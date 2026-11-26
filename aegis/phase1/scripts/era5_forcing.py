#!/usr/bin/env python
"""ERA5 DATM forcing for the Phase 1 Texas box (ELMERA5 layout).

Writes a regional copy of E3SM's ``atm_forcing.datm7.ERA.0.25d.v5.c180614``
(DATM_MODE=ELMERA5), which on the E3SM inputdata server only has 1979 and 1981.
Same variables, units, time stamps and calendar; only the grid is cut to the box.

  fetch   YEAR0 YEAR1 [--source ncar|cds] [--workers N]
                                     monthly box subsets -> $ERA5_RAW (resumable)
  convert YEAR0 YEAR1                raw -> $DIN/atm/datm7/<FORC_DIR>/<sub>/*.nc
  domain                             stream domain file for the subset grid
  streams YEAR0 YEAR1                user_datm.streams.txt.ELMERA5.* templates
                                     -> aegis/phase1/forcing/era5/

Sources (same raw format either way):
* ncar (default): NSF NCAR ERA5 (RDA ds633.0) netCDF on public AWS S3
  (s3://nsf-ncar-era5), read with HTTP byte ranges. Analysis fields
  (e5.oper.an.sfc) are chunked spatially, so only the box is read; mean-flux
  forecast fields (e5.oper.fc.sfc.meanflux, 06/18Z inits, steps 1-12) are
  chunked per init, so whole global chunks are read and cut. Valid time is
  init + step, the end of the averaging hour, as in CDS.
* cds: Copernicus CDS API. Correct but slow: CDS queues one request per user
  and dataset, and monthly requests have waited ~11 h each.

Conventions (checked against the E3SM 1981 files, see README):
* A file value at time t equals the CDS value at valid_time t. For mean fields
  (avg_*) that is the mean over the hour ending at t; the stock ELMERA5 stream
  offsets (-3600 s for swdn, -60 s for prec/lwdn) handle that.
* msdfswrf = avg_sdswrf - avg_sdirswrf, w10 = hypot(u10, v10).
* noleap: Feb 29 is dropped; time = days since the 1st of the month 00Z.
* lat ascending, lon in 0..360.
"""
import argparse
import os
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

WORK = Path("/Volumes/SSD-Data/aegis-data/e3sm-work")
DIN = Path(os.environ.get("DIN_LOC_ROOT", WORK / "inputdata"))
RAW = Path(os.environ.get("ERA5_RAW", WORK / "era5/raw"))
TAG = "c261126"
FORC_DIR = f"atm_forcing.datm7.ERA5.0.25d.texas.{TAG}"
DOMAIN_NAME = f"domain.lnd.era5_texas_55x65.{TAG}.nc"
DOMAIN_DIR = DIN / "share/domains/domain.clm"
GLOBAL_DOMAIN = DIN / "atm/datm7/atm_forcing.datm7.ERA.0.25d.v5.c180614/domain.lnd.era5_721x1440_rdrlat_EC30to60E2r2.221115.nc"
GLOBAL_DOMAIN_URL = ("https://web.lcrc.anl.gov/public/e3sm/inputdata/atm/datm7/"
                     "atm_forcing.datm7.ERA.0.25d.v5.c180614/" + GLOBAL_DOMAIN.name)
# r05 model box is 25.5-37N, 107-93W; keep >= 1 deg of margin for bilinear mapping
AREA = [38.0, -108.0, 24.5, -92.0]  # N, W, S, E (CDS order)
FORK = Path(__file__).resolve().parents[1]

CDS_VARS = [
    "2m_temperature", "2m_dewpoint_temperature", "surface_pressure",
    "10m_u_component_of_wind", "10m_v_component_of_wind",
    "mean_surface_direct_short_wave_radiation_flux",
    "mean_surface_downward_short_wave_radiation_flux",
    "mean_convective_precipitation_rate", "mean_large_scale_precipitation_rate",
    "mean_surface_downward_long_wave_radiation_flux",
]

