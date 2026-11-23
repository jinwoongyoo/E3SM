#!/usr/bin/env python
"""Build the Texas-box r05 inputs for the Aegis Phase 1 E3SM land baseline.

Creates, from the global E3SM/CESM half-degree inputs in DIN_LOC_ROOT:
  domain.lnd.r05_texas.<tag>.nc        ELM/DATM/MOSART domain (mask/frac from
                                       domain.lnd.r05_IcoswISC30E3r5.231121.nc)
  surfdata_r05_texas_simyr2000.<tag>.nc  subset of surfdata_0.5x0.5_simyr2000_c200624.nc
  MOSART_r05_texas.<tag>.nc           subset of MOSART_global_half_20180721a.nc with
                                       IDs renumbered 1..N on the subset grid and
                                       cells draining out of the box turned into outlets
  inputs_manifest.json                 sha256, sizes, box, cell counts, basin checks

Box: cell centres with 25.5 < lat < 37 and -107 < lon < -93 (23 x 28 cells).

usage: make_inputs.py OUTDIR [--tag TAG]
"""
import argparse
import datetime as dt
import hashlib
import json
import os

import numpy as np
import xarray as xr

from p1lib import GAUGES, match_gauge, terminal_outlets

DIN = os.environ.get("DIN_LOC_ROOT", "/Volumes/SSD-Data/aegis-data/e3sm-work/inputdata")
SRC_DOMAIN = f"{DIN}/share/domains/domain.lnd.r05_IcoswISC30E3r5.231121.nc"
SRC_SURF = f"{DIN}/lnd/clm2/surfdata_map/surfdata_0.5x0.5_simyr2000_c200624.nc"
SRC_MOSART = f"{DIN}/rof/mosart/MOSART_global_half_20180721a.nc"
LAT0, LAT1, LON0, LON1 = 25.5, 37.0, -107.0, -93.0

# Rio Grande mouth (checked for inflow lost at the box edge); the Harvey basins
# are checked from the scoring gauges in p1lib.GAUGES.
RIO_GRANDE_MOUTH = (25.96, -97.15)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def box_index(lat1d, lon1d):
    lon1d = ((np.asarray(lon1d) + 180.0) % 360.0) - 180.0
    jj = np.where((lat1d > LAT0) & (lat1d < LAT1))[0]
    ii = np.where((lon1d > LON0) & (lon1d < LON1))[0]
    assert len(jj) == 23 and len(ii) == 28, (len(jj), len(ii))
    assert np.all(np.diff(jj) == 1) and np.all(np.diff(ii) == 1)
    return jj, ii


def stamp(ds, src, what):
    ds.attrs["aegis_phase1"] = (
        f"{what}: Texas box subset ({LAT0}-{LAT1}N, {LON0}-{LON1}E cell centres) of "
        f"{os.path.basename(src)}; created {dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%MZ} "
        "by aegis/phase1/scripts/make_inputs.py"
    )
    return ds


def make_domain(out):
    d = xr.open_dataset(SRC_DOMAIN)
    jj, ii = box_index(d.yc.values[:, 0], d.xc.values[0, :])
    s = d.isel(nj=jj, ni=ii).load()
    s = s.drop_dims("n", errors="ignore")
    stamp(s, SRC_DOMAIN, "ELM/MOSART domain")
    enc = {v: {"_FillValue": None} for v in s.variables}
    s.to_netcdf(out, format="NETCDF3_64BIT", encoding=enc)
    return s, jj, ii


def make_surfdata(out, jj, ii, dom):
    d = xr.open_dataset(SRC_SURF, decode_times=False, mask_and_scale=False)
    lat = d.LATIXY.values[:, 0]
    lon = d.LONGXY.values[0, :]
    j2, i2 = box_index(lat, lon)
    s = d.isel(lsmlat=j2, lsmlon=i2).load()
    dl = ((s.LONGXY.values + 180) % 360) - 180
    assert np.allclose(dl, dom.xc.values, atol=1e-6) and np.allclose(s.LATIXY.values, dom.yc.values, atol=1e-6)
    stamp(s, SRC_SURF, "ELM surface dataset (sim year 2000)")
    enc = {v: {"_FillValue": None} for v in s.variables if "_FillValue" not in s[v].attrs}
    s.to_netcdf(out, format="NETCDF4_CLASSIC", encoding=enc)
    return s


