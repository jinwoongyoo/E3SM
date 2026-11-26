#!/usr/bin/env python
"""Score MOSART daily discharge against USGS daily mean discharge.

Each gauge is matched to the MOSART cell (Texas subset network) whose upstream
area (areaTotal2) best matches the USGS drainage area, within +-1 cell and
inside the same river basin (p1lib.match_gauge). The model series is
RIVER_DISCHARGE_OVER_LAND_LIQ (m3/s). Model calendar is noleap, so Feb 29
observations are dropped. (The CTSM NLDAS-2 files are themselves noleap: Feb 29
is omitted from the forcing, so model dates are real calendar dates and peak
timing errors are plain calendar-date differences.)

Time basis. Model time is UTC (NLDAS-2 is in UTC, stream offset 0), so the daily
MOSART tape (h1) holds UTC-day means. USGS daily values are local-day means at
the site (Texas: America/Chicago, CDT = UTC-5 in Aug-Sep). Hence:
  * full period (2016-01..2017-09): h1 UTC-day means vs USGS local days; a
    residual offset of 5 h (CDT) / 6 h (CST) remains.
  * Harvey window (Aug 15 - Sep 15 2017): model daily means are rebuilt from the
    hourly MOSART tape (h2) as America/Chicago local days, the same basis as
    USGS. Only local days with all their hours on h2 are used; h2 ends at
    2017-09-15 00Z, so the last complete local day is Sep 13.

Metrics per gauge and period (days where both obs and model exist):
  KGE (Gupta et al. 2009) with r, alpha = sd_sim/sd_obs, beta = mean_sim/mean_obs;
  NSE; bias = mean_sim - mean_obs (m3/s); pbias = 100*(sum sim - sum obs)/sum obs;
  peak magnitude and date for obs and sim, and the peak timing error
  (sim - obs, days). Ties for the peak take the first (earliest) day; tied
  days are listed in peak_obs_tie_dates / peak_sim_tie_dates.

usage: score_usgs.py RUNDIR CASE MOSART_FILE OBS_CSV OUTDIR [--period START:END[:local] ...]
                     [--local-tz America/Chicago]
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

from p1lib import GAUGES, day_strings, forcing_label, match_gauge, open_hist, terminal_outlets

# name: (start, end, time basis of the model daily means)
PERIODS = {
    "2016-01-01_2017-09-30": ("2016-01-01", "2017-09-30", "utc"),
    "2017-08-15_2017-09-15": ("2017-08-15", "2017-09-15", "local"),
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
    io, isim = int(np.argmax(o)), int(np.argmax(s))   # first occurrence on ties
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
        "peak_obs_tie_dates": [str(d) for d in dates[o == o[io]]],
        "peak_sim_tie_dates": [str(d) for d in dates[s == s[isim]]],
    }


def local_daily_from_hourly(q, tz):
    """Hourly (UTC, noleap cftime, hh:30 labels) -> local-day means.

    Returns a DataFrame (index YYYY-MM-DD local dates, columns = flat cells)
    holding only local days whose every hour is on the tape."""
    t = pd.DatetimeIndex([pd.Timestamp(x.year, x.month, x.day, x.hour, x.minute) for x in q.time.values],
                         tz="UTC").tz_convert(tz)
    v = q.values.reshape(q.shape[0], -1).astype(float)
    df = pd.DataFrame(v, index=t)
    day = t.normalize()
    g = df.groupby(day)
    mean, n = g.mean(), g.size()
    hours = pd.Series([((d + pd.Timedelta(days=1)).normalize() - d).total_seconds() / 3600 for d in mean.index],
                      index=mean.index)   # 23/25 on DST change days
    mean = mean[n.values == hours.values]
    mean.index = [d.strftime("%Y-%m-%d") for d in mean.index]
    return mean


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rundir")
    ap.add_argument("case")
    ap.add_argument("mosart_file")
    ap.add_argument("obs_csv")
    ap.add_argument("outdir")
    ap.add_argument("--period", action="append",
                    help="START:END[:utc|local] (YYYY-MM-DD); default: the two Phase 1 periods")
    ap.add_argument("--local-tz", default="America/Chicago",
                    help="time zone of the USGS daily values (default America/Chicago)")
    a = ap.parse_args()
    periods = PERIODS
    if a.period:
        periods = {}
        for p in a.period:
            f = p.split(":")
            periods[f"{f[0]}_{f[1]}"] = (f[0], f[1], f[2] if len(f) > 2 else "utc")
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
    qloc = None
    if any(p[2] == "local" for p in periods.values()):
        hfiles = sorted(glob.glob(os.path.join(a.rundir, f"{a.case}.mosart.h2.*.nc")))
        qh = open_hist(hfiles, ["RIVER_DISCHARGE_OVER_LAND_LIQ"]).RIVER_DISCHARGE_OVER_LAND_LIQ
        qloc = local_daily_from_hourly(qh, a.local_tz)

    obs = pd.read_csv(a.obs_csv, dtype={"site": str})
    rows, series, gauges = [], {}, {}
    for site, g in GAUGES.items():
        j, i, amod = match_gauge(lat2d, lon2d, a2, g["lat"], g["lon"], g["area_km2"], outlet2d=outl)
        sim = pd.Series(q.values[:, j, i].astype(float), index=days)
        sim_loc = (pd.Series(qloc[j * nlon + i].values, index=qloc.index) if qloc is not None
                   else pd.Series(dtype=float))
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
        series[site] = pd.DataFrame({"obs_m3s": o, "sim_m3s": sim, "sim_localday_m3s": sim_loc})
        for pname, (d0, d1, basis) in periods.items():
            src = sim_loc if basis == "local" else sim
            idx = [d for d in src.index if d0 <= d <= d1]
            s_ = src.reindex(idx).values
            o_ = o.reindex(idx).values.astype(float)
            mt = metrics(s_, o_, idx)
            mt["model_time_basis"] = (f"{a.local_tz} local days (from hourly h2)" if basis == "local"
                                      else "UTC days (daily h1)")
            if idx:
                mt["first_day"], mt["last_day"] = idx[0], idx[-1]
            gauges[site]["periods"][pname] = mt
            rows.append({"site": site, "river": g["river"], "period": pname,
                         "area_ratio": gauges[site]["area_ratio_model_over_usgs"], **mt})

    res = {
        "case": a.case, "model_variable": "RIVER_DISCHARGE_OVER_LAND_LIQ (MOSART daily, m3/s)",
        "obs": "USGS NWIS daily mean discharge (00060, stat 00003), converted to m3/s",
        "calendar_note": f"model noleap; Feb 29 obs dropped ({forcing_label(a.case)} forcing also omits Feb 29)",
        "time_basis_note": (f"USGS daily values are {a.local_tz} local days. Model daily means are UTC days "
                            "(h1) except for periods marked local, which use hourly h2 averaged over local "
                            "days (complete days only). sim_m3s in gauge_daily_sim_obs.csv is UTC-day; "
                            "sim_localday_m3s is the local-day series where hourly output exists."),
        "peak_tie_rule": "first (earliest) day of a tie",
        "caveat": (f"Uncalibrated ELM SP + MOSART at 0.5 deg forced by {forcing_label(a.case)}; reservoirs/withdrawals "
                   "not represented; small San Jacinto tributaries are below the grid scale."),
        "gauges": gauges,
    }
    with open(os.path.join(a.outdir, "scores.json"), "w") as f:
        json.dump(res, f, indent=1)
    keys = ["site", "river", "period", "model_time_basis", "first_day", "last_day", "area_ratio", "n_days",
            "KGE", "NSE", "r", "alpha", "beta",
            "mean_obs_m3s", "mean_sim_m3s", "bias_m3s", "pbias_pct", "peak_obs_m3s", "peak_obs_date",
            "peak_sim_m3s", "peak_sim_date", "peak_ratio_sim_over_obs", "peak_timing_error_days"]
    with open(os.path.join(a.outdir, "scores.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()
                        if not k.endswith("_tie_dates")})
    long = pd.concat({k: v.sort_index() for k, v in series.items()}, names=["site", "date"]).reset_index()
    long.to_csv(os.path.join(a.outdir, "gauge_daily_sim_obs.csv"), index=False, float_format="%.4f")
    for r in rows:
        print(f"{r['site']} {r['river']:26s} {r['period']}  n={r['n_days']:4d}  "
              f"KGE={r.get('KGE', np.nan):6.2f}  NSE={r.get('NSE', np.nan):7.2f}  "
              f"pbias={r.get('pbias_pct', np.nan):7.1f}%  peak {r.get('peak_obs_date')} obs / "
              f"{r.get('peak_sim_date')} sim ({r.get('peak_timing_error_days', 0):+d} d)  "
              f"area_ratio={r['area_ratio']}")


if __name__ == "__main__":
    main()