# (subdir, stream/var name, units, long_name, cell_method)
OUT = [
    ("swdn", "msdrswrf", "W m**-2", "Mean surface direct short-wave radiation flux", "mean"),
    ("swdn", "msdfswrf", "W m**-2", "Mean surface diffuse short-wave radiation flux", "mean"),
    ("prec", "mcpr", "kg m**-2 s**-1", "Mean convective precipitation rate", "mean"),
    ("prec", "mlspr", "kg m**-2 s**-1", "Mean large-scale precipitation rate", "mean"),
    ("tbot", "t2m", "K", "2 metre temperature", "point"),
    ("pbot", "sp", "Pa", "Surface pressure", "point"),
    ("tdew", "d2m", "K", "2 metre dewpoint temperature", "point"),
    ("wind", "w10", "m s**-1", "10 metre wind speed", "point"),
    ("lwdn", "msdwlwrf", "W m**-2", "Mean surface downward long-wave radiation flux", "mean"),
]
# DATM field name for each stream (namelist_definition_datm.xml, ELMERA5)
DATM_NAME = {"msdrswrf": "swdndr", "msdfswrf": "swdndf", "mcpr": "precc", "mlspr": "precl",
             "t2m": "tbot", "sp": "pbot", "d2m": "tdew", "w10": "wind", "msdwlwrf": "lwdn"}


def months(y0, y1):
    return [(y, m) for y in range(y0, y1 + 1) for m in range(1, 13)]


def raw_paths(y, m):
    b = RAW / f"era5_texas_{y}-{m:02d}"
    return b.with_name(b.name + "_instant.nc"), b.with_name(b.name + "_avg.nc")


# ---------------------------------------------------------------- fetch
def fetch_one(y, m):
    import calendar
    import cdsapi
    inst, avg = raw_paths(y, m)
    if inst.exists() and avg.exists():
        return f"{y}-{m:02d} exists"
    nd = calendar.monthrange(y, m)[1]
    z = RAW / f".era5_texas_{y}-{m:02d}.zip.part"
    cdsapi.Client(quiet=True, progress=False).retrieve("reanalysis-era5-single-levels", {
        "product_type": ["reanalysis"], "variable": CDS_VARS,
        "year": [str(y)], "month": [f"{m:02d}"], "day": [f"{d:02d}" for d in range(1, nd + 1)],
        "time": [f"{h:02d}:00" for h in range(24)], "area": AREA,
        "data_format": "netcdf", "download_format": "zip"}, str(z))
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        for n, dst in (("instant", inst), ("avg", avg)):
            src = [s for s in names if f"stepType-{n}" in s]
            if len(src) != 1:
                raise RuntimeError(f"{y}-{m:02d}: expected one {n} file in {names}")
            tmp = dst.with_suffix(".part")
            tmp.write_bytes(zf.read(src[0]))
            check_raw(tmp, y, m, n)
            tmp.rename(dst)
    z.unlink()
    return f"{y}-{m:02d} ok"


# ---------------------------------------------------------------- fetch (NCAR)
NCAR = "https://nsf-ncar-era5.s3.amazonaws.com"
# raw name -> (NCAR product, file param, HDF5 variable)
NCAR_AN = {"t2m": "128_167_2t", "d2m": "128_168_2d", "sp": "128_134_sp",
           "u10": "128_165_10u", "v10": "128_166_10v"}
NCAR_MF = {"avg_sdirswrf": "235_058_msdrswrf", "avg_sdswrf": "235_035_msdwswrf",
           "avg_cpr": "235_030_mcpr", "avg_lsprate": "235_029_mlspr",
           "avg_sdlwrf": "235_036_msdwlwrf"}
NCAR_UNITS = {"t2m": "K", "d2m": "K", "sp": "Pa", "u10": "m s**-1", "v10": "m s**-1",
              "avg_sdirswrf": "W m**-2", "avg_sdswrf": "W m**-2", "avg_cpr": "kg m**-2 s**-1",
              "avg_lsprate": "kg m**-2 s**-1", "avg_sdlwrf": "W m**-2"}
H1900 = np.datetime64("1900-01-01T00", "h")


def s3_keys(prefix):
    import re
    import requests
    keys, tok = [], None
    while True:
        q = {"list-type": "2", "prefix": prefix}
        if tok:
            q["continuation-token"] = tok
        r = requests.get(NCAR + "/", params=q, timeout=120)
        r.raise_for_status()
        keys += re.findall(r"<Key>([^<]+)</Key>", r.text)
        m = re.search(r"<NextContinuationToken>([^<]+)<", r.text)
        if not m:
            return keys
        tok = m.group(1)


def h5open(key):
    import fsspec
    import h5py
    return h5py.File(fsspec.open(f"{NCAR}/{key}", block_size=2**22).open(), "r")


