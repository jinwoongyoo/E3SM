#!/usr/bin/env python
"""Spin-up equilibrium check for the Phase 1 spin-up case.

Reads the monthly ELM h0 files of the spin-up run (NLDAS-2 2010-2014 looped,
5-year forcing cycle) and evaluates drift over the last 5 loop years:

  drift_cycle  = (mean over the last 5-yr cycle - mean over the previous
                  5-yr cycle) / 5 yr          (same forcing in both cycles, so
                                              forcing variability cancels)
  drift_jan1   = (state at end of last cycle - state at end of previous
                  cycle) / 5 yr  (Dec monthly mean used as end state)

Criteria (domain mean over land cells, area weighted): |TWS| < 1 mm/yr and
|ZWT| < 5 cm/yr. Also reports the 95th percentile of |cell drift| (worst 5 %).

usage: spinup_drift.py RUNDIR CASENAME OUTJSON [--cycle-years 5]
"""
import argparse
import glob
import json
import os

import numpy as np
import xarray as xr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rundir")
    ap.add_argument("case")
    ap.add_argument("outjson")
    ap.add_argument("--cycle-years", type=int, default=5)
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.rundir, f"{a.case}.elm.h0.*.nc")))
    if not files:
        raise SystemExit(f"no {a.case}.elm.h0.*.nc files in {a.rundir}")
    first = xr.open_dataset(files[0], decode_times=False)
    stack = {v: [] for v in ("TWS", "ZWT")}
    for f in files:
        with xr.open_dataset(f, decode_times=False) as d:
            for v in stack:
                stack[v].append(d[v].values.reshape(-1, *d[v].shape[1:]))
    ds = xr.Dataset({v: (("time", "lat", "lon"), np.concatenate(x)) for v, x in stack.items()})
    for v in ("area", "landfrac", "landmask"):
        ds[v] = (("lat", "lon"), first[v].values)
    nmon = ds.sizes["time"]
    nyear = nmon // 12
    w = (ds.area * ds.landfrac).where(ds.landmask > 0).fillna(0.0)
    land = ds.landmask.values > 0
    cy = a.cycle_years
    if nyear < 2 * cy:
        raise SystemExit(f"need >= {2 * cy} years, have {nyear}")
    ann = {}
    for v, scale in (("TWS", 1.0), ("ZWT", 1.0)):
        x = ds[v].values[: nyear * 12].reshape(nyear, 12, *ds[v].shape[1:]).mean(axis=1) * scale
        ann[v] = x
    res = {"n_years": nyear, "cycle_years": cy, "files": len(files), "variables": {}}
    for v, unit, crit in (("TWS", "mm/yr", 1.0), ("ZWT", "m/yr", 0.05)):
        x = ann[v]
        last = x[nyear - cy: nyear].mean(axis=0)
        prev = x[nyear - 2 * cy: nyear - cy].mean(axis=0)
        cell = (last - prev) / cy
        mon = ds[v].values
        end_last = mon[nyear * 12 - 1]
        end_prev = mon[(nyear - cy) * 12 - 1]
        cell_end = (end_last - end_prev) / cy
        ww = w.values
        dm = float(np.nansum(cell * ww) / np.nansum(ww * np.isfinite(cell)))
        dm_end = float(np.nansum(cell_end * ww) / np.nansum(ww * np.isfinite(cell_end)))
        absd = np.abs(cell[land & np.isfinite(cell)])
        res["variables"][v] = {
            "units": unit,
            "criterion_abs_domain_mean": crit,
            "drift_cycle_mean_domain": dm,
            "drift_end_state_domain": dm_end,
            "p95_abs_cell_drift": float(np.percentile(absd, 95)),
            "max_abs_cell_drift": float(absd.max()),
            "frac_cells_meeting_criterion": float(np.mean(absd < crit)),
            "pass": bool(abs(dm) < crit),
            "domain_mean_annual_series": [float(np.nansum(ann[v][k] * ww) / np.nansum(ww * np.isfinite(ann[v][k])))
                                          for k in range(nyear)],
        }
    res["pass"] = all(r["pass"] for r in res["variables"].values())
    os.makedirs(os.path.dirname(os.path.abspath(a.outjson)), exist_ok=True)
    with open(a.outjson, "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps({k: (v if k != "variables" else {n: {kk: vv for kk, vv in r.items() if kk != "domain_mean_annual_series"}
                                                       for n, r in v.items()}) for k, v in res.items()}, indent=1))


if __name__ == "__main__":
    main()
