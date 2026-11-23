#!/usr/bin/env python
"""Score MOSART daily discharge against USGS daily mean discharge.

Each gauge is matched to the MOSART cell (Texas subset network) whose upstream
area (areaTotal2) best matches the USGS drainage area, within +-1 cell and
inside the same river basin (p1lib.match_gauge). The model series is
RIVER_DISCHARGE_OVER_LAND_LIQ (m3/s) from the daily MOSART tape (h1). Model
calendar is noleap, so Feb 29 observations are dropped.

Metrics per gauge and period (days where both obs and model exist):
  KGE (Gupta et al. 2009) with r, alpha = sd_sim/sd_obs, beta = mean_sim/mean_obs;
  NSE; bias = mean_sim - mean_obs (m3/s); pbias = 100*(sum sim - sum obs)/sum obs;
  peak magnitude and date for obs and sim, and the peak timing error
  (sim - obs, days).

usage: score_usgs.py RUNDIR CASE MOSART_FILE OBS_CSV OUTDIR [--period START:END ...]
"""
import argparse
import csv
import datetime as dt
import glob
import json
import os

import numpy as np
import pandas as pd
import xarray as xr

from p1lib import GAUGES, day_strings, match_gauge, open_hist, terminal_outlets

PERIODS = {
    "2016-01-01_2017-09-30": ("2016-01-01", "2017-09-30"),
    "2017-08-15_2017-09-15": ("2017-08-15", "2017-09-15"),
}