def box_index(f):
    lat = f["latitude"][:]
    lon = f["longitude"][:]
    j = np.where((lat <= AREA[0] + 1e-6) & (lat >= AREA[2] - 1e-6))[0]
    i = np.where((lon >= AREA[1] % 360 - 1e-6) & (lon <= AREA[3] % 360 + 1e-6))[0]
    return slice(j[0], j[-1] + 1), slice(i[0], i[-1] + 1), lat[j], lon[i]


def retry(fn, *args, tries=5):
    import time
    for k in range(tries):
        try:
            return fn(*args)
        except (OSError, ConnectionError, TimeoutError):  # network only; logic errors fail fast
            if k == tries - 1:
                raise
            time.sleep(10 * (k + 1))


def ncar_an(var, y, m, t0, t1):
    import h5py
    key = [k for k in s3_keys(f"e5.oper.an.sfc/{y}{m:02d}/") if f".{NCAR_AN[var]}." in k]
    if len(key) != 1:
        raise RuntimeError(f"{y}-{m:02d} {var}: {key}")
    with h5open(key[0]) as f:
        js, is_, lat, lon = box_index(f)
        hv = [k for k in f if isinstance(f[k], h5py.Dataset) and f[k].ndim == 3][0]
        t = H1900 + f["time"][:].astype("i8")
        sel = (t >= t0) & (t < t1)
        x = f[hv][:, js, is_][sel]
    return t[sel], lat, lon, x


def ncar_mf(var, y, m, t0, t1):
    import h5py
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    keys = [k for p in (f"{py}{pm:02d}", f"{y}{m:02d}")
            for k in s3_keys(f"e5.oper.fc.sfc.meanflux/{p}/") if f".{NCAR_MF[var]}." in k]
    out_t, out_x, lat, lon = [], [], None, None
    for key in keys:
        with h5open(key) as f:
            js, is_, lat, lon = box_index(f)
            hv = [k for k in f if isinstance(f[k], h5py.Dataset) and f[k].ndim == 4][0]
            init = H1900 + f["forecast_initial_time"][:].astype("i8")
            fh = f["forecast_hour"][:].astype("i8")
            for n, it in enumerate(init):
                vt = it + fh.astype("timedelta64[h]")
                sel = (vt >= t0) & (vt < t1)
                if sel.any():
                    out_x.append(f[hv][n, :, js, is_][sel])
                    out_t.append(vt[sel])
    t = np.concatenate(out_t)
    x = np.concatenate(out_x)
    o = np.argsort(t)
    return t[o], lat, lon, x[o]


def write_raw(path, t, lat, lon, fields):
    import netCDF4 as nc
    tmp = path.with_suffix(".part")
    with nc.Dataset(tmp, "w", format="NETCDF4_CLASSIC") as d:
        d.createDimension("valid_time", len(t)); d.createDimension("latitude", len(lat))
        d.createDimension("longitude", len(lon))
        v = d.createVariable("valid_time", "i4", ("valid_time",))
        v.units, v.calendar = "hours since 1900-01-01", "proleptic_gregorian"
        v[:] = (t - H1900).astype("i4")
        d.createVariable("latitude", "f8", ("latitude",))[:] = lat
        d.createVariable("longitude", "f8", ("longitude",))[:] = lon
        for k, x in fields.items():
            v = d.createVariable(k, "f4", ("valid_time", "latitude", "longitude"), zlib=True, complevel=1)
            v.units = NCAR_UNITS[k]
            v[:] = x
        d.source = f"NSF NCAR ERA5 (RDA ds633.0) via {NCAR}"
    return tmp


def fetch_ncar(y, m):
    inst, avg = raw_paths(y, m)
    if inst.exists() and avg.exists():
        return f"{y}-{m:02d} exists"
    t0 = np.datetime64(f"{y}-{m:02d}-01T00", "h")
    t1 = np.datetime64(f"{y + (m == 12)}-{m % 12 + 1:02d}-01T00", "h")
    expect = np.arange(t0, t1)
    for path, table, reader, kind in ((inst, NCAR_AN, ncar_an, "instant"), (avg, NCAR_MF, ncar_mf, "avg")):
        if path.exists():
            continue
        fields, ref = {}, None
        for var in table:
            t, lat, lon, x = retry(reader, var, y, m, t0, t1)
            if not np.array_equal(t, expect):
                raise RuntimeError(f"{y}-{m:02d} {var}: {len(t)} steps, expected {len(expect)}")
            if np.nanmax(np.abs(x)) > 1e19 or not np.all(np.isfinite(x)):
                raise RuntimeError(f"{y}-{m:02d} {var}: fill or non-finite values")
            if ref is None:
                ref = (lat, lon)
            elif not (np.array_equal(ref[0], lat) and np.array_equal(ref[1], lon)):
                raise RuntimeError(f"{y}-{m:02d} {var}: grid differs")
            fields[var] = x
        tmp = write_raw(path, expect, ref[0], ref[1], fields)
        check_raw(tmp, y, m, kind)
        tmp.rename(path)
    return f"{y}-{m:02d} ok"


