#!/usr/bin/env python
"""Remap Texas-box ELM history fields (r05) to E3SM ne30pg2 columns.

Uses E3SM's conservative r05 -> ne30pg2 map (map_r05_to_ne30pg2_traave.20231130.nc,
global). The Texas fields are placed in the global r05 grid (all other cells
treated as missing), and each ne30pg2 column gets a land-area-weighted
conservative mean:

    x_b = sum_a S_ba * landfrac_a * x_a / sum_a S_ba * landfrac_a

The sums run over box cells with valid (finite) data. Only the ne30pg2
columns that overlap the box are written (dimension ncol). `ncol_global`
(0-based) gives their index in the full 21600-column ne30pg2 grid.
`box_area_frac` is the fraction of the column's area inside the box: columns
with box_area_frac < 1 on the box edge average only the part inside the box.
`land_area_frac` is the fraction of the column's area that is (box) land.

usage: remap_ne30pg2.py RUNDIR CASE TAPE OUT.nc [--fields A,B,...] [--map MAP]
       (TAPE = h1 daily, h2 hourly)
"""
import argparse
import glob
import os

import numpy as np
import xarray as xr

from p1lib import open_hist

DIN = os.environ.get("DIN_LOC_ROOT", "/Volumes/SSD-Data/aegis-data/e3sm-work/inputdata")
DEFAULT_MAP = os.path.join(DIN, "cpl/gridmaps/ne30pg2/map_r05_to_ne30pg2_traave.20231130.nc")
KEY = ["H2OSOI", "SOILWATER_10CM", "TSOI", "H2OSNO", "QRUNOFF", "QOVER", "QDRAI", "ZWT", "TWS",
       "FSH", "EFLX_LH_TOT", "RAIN", "TSA"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rundir")
    ap.add_argument("case")
    ap.add_argument("tape")
    ap.add_argument("out")
    ap.add_argument("--fields", default=",".join(KEY))
    ap.add_argument("--map", default=DEFAULT_MAP)
    a = ap.parse_args()
    fields = a.fields.split(",")
    files = sorted(glob.glob(os.path.join(a.rundir, f"{a.case}.elm.{a.tape}.*.nc")))
    if not files:
        raise SystemExit(f"no {a.case}.elm.{a.tape}.*.nc files in {a.rundir}")
    ds = open_hist(files, fields)

    m = xr.open_dataset(a.map)
    nlon_g, nlat_g = (int(v) for v in m.src_grid_dims.values)
    lat = ds.lat.values
    lon = ds.lon.values
    jg = np.rint((lat + 89.75) / 0.5).astype(int)
    ig = np.rint((((lon + 180.0) % 360.0) - 180.0 + 179.75) / 0.5).astype(int)
    # sanity: the map source cell centres must coincide with the box cell centres
    src_idx = (jg[:, None] * nlon_g + ig[None, :])            # (nlat, nlon) global flat index
    xa = m.xc_a.values[src_idx]
    ya = m.yc_a.values[src_idx]
    assert np.allclose(ya, lat[:, None]) and np.allclose(((xa + 180) % 360) - 180, ((lon[None, :] + 180) % 360) - 180)

    # sparse -> dense block restricted to box sources
    col = m.col.values.astype(np.int64) - 1
    row = m.row.values.astype(np.int64) - 1
    S = m.S.values
    flat_box = src_idx.ravel()
    pos = np.full(nlon_g * nlat_g, -1, np.int64)
    pos[flat_box] = np.arange(flat_box.size)
    sel = pos[col] >= 0
    rows_used = np.unique(row[sel])
    rpos = {r: k for k, r in enumerate(rows_used)}
    W = np.zeros((rows_used.size, flat_box.size))
    for r, c, s in zip(row[sel], pos[col[sel]], S[sel]):
        W[rpos[r], c] += s
    lf = np.nan_to_num(ds.landfrac.values.ravel()) * (ds.landmask.values.ravel() > 0)
    box_area_frac = W.sum(1)
    land_area_frac = W @ lf

    out = xr.Dataset(coords=dict(time=ds.time))
    out["time_bounds"] = ds.time_bounds
    out["ncol_global"] = ("ncol", rows_used.astype(np.int32),
                          {"long_name": "0-based index of the column in the ne30pg2 grid (21600 columns)"})
    out["lat"] = ("ncol", m.yc_b.values[rows_used], {"units": "degrees_north"})
    out["lon"] = ("ncol", m.xc_b.values[rows_used], {"units": "degrees_east"})
    out["area"] = ("ncol", m.area_b.values[rows_used], {"units": "sr"})
    out["box_area_frac"] = ("ncol", box_area_frac,
                            {"long_name": "fraction of the column area inside the Texas r05 box"})
    out["land_area_frac"] = ("ncol", land_area_frac,
                             {"long_name": "fraction of the column area that is box land (ELM landfrac)"})
    for v in fields:
        if v not in ds:
            print("skip (not on tape):", v)
            continue
        x = ds[v]
        other = [d for d in x.dims if d not in ("time", "lat", "lon")]
        xt = x.transpose("time", *other, "lat", "lon").values
        shp = xt.shape[:-2]
        xf = xt.reshape(-1, flat_box.size).T                   # (nsrc, ntime*nlev)
        valid = np.isfinite(xf) & (np.abs(xf) < 1e30)
        num = W @ (np.where(valid, xf, 0.0) * lf[:, None])
        den = W @ (valid * lf[:, None])
        with np.errstate(invalid="ignore", divide="ignore"):
            y = np.where(den > 0, num / den, np.nan)
        y = y.T.reshape(*shp, rows_used.size).astype(np.float32)
        attrs = {k: x.attrs[k] for k in ("long_name", "units") if k in x.attrs}
        attrs["cell_methods"] = "ncol: land-area-weighted conservative mean (map_r05_to_ne30pg2_traave)"
        out[v] = (("time", *other, "ncol"), y, attrs)
    out.attrs.update(
        title="Aegis Phase 1 E3SM ELM (SP, NLDAS-2) Texas baseline remapped to ne30pg2",
        source_case=a.case, source_tape=a.tape, n_source_files=len(files),
        map_file=os.path.basename(a.map),
        note=("Uncalibrated baseline; only ne30pg2 columns overlapping the Texas r05 box are "
              "included; see box_area_frac / land_area_frac."),
    )
    enc = {v: {"zlib": True, "complevel": 4} for v in out.data_vars if out[v].dtype == np.float32}
    enc["time"] = {"units": "days since 2010-01-01 00:00:00", "calendar": "noleap"}
    enc["time_bounds"] = {"units": "days since 2010-01-01 00:00:00", "calendar": "noleap"}
    out["time"].attrs.update(bounds="time_bounds", long_name="midpoint of averaging interval")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tmp = a.out + ".part"
    out.to_netcdf(tmp, encoding=enc, unlimited_dims=["time"])
    os.replace(tmp, a.out)
    print(f"{a.out}: {out.sizes['time']} times, {rows_used.size} columns "
          f"({int((box_area_frac > 0.999).sum())} fully inside the box)")


if __name__ == "__main__":
    main()