def trace_upstream(dn_glob, start):
    """All global flat indices (0-based) upstream of (and including) start."""
    n = dn_glob.size
    ups = [[] for _ in range(n)]
    for k in np.where(dn_glob >= 0)[0]:
        ups[dn_glob[k]].append(k)
    seen, stack = {start}, [start]
    while stack:
        k = stack.pop()
        for u in ups[k]:
            if u not in seen:
                seen.add(u)
                stack.append(u)
    return np.fromiter(seen, int)


def make_mosart(out, dom):
    m = xr.open_dataset(SRC_MOSART, mask_and_scale=False)
    nlat, nlon = m.sizes["lat"], m.sizes["lon"]
    jj, ii = box_index(m.lat.values, m.lon.values)
    ID = m.ID.values.astype(np.int64)
    dn = m.dnID.values.astype(np.int64)
    # global flat (0-based) index of each ID, and of each cell's downstream
    key = np.full(nlat * nlon + 1, -1, np.int64)
    key[ID.ravel()] = np.arange(nlat * nlon)
    dn_flat = dn.ravel()
    dn_glob = np.where((dn_flat >= 1) & (dn_flat <= nlat * nlon), key[np.clip(dn_flat, 0, nlat * nlon)], -1)

    inbox = np.zeros((nlat, nlon), bool)
    inbox[np.ix_(jj, ii)] = True
    inbox = inbox.ravel()

    sub = {}
    dims_map = {}
    for dname in m.dims:
        if dname in ("lat", "ncl0", "ncl2", "ncl4", "ncl6"):
            dims_map[dname] = jj
        elif dname in ("lon", "ncl1", "ncl3", "ncl5", "ncl7"):
            dims_map[dname] = ii
    s = m.isel(**dims_map).load()

    ny, nx = len(jj), len(ii)
    new_id = np.arange(1, ny * nx + 1, dtype=np.int64).reshape(ny, nx)  # lon fastest, S->N
    glob_to_new = np.full(nlat * nlon, -9999, np.int64)
    gflat = (jj[:, None] * nlon + ii[None, :]).ravel()
    glob_to_new[gflat] = new_id.ravel()

    sub_dn_glob = dn_glob[gflat]
    leaves = (sub_dn_glob >= 0) & ~inbox[np.clip(sub_dn_glob, 0, None)]
    new_dn = np.where(sub_dn_glob >= 0, glob_to_new[np.clip(sub_dn_glob, 0, None)], -9999)
    new_dn[leaves] = -9999
    fdir = s.fdir.values.ravel().copy()
    n_new_outlets = int(np.sum(leaves & (fdir > 0)))
    fdir[leaves & (fdir > 0)] = 0  # basin outlet (Tunit mask 2)

    s["ID"] = (s.ID.dims, new_id.astype(s.ID.dtype).reshape(ny, nx), s.ID.attrs)
    s["dnID"] = (s.dnID.dims, new_dn.astype(s.dnID.dtype).reshape(ny, nx), s.dnID.attrs)
    s["fdir"] = (s.fdir.dims, fdir.astype(s.fdir.dtype).reshape(ny, nx), s.fdir.attrs)
    if "frac" in s:
        fr = s.frac.values
        if np.any((fdir.reshape(ny, nx) >= 0) & (np.abs(fr - 1) > 1e-9)):
            raise SystemExit("frac != 1 on an active MOSART cell in the box")
    lonxy = ((s.longxy.values + 180) % 360) - 180
    assert np.allclose(lonxy, dom.xc.values) and np.allclose(s.latixy.values, dom.yc.values)
    stamp(s, SRC_MOSART, "MOSART parameters (IDs renumbered; out-of-box downstream -> outlet)")
    s.attrs["aegis_phase1_note"] = (
        "Cells whose downstream cell lies outside the box are basin outlets (dnID=-9999, fdir=0). "
        "Inflow from outside the box (e.g. Rio Grande from NM/CO, Canadian/Red River headwaters "
        "north of 37N, Arkansas River) is not represented."
    )
    s.to_netcdf(out, format="NETCDF3_64BIT")

    # ---- diagnostics: basins fully inside box? cells losing inflow?
    flat_lat = np.repeat(m.lat.values, nlon)
    flat_lon = np.tile(m.lon.values, nlat)
    basins = {}
    lat2d = np.repeat(m.lat.values[:, None], nlon, 1)
    lon2d = np.repeat(m.lon.values[None, :], nlat, 0)
    a2 = m.areaTotal2.values / 1e6

    def downstream_outlet(k):
        while dn_glob[k] >= 0:
            k = dn_glob[k]
        return k

    outl = terminal_outlets(dn_glob).reshape(nlat, nlon)
    for site, g in GAUGES.items():
        j, i, amod = match_gauge(lat2d, lon2d, a2, g["lat"], g["lon"], g["area_km2"], outlet2d=outl)
        k = j * nlon + i
        up = trace_upstream(dn_glob, k)
        kout = downstream_outlet(k)
        upo = trace_upstream(dn_glob, kout)
        basins[f"{g['river']} {site}"] = {
            "gauge_cell_latlon": [float(flat_lat[k]), float(flat_lon[k])],
            "gauge_cell_areaTotal2_km2": round(amod, 1),
            "usgs_drain_area_km2": g["area_km2"],
            "area_ratio_model_over_usgs": round(amod / g["area_km2"], 3),
            "upstream_of_gauge_fully_inside_box": bool(inbox[up].all()),
            "outlet_cell_latlon": [float(flat_lat[kout]), float(flat_lon[kout])],
            "outlet_inside_box": bool(inbox[kout]),
            "whole_basin_fully_inside_box": bool(inbox[upo].all()),
        }
    j = int(np.argmin(np.abs(m.lat.values - RIO_GRANDE_MOUTH[0])))
    i = int(np.argmin(np.abs(m.lon.values - RIO_GRANDE_MOUTH[1])))
    jj3, ii3 = np.unravel_index(np.argmax(np.where(np.abs(lat2d - lat2d[j, i]) <= 0.6, 1, 0) *
                                          np.where(np.abs(lon2d - lon2d[j, i]) <= 0.6, 1, 0) *
                                          np.nan_to_num(a2)), a2.shape)
    k = jj3 * nlon + ii3
    up = trace_upstream(dn_glob, k)
    basins["Rio Grande (mouth)"] = {
        "outlet_cell_latlon": [float(flat_lat[k]), float(flat_lon[k])],
        "areaTotal2_km2": round(float(a2[jj3, ii3]), 1),
        "n_cells_upstream": int(up.size),
        "n_cells_outside_box": int((~inbox[up]).sum()),
        "area_outside_box_km2": round(float(np.nansum(m.area.values.ravel()[up[~inbox[up]]])) / 1e6, 1),
        "whole_basin_fully_inside_box": bool(inbox[up].all()),
    }
    # cells in the box that receive inflow from outside
    recv = set()
    outside_cells = np.where(~inbox & (dn_glob >= 0))[0]
    for k in outside_cells:
        if inbox[dn_glob[k]]:
            recv.add(int(dn_glob[k]))
    lost = [[float(flat_lat[k]), float(flat_lon[k]), round(float(m.areaTotal2.values.ravel()[k]) / 1e6, 1)] for k in sorted(recv)]
    return s, {
        "n_cells": int(ny * nx),
        "n_new_outlets_box_edge": n_new_outlets,
        "basins": basins,
        "box_cells_with_inflow_from_outside": lost,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--tag", default=dt.date.today().strftime("c%y%m%d"))
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    f_dom = os.path.join(a.outdir, f"domain.lnd.r05_texas.{a.tag}.nc")
    f_srf = os.path.join(a.outdir, f"surfdata_r05_texas_simyr2000.{a.tag}.nc")
    f_mos = os.path.join(a.outdir, f"MOSART_r05_texas.{a.tag}.nc")

    dom, jj, ii = make_domain(f_dom)
    nland = int((dom.mask.values > 0).sum())
    make_surfdata(f_srf, jj, ii, dom)
    _, mos_diag = make_mosart(f_mos, dom)

    man = {
        "box": {"lat": [LAT0, LAT1], "lon": [LON0, LON1], "nj": 23, "ni": 28},
        "n_land_cells_domain_mask": nland,
        "sources": {k: {"path": p, "sha256": sha256(p)} for k, p in
                    (("domain", SRC_DOMAIN), ("surfdata", SRC_SURF), ("mosart", SRC_MOSART))},
        "outputs": {os.path.basename(p): {"sha256": sha256(p), "bytes": os.path.getsize(p)}
                    for p in (f_dom, f_srf, f_mos)},
        "mosart": mos_diag,
        "surfdata_sim_year": 2000,
    }
    with open(os.path.join(a.outdir, "inputs_manifest.json"), "w") as f:
        json.dump(man, f, indent=1)
    print(json.dumps({k: man[k] for k in ("n_land_cells_domain_mask", "mosart")}, indent=1))


if __name__ == "__main__":
    main()