def check_raw(path, y, m, kind):
    import calendar
    import netCDF4 as nc
    with nc.Dataset(path) as d:
        nt = len(d["valid_time"])
        exp = calendar.monthrange(y, m)[1] * 24
        if nt != exp:
            raise RuntimeError(f"{path}: {nt} steps, expected {exp}")
        need = {"instant": ["t2m", "d2m", "sp", "u10", "v10"],
                "avg": ["avg_sdirswrf", "avg_sdswrf", "avg_cpr", "avg_lsprate", "avg_sdlwrf"]}[kind]
        miss = [v for v in need if v not in d.variables]
        if miss:
            raise RuntimeError(f"{path}: missing {miss}")


def cmd_fetch(a):
    RAW.mkdir(parents=True, exist_ok=True)
    todo = months(a.y0, a.y1)
    one = fetch_one if a.source == "cds" else fetch_ncar
    fails = []
    with ProcessPoolExecutor(a.workers) as ex:
        fut = {ex.submit(one, y, m): (y, m) for y, m in todo}
        for f in as_completed(fut):
            y, m = fut[f]
            try:
                print(f.result(), flush=True)
            except Exception as e:  # keep going; re-run picks up the rest
                fails.append((y, m))
                print(f"{y}-{m:02d} FAILED: {e}", flush=True)
    print(f"done: {len(todo) - len(fails)}/{len(todo)} months", flush=True)
    return 1 if fails else 0


# ---------------------------------------------------------------- convert
def read_month(y, m):
    import netCDF4 as nc
    inst, avg = raw_paths(y, m)
    I, A = nc.Dataset(inst), nc.Dataset(avg)
    t = nc.num2date(I["valid_time"][:], I["valid_time"].units)
    ta = nc.num2date(A["valid_time"][:], A["valid_time"].units)
    if any(a != b for a, b in zip(t, ta)):
        raise RuntimeError(f"{y}-{m:02d}: instant/avg time axes differ")
    keep = np.array([not (x.month == 2 and x.day == 29) for x in t])
    lat = np.asarray(I["latitude"][:], "f8")
    lon = np.asarray(I["longitude"][:], "f8") % 360.0
    flip = lat[0] > lat[-1]

    def g(d, v):
        x = np.asarray(d[v][:], "f8")[keep]
        return x[:, ::-1, :] if flip else x

    sdir, sdn = g(A, "avg_sdirswrf"), g(A, "avg_sdswrf")
    f = {"t2m": g(I, "t2m"), "d2m": g(I, "d2m"), "sp": g(I, "sp"),
         "w10": np.hypot(g(I, "u10"), g(I, "v10")),
         "msdrswrf": sdir, "msdfswrf": np.maximum(sdn - sdir, 0.0), "msdwswrf": sdn,
         "mcpr": np.maximum(g(A, "avg_cpr"), 0.0), "mlspr": np.maximum(g(A, "avg_lsprate"), 0.0),
         "msdwlwrf": g(A, "avg_sdlwrf")}
    hrs = np.array([(x.day - 1) * 24 + x.hour for x in np.asarray(t)[keep]], "f8")
    I.close(); A.close()
    for k, v in f.items():
        if not np.all(np.isfinite(v)):
            raise RuntimeError(f"{y}-{m:02d} {k}: non-finite values")
    return (lat[::-1] if flip else lat), lon, hrs / 24.0, f


