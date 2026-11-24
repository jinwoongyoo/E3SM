#!/usr/bin/env python
"""Download USGS daily mean discharge (parameter 00060, stat 00003) and site
metadata for the Phase 1 scoring gauges from the USGS NWIS web services.

usage: fetch_usgs.py OUTDIR [--start 2010-01-01] [--end 2017-09-30]
Writes OUTDIR/usgs_daily_q.csv (date, site, q_m3s, qual) and OUTDIR/usgs_sites.json.
"""
import argparse
import io
import json
import os
import time

import pandas as pd
import requests

from p1lib import GAUGES
CFS_TO_M3S = 0.028316846592
SQMI_TO_KM2 = 2.589988110336
BASE = "https://waterservices.usgs.gov/nwis"


def get(url, params, tries=5):
    for k in range(tries):
        try:
            r = requests.get(url, params=params, timeout=120)
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if k == tries - 1:
                raise
            time.sleep(10 * (k + 1))


def rdb(text):
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    return pd.read_csv(io.StringIO("\n".join([lines[0]] + lines[2:])), sep="\t", dtype=str)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default="2017-09-30")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    sites = rdb(get(f"{BASE}/site/", {"format": "rdb", "sites": ",".join(GAUGES), "siteOutput": "expanded"}))
    meta = {}
    for _, r in sites.iterrows():
        meta[r.site_no] = {
            "name": r.station_nm,
            "lat": float(r.dec_lat_va),
            "lon": float(r.dec_long_va),
            "drain_area_km2": float(r.drain_area_va) * SQMI_TO_KM2,
            "contrib_drain_area_km2": (float(r.contrib_drain_area_va) * SQMI_TO_KM2
                                       if isinstance(r.contrib_drain_area_va, str) and r.contrib_drain_area_va.strip() else None),
        }
    frames = []
    for s in GAUGES:
        t = rdb(get(f"{BASE}/dv/", {"format": "rdb", "sites": s, "parameterCd": "00060", "statCd": "00003",
                                    "startDT": a.start, "endDT": a.end, "siteStatus": "all"}))
        vcol = [c for c in t.columns if c.endswith("_00060_00003")][0]
        df = pd.DataFrame({
            "date": pd.to_datetime(t["datetime"]),
            "site": s,
            "q_m3s": pd.to_numeric(t[vcol], errors="coerce") * CFS_TO_M3S,
            "qual": t[vcol + "_cd"],
        })
        meta[s]["n_days"] = int(df.q_m3s.notna().sum())
        frames.append(df)
    out = pd.concat(frames)
    out.to_csv(os.path.join(a.outdir, "usgs_daily_q.csv"), index=False)
    meta["_source"] = (f"USGS NWIS waterservices dv (00060/00003), {a.start}..{a.end}, retrieved "
                       f"{pd.Timestamp.now(tz='UTC'):%Y-%m-%dT%H:%MZ}; cfs->m3/s x{CFS_TO_M3S}")
    with open(os.path.join(a.outdir, "usgs_sites.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