def metrics(s, o, dates):
    ok = np.isfinite(s) & np.isfinite(o)
    s, o, dates = s[ok], o[ok], np.asarray(dates)[ok]
    if s.size < 3:
        return {"n_days": int(s.size)}
    r = float(np.corrcoef(s, o)[0, 1])
    alpha = float(np.std(s) / np.std(o))
    beta = float(np.mean(s) / np.mean(o))
    kge = 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    nse = 1.0 - np.sum((s - o) ** 2) / np.sum((o - np.mean(o)) ** 2)
    io, isim = int(np.argmax(o)), int(np.argmax(s))
    d_o = dt.date.fromisoformat(dates[io])
    d_s = dt.date.fromisoformat(dates[isim])
    return {
        "n_days": int(s.size),
        "KGE": float(kge), "NSE": float(nse), "r": r, "alpha": alpha, "beta": beta,
        "mean_obs_m3s": float(np.mean(o)), "mean_sim_m3s": float(np.mean(s)),
        "bias_m3s": float(np.mean(s) - np.mean(o)),
        "pbias_pct": float(100.0 * (np.sum(s) - np.sum(o)) / np.sum(o)),
        "peak_obs_m3s": float(o[io]), "peak_obs_date": dates[io],
        "peak_sim_m3s": float(s[isim]), "peak_sim_date": dates[isim],
        "peak_ratio_sim_over_obs": float(s[isim] / o[io]),
        "peak_timing_error_days": (d_s - d_o).days,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rundir")
    ap.add_argument("case")
    ap.add_argument("mosart_file")
    ap.add_argument("obs_csv")
    ap.add_argument("outdir")
    ap.add_argument("--period", action="append", help="START:END (YYYY-MM-DD); default: the two Phase 1 periods")
    a = ap.parse_args()
    periods = ({f"{p.split(':')[0]}_{p.split(':')[1]}": tuple(p.split(":")) for p in a.period}
               if a.period else PERIODS)
    os.makedirs(a.outdir, exist_ok=True)

    net = xr.open_dataset(a.mosart_file)
    nlat, nlon = net.sizes["lat"], net.sizes["lon"]
    lat2d = np.repeat(net.lat.values[:, None], nlon, 1)
    lon2d = np.repeat(net.lon.values[None, :], nlat, 0)
    a2 = net.areaTotal2.values / 1e6
    ids = net.ID.values.astype(np.int64).ravel()
    dn = net.dnID.values.astype(np.int64).ravel()
    id2k = {i: k for k, i in enumerate(ids)}
    dn0 = np.array([id2k.get(d, -1) for d in dn])
    outl = terminal_outlets(dn0).reshape(nlat, nlon)

    files = sorted(glob.glob(os.path.join(a.rundir, f"{a.case}.mosart.h1.*.nc")))
    q = open_hist(files, ["RIVER_DISCHARGE_OVER_LAND_LIQ"]).RIVER_DISCHARGE_OVER_LAND_LIQ
    days = day_strings(q.time.values)
    assert np.allclose(q.lat.values, net.lat.values) and np.allclose(q.lon.values, net.lon.values)

    obs = pd.read_csv(a.obs_csv, dtype={"site": str})
    rows, series, gauges = [], {}, {}
    for site, g in GAUGES.items():
        j, i, amod = match_gauge(lat2d, lon2d, a2, g["lat"], g["lon"], g["area_km2"], outlet2d=outl)
        sim = pd.Series(q.values[:, j, i].astype(float), index=days)
        o = obs[obs.site == site].set_index("date").q_m3s
        o = o[~o.index.str.endswith("-02-29")]
        gauges[site] = {
            "name": g["name"], "river": g["river"], "gauge_lat": g["lat"], "gauge_lon": g["lon"],
            "usgs_drain_area_km2": g["area_km2"], "usgs_contrib_area_km2": g["contrib_km2"],
            "cell_lat": float(net.lat.values[j]), "cell_lon": float(net.lon.values[i]),
            "cell_areaTotal2_km2": round(float(amod), 1),
            "area_ratio_model_over_usgs": round(float(amod / g["area_km2"]), 3),
            "periods": {},
        }
        series[site] = pd.DataFrame({"obs_m3s": o, "sim_m3s": sim})
        for pname, (d0, d1) in periods.items():
            idx = [d for d in sim.index if d0 <= d <= d1]
            s_ = sim.reindex(idx).values
            o_ = o.reindex(idx).values.astype(float)
            mt = metrics(s_, o_, idx)
            gauges[site]["periods"][pname] = mt
            rows.append({"site": site, "river": g["river"], "period": pname,
                         "area_ratio": gauges[site]["area_ratio_model_over_usgs"], **mt})

    res = {
        "case": a.case, "model_variable": "RIVER_DISCHARGE_OVER_LAND_LIQ (MOSART daily, m3/s)",
        "obs": "USGS NWIS daily mean discharge (00060, stat 00003), converted to m3/s",
        "calendar_note": "model noleap; Feb 29 obs dropped",
        "caveat": ("Uncalibrated ELM SP + MOSART at 0.5 deg forced by NLDAS-2; reservoirs/withdrawals "
                   "not represented; small San Jacinto tributaries are below the grid scale."),
        "gauges": gauges,
    }
    with open(os.path.join(a.outdir, "scores.json"), "w") as f:
        json.dump(res, f, indent=1)
    keys = ["site", "river", "period", "area_ratio", "n_days", "KGE", "NSE", "r", "alpha", "beta",
            "mean_obs_m3s", "mean_sim_m3s", "bias_m3s", "pbias_pct", "peak_obs_m3s", "peak_obs_date",
            "peak_sim_m3s", "peak_sim_date", "peak_ratio_sim_over_obs", "peak_timing_error_days"]
    with open(os.path.join(a.outdir, "scores.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    long = pd.concat({k: v for k, v in series.items()}, names=["site", "date"]).reset_index()
    long.to_csv(os.path.join(a.outdir, "gauge_daily_sim_obs.csv"), index=False, float_format="%.4f")
    for r in rows:
        print(f"{r['site']} {r['river']:26s} {r['period']}  n={r['n_days']:4d}  "
              f"KGE={r.get('KGE', np.nan):6.2f}  NSE={r.get('NSE', np.nan):7.2f}  "
              f"pbias={r.get('pbias_pct', np.nan):7.1f}%  area_ratio={r['area_ratio']}")


if __name__ == "__main__":
    main()