def write_var(path, y, m, lat, lon, tdays, var, data, units, lname, cm, extra=None):
    import netCDF4 as nc
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".nc.part")
    with nc.Dataset(tmp, "w", format="NETCDF4_CLASSIC") as d:
        d.createDimension("scalar", 1)
        d.createDimension("lat", len(lat))
        d.createDimension("lon", len(lon))
        d.createDimension("time", None)
        dlon = lon[1] - lon[0]
        dlat = lat[1] - lat[0]
        for n, val, u, ln in (("EDGEE", lon[-1] + dlon / 2, "degrees_east", "eastern edge in atmospheric data"),
                              ("EDGEN", lat[-1] + dlat / 2, "degrees_north", "northern edge in atmospheric data"),
                              ("EDGES", lat[0] - dlat / 2, "degrees_north", "southern edge in atmospheric data"),
                              ("EDGEW", lon[0] - dlon / 2, "degrees_east", "western edge in atmospheric data")):
            v = d.createVariable(n, "f4", ("scalar",))
            v.long_name, v.mode, v.units = ln, "time-invariant", u
            v[:] = val
        LON, LAT = np.meshgrid(lon, lat)
        for n, arr, u, ln in (("LATIXY", LAT, "degrees_north", "latitude"),
                              ("LONGXY", LON, "degrees_east", "longitude")):
            v = d.createVariable(n, "f4", ("lat", "lon"))
            v.long_name, v.mode, v.units = ln, "time-invariant", u
            v[:] = arr
        v = d.createVariable("lat", "f4", ("lat",)); v.units, v.long_name = "degrees_north", "latitude"; v[:] = lat
        v = d.createVariable("lon", "f4", ("lon",)); v.units, v.long_name = "degrees_east", "longitude"; v[:] = lon
        v = d.createVariable("time", "f8", ("time",))
        v.calendar, v.long_name, v.units = "noleap", "time", f"days since {y}-{m:02d}-01 00:00:00"
        v[:] = tdays
        for n, arr, u, ln in [(var, data, units, lname)] + (extra or []):
            v = d.createVariable(n, "f4", ("time", "lat", "lon"), zlib=True, complevel=1)
            v.units, v.long_name, v.cell_methods = u, ln, f"time: {cm}"
            v[:] = arr.astype("f4")
        d.title = "ERA5 hourly single levels, Texas box subset in E3SM ELMERA5 layout"
        d.source = "Copernicus Climate Change Service (C3S) Climate Data Store, reanalysis-era5-single-levels"
        d.history = f"aegis/phase1/scripts/era5_forcing.py convert ({FORC_DIR})"
    tmp.rename(path)


def out_path(sub, var, y, m):
    return DIN / "atm/datm7" / FORC_DIR / sub / f"elmforc.ERA5.texas.0.25d.{var}.{y}-{m:02d}.nc"


def cmd_convert(a):
    n = 0
    for y, m in months(a.y0, a.y1):
        outs = [out_path(s, v, y, m) for s, v, *_ in OUT]
        if all(p.exists() for p in outs):
            continue
        if not all(p.exists() for p in raw_paths(y, m)):
            print(f"{y}-{m:02d} raw files missing, skipped", flush=True)
            continue
        lat, lon, td, f = read_month(y, m)
        for (sub, var, u, ln, cm), p in zip(OUT, outs):
            extra = None
            if var == "msdrswrf":  # the E3SM file carries the total as a second variable
                extra = [("msdwswrf", f["msdwswrf"], "W m**-2", "Mean surface downward short-wave radiation flux")]
            write_var(p, y, m, lat, lon, td, var, f[var], u, ln, cm, extra)
        n += 1
        print(f"{y}-{m:02d} converted ({len(td)} steps)", flush=True)
    print(f"converted {n} months", flush=True)


