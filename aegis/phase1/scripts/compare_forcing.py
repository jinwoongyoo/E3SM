#!/usr/bin/env python
"""Compare two Phase 1 runs that differ only in forcing (default NLDAS-2 vs ERA5).

  forcing_comparison.csv          KGE / NSE / pbias / peak ratio / peak timing per
                                  gauge and scoring period, side by side
  hydrographs_forcing_compare.png USGS vs both runs, 2017-08-01..09-30

usage: compare_forcing.py POST_A POST_B OUTDIR [--labels NLDAS-2,ERA5]
POST_* are the score_usgs.py output dirs (scores.csv, gauge_daily_sim_obs.csv).
"""
import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from make_figures import HARVEY, OI  # noqa: E402
from p1lib import GAUGES  # noqa: E402

METRICS = ["KGE", "NSE", "pbias_pct", "peak_ratio_sim_over_obs", "peak_timing_error_days"]


def table(post_a, post_b, labels, outdir):
    a, b = (pd.read_csv(os.path.join(p, "scores.csv"), dtype={"site": str}) for p in (post_a, post_b))
    key = ["site", "river", "period"]
    m = a[key + METRICS].merge(b[key + METRICS], on=key, suffixes=[f"_{x}" for x in labels])
    m = m[key + [f"{v}_{x}" for v in METRICS for x in labels]]
    out = os.path.join(outdir, "forcing_comparison.csv")
    m.round(3).to_csv(out, index=False)
    return out, m


def hydrographs(post_a, post_b, labels, outdir, d0="2017-08-01", d1="2017-09-30"):
    dfs = [pd.read_csv(os.path.join(p, "gauge_daily_sim_obs.csv"), dtype={"site": str}) for p in (post_a, post_b)]
    styles = [dict(color=OI["blue"], ls="-"), dict(color=OI["vermillion"], ls="--")]
    fig, axs = plt.subplots(len(GAUGES), 1, figsize=(9, 2.1 * len(GAUGES)), sharex=True)
    for ax, site in zip(axs, GAUGES):
        ax.axvspan(pd.Timestamp(HARVEY[0]), pd.Timestamp(HARVEY[1]), color="0.88", lw=0,
                   label="Harvey rainfall (Aug 25 - Sep 1)")
        for i, (df, lab, st) in enumerate(zip(dfs, labels, styles)):
            d = df[(df.site == site) & (df.date >= d0) & (df.date <= d1)]
            t = pd.to_datetime(d.date)
            if i == 0:
                ax.plot(t, d.obs_m3s, color=OI["black"], lw=1.8, label="USGS observed")
            # local-day series (from hourly output) where available, as used for the scores
            sim = d.sim_localday_m3s.fillna(d.sim_m3s) if "sim_localday_m3s" in d else d.sim_m3s
            ax.plot(t, sim, lw=1.4, label=f"E3SM MOSART, {lab}", **st)
        ax.set_title(f"{GAUGES[site]['name']} (USGS {site})", fontsize=9, loc="left")
        ax.set_ylabel("m$^3$ s$^{-1}$", fontsize=8)
        ax.set_ylim(bottom=0)
        ax.grid(alpha=0.3)
    axs[0].legend(fontsize=7.5, loc="upper left", frameon=False)
    axs[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    fig.suptitle(f"Daily discharge, Aug-Sep 2017: {labels[0]} vs {labels[1]} forcing\n"
                 "E3SM ELM-SP + MOSART r05, same spin-up length (30 yr), uncalibrated", fontsize=11)
    fig.tight_layout()
    out = os.path.join(outdir, "hydrographs_forcing_compare.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("post_a")
    ap.add_argument("post_b")
    ap.add_argument("outdir")
    ap.add_argument("--labels", default="NLDAS-2,ERA5")
    a = ap.parse_args()
    labels = a.labels.split(",")
    os.makedirs(a.outdir, exist_ok=True)
    out, m = table(a.post_a, a.post_b, labels, a.outdir)
    with pd.option_context("display.width", 250):
        print(m.round(2).to_string(index=False))
    print(out)
    print(hydrographs(a.post_a, a.post_b, labels, a.outdir))


if __name__ == "__main__":
    main()