# ---------------------------------------------------------------- domain
def cmd_domain(a):
    import netCDF4 as nc
    lat = np.arange(AREA[2], AREA[0] + 1e-9, 0.25)
    lon = np.arange(AREA[1], AREA[3] + 1e-9, 0.25) % 360.0
    nj, ni = len(lat), len(lon)
    LON, LAT = np.meshgrid(lon, lat)
    h = 0.125
    xv = np.stack([LON - h, LON + h, LON + h, LON - h], -1)
    yv = np.stack([LAT - h, LAT - h, LAT + h, LAT + h], -1)
    area = np.deg2rad(0.25) * (np.sin(np.deg2rad(LAT + h)) - np.sin(np.deg2rad(LAT - h)))
    # mask/frac copied from the stock ELMERA5 stream domain for fidelity. DATM's
    # default mapmask=nomask ignores it, so coastal cells also use ocean points.
    src = GLOBAL_DOMAIN if GLOBAL_DOMAIN.exists() else GLOBAL_DOMAIN_URL + "#mode=bytes"
    with nc.Dataset(src) as g:
        yc, xc = g["yc"][:, 0], g["xc"][0, :]
        j = np.where((yc > AREA[2] - 1e-6) & (yc < AREA[0] + 1e-6))[0]
        i = np.where((xc > lon[0] - 1e-6) & (xc < lon[-1] + 1e-6))[0]
        sl = (slice(j[0], j[-1] + 1), slice(i[0], i[-1] + 1))
        if not (np.allclose(g["yc"][sl], LAT) and np.allclose(g["xc"][sl], LON)):
            raise RuntimeError("subset grid does not match the global ERA5 domain")
        mask, frac = np.asarray(g["mask"][sl]), np.asarray(g["frac"][sl])
    DOMAIN_DIR.mkdir(parents=True, exist_ok=True)
    p = DOMAIN_DIR / DOMAIN_NAME
    with nc.Dataset(p, "w", format="NETCDF3_64BIT_OFFSET") as d:
        d.createDimension("n", nj * ni); d.createDimension("ni", ni)
        d.createDimension("nj", nj); d.createDimension("nv", 4)
        for n, arr, u, ln in (("xc", LON, "degrees_east", "longitude of grid cell center"),
                              ("yc", LAT, "degrees_north", "latitude of grid cell center")):
            v = d.createVariable(n, "f8", ("nj", "ni")); v.long_name, v.units = ln, u; v[:] = arr
        for n, arr, u, ln in (("xv", xv, "degrees_east", "longitude of grid cell verticies"),
                              ("yv", yv, "degrees_north", "latitude of grid cell verticies")):
            v = d.createVariable(n, "f8", ("nj", "ni", "nv")); v.long_name, v.units = ln, u; v[:] = arr
        v = d.createVariable("mask", "i4", ("nj", "ni")); v.long_name = "domain mask"; v[:] = mask
        v = d.createVariable("area", "f8", ("nj", "ni"))
        v.long_name, v.units = "area of grid cell in radians squared", "radian2"; v[:] = area
        v = d.createVariable("frac", "f8", ("nj", "ni"))
        v.long_name = "fraction of grid cell that is active"; v[:] = frac
        d.title = f"ERA5 0.25 deg Texas box stream domain (subset of {GLOBAL_DOMAIN.name})"
    print(p, nj, ni, "active cells:", int(mask.sum()))


# ---------------------------------------------------------------- streams
STREAM_TMPL = """<?xml version="1.0"?>
<file id="stream" version="1.0">
<dataSource>
   GENERIC
</dataSource>
<domainInfo>
  <variableNames>
     time    time
        xc      lon
        yc      lat
        area    area
        mask    mask
  </variableNames>
  <filePath>
     @DIN@/share/domains/domain.clm
  </filePath>
  <fileNames>
     {domain}
  </fileNames>
</domainInfo>
<fieldInfo>
   <variableNames>
     {var}    {datm}
   </variableNames>
   <filePath>
     @DIN@/atm/datm7/{forc}/{sub}
   </filePath>
   <fileNames>
{files}
   </fileNames>
   <offset>
      {offset}
   </offset>
</fieldInfo>
</file>
"""
# stock ELMERA5 offsets (namelist_definition_datm.xml)
OFFSET = {"msdrswrf": -3600, "msdfswrf": -3600, "mcpr": -60, "mlspr": -60, "msdwlwrf": -60}


def cmd_streams(a):
    d = FORK / "forcing/era5"
    d.mkdir(parents=True, exist_ok=True)
    for sub, var, *_ in OUT:
        files = "\n".join(f"    {out_path(sub, var, y, m).name}" for y, m in months(a.y0, a.y1))
        txt = STREAM_TMPL.format(domain=DOMAIN_NAME, var=var, datm=DATM_NAME[var], forc=FORC_DIR,
                                 sub=sub, files=files, offset=OFFSET.get(var, 0))
        (d / f"user_datm.streams.txt.ELMERA5.{var}").write_text(txt)
    print(f"wrote 9 stream templates to {d}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    for n in ("fetch", "convert", "streams"):
        q = s.add_parser(n); q.add_argument("y0", type=int); q.add_argument("y1", type=int)
        if n == "fetch":
            q.add_argument("--source", choices=["ncar", "cds"], default="ncar")
            q.add_argument("--workers", type=int, default=None,
                           help="parallel months (default 6 for ncar, 1 for cds: CDS "
                                "rejects concurrent queued requests per dataset)")
    s.add_parser("domain")
    a = p.parse_args()
    if a.cmd == "fetch" and a.workers is None:
        a.workers = 6 if a.source == "ncar" else 1
    return {"fetch": cmd_fetch, "convert": cmd_convert, "domain": cmd_domain,
            "streams": cmd_streams}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
