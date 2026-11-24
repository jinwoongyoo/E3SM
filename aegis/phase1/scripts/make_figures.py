#!/usr/bin/env python
"""Phase 1 figures (colour-blind-safe Okabe-Ito / cividis / BrBG palettes).

  hydrographs_2017JunSep.png    MOSART vs USGS daily discharge, 2017-06-01..09-30
  soilwater10cm_harvey.png      ELM SOILWATER_10CM daily mean on 2017-08-24 and
                                2017-08-31 and their difference
  spinup_drift.png              spin-up domain-mean TWS / ZWT by year (+ drift)

usage: make_figures.py RUNDIR CASE POSTDIR FIGDIR [--which hydro,maps,spinup]
POSTDIR holds scores.json, gauge_daily_sim_obs.csv and spinup_drift.json.
"""
import argparse
import glob
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from p1lib import GAUGES, day_strings, open_hist  # noqa: E402

OI = {"black": "#000000", "orange": "#E69F00", "sky": "#56B4E9", "green": "#009E73",
      "yellow": "#F0E442", "blue": "#0072B2", "vermillion": "#D55E00", "purple": "#CC79A7"}
HARVEY = ("2017-08-25", "2017-09-01")
HOUSTON = (29.76, -95.37)
SUBTITLE = "E3SM ELM-SP + MOSART r05, NLDAS-2 forcing, uncalibrated baseline"


def hydrographs(post, figdir, d0="2017-06-01", d1="2017-09-30"):
    sc = json.load(open(os.path.join(post, "scores.json")))
    df = pd.read_csv(os.path.join(post, "gauge_daily_sim_obs.csv"), dtype={"site": str})
    sites = list(GAUGES)
    fig, axs = plt.subplots(len(sites), 1, figsize=(9, 2.3 * len(sites)), sharex=True)
    for ax, site in zip(axs, sites):
        d = df[(df.site == site) & (df.date >= d0) & (df.date <= d1)].copy()
        t = pd.to_datetime(d.date)
        ax.axvspan(pd.Timestamp(HARVEY[0]), pd.Timestamp(HARVEY[1]), color="0.88", lw=0,
                   label="Harvey rainfall (Aug 25 - Sep 1)")
        ax.plot(t, d.obs_m3s, color=OI["black"], lw=1.6, label="USGS observed")
        ax.plot(t, d.sim_m3s, color=OI["vermillion"], lw=1.6, ls="--", label="E3SM MOSART")
        g = sc["gauges"][site]
        m = g["periods"].get("2017-08-15_2017-09-15", {})
        ax.set_title(f"{g['name']} (USGS {site}); cell {g['cell_lat']:.2f}N {abs(g['cell_lon']):.2f}W, "
                     f"model/USGS area {g['area_ratio_model_over_usgs']:.2f}", fontsize=9, loc="left")
        if "KGE" in m:
            ax.text(0.01, 0.80, f"Aug 15-Sep 15: KGE {m['KGE']:.2f}, NSE {m['NSE']:.2f}, "
                    f"peak sim/obs {m['peak_ratio_sim_over_obs']:.2f}, timing {m['peak_timing_error_days']:+d} d",
                    transform=ax.transAxes, fontsize=8)
        ax.set_ylabel("Discharge (m$^3$ s$^{-1}$)", fontsize=8)
        ax.set_ylim(bottom=0)
        ax.grid(alpha=0.3)
    axs[0].legend(fontsize=8, loc="upper left", bbox_to_anchor=(0.0, 0.78), frameon=False)
    axs[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    fig.suptitle(f"Daily discharge, Jun-Sep 2017\n{SUBTITLE}", fontsize=11)
    fig.tight_layout()
    out = os.path.join(figdir, "hydrographs_2017JunSep.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def _map_axes(fig, n):
    try:
        import cartopy
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
        # Natural Earth cache outside the git repo
        cartopy.config["data_dir"] = os.environ.get(
            "CARTOPY_DATA_DIR", "/Volumes/SSD-Data/aegis-data/e3sm-work/phase1/cartopy_data")
        axs = [fig.add_subplot(1, n, k + 1, projection=ccrs.PlateCarree()) for k in range(n)]
        for ax in axs:
            try:
                ax.add_feature(cfeature.STATES.with_scale("50m"), lw=0.4, edgecolor="0.3")
                ax.add_feature(cfeature.COASTLINE.with_scale("50m"), lw=0.6)
            except Exception as e:  # offline: no Natural Earth data
                print("cartopy features unavailable:", e)
        return axs, ccrs.PlateCarree()
    except ImportError:
        return [fig.add_subplot(1, n, k + 1) for k in range(n)], None


def soilwater_maps(rundir, case, figdir, days=("2017-08-24", "2017-08-31")):
    yrs = {d[:4] for d in days}
    files = sorted(f for f in glob.glob(os.path.join(rundir, f"{case}.elm.h1.*.nc"))
                   if any(f".h1.{y}-" in f for y in yrs))
    ds = open_hist(files, ["SOILWATER_10CM"])
    ds_days = day_strings(ds.time.values)
    x = [ds.SOILWATER_10CM.values[ds_days.index(d)] for d in days]
    land = ds.landmask.values > 0
    x = [np.where(land, v, np.nan) for v in x]
    diff = x[1] - x[0]
    lat, lon = ds.lat.values, ds.lon.values
    le = np.r_[lon - 0.25, lon[-1] + 0.25]
    ae = np.r_[lat - 0.25, lat[-1] + 0.25]
    fig = plt.figure(figsize=(15, 4.6))
    axs, tr = _map_axes(fig, 3)
    kw = {} if tr is None else {"transform": tr}
    vmax = np.nanpercentile(np.r_[x[0].ravel(), x[1].ravel()], 99)
    for ax, v, d in zip(axs[:2], x, days):
        pm = ax.pcolormesh(le, ae, v, cmap="cividis", vmin=0, vmax=vmax, **kw)
        ax.set_title(f"SOILWATER_10CM, daily mean {d}", fontsize=10)
        fig.colorbar(pm, ax=ax, shrink=0.8, label="kg m$^{-2}$ (= mm water, top 10 cm)")
    lim = np.nanpercentile(np.abs(diff), 99)
    pm = axs[2].pcolormesh(le, ae, diff, cmap="BrBG", vmin=-lim, vmax=lim, **kw)
    axs[2].set_title(f"Difference {days[1]} minus {days[0]}", fontsize=10)
    fig.colorbar(pm, ax=axs[2], shrink=0.8, label="kg m$^{-2}$")
    for ax in axs:
        ax.plot(HOUSTON[1], HOUSTON[0], marker="*", color=OI["vermillion"], ms=11, mec="k", **kw)
        for g in GAUGES.values():
            ax.plot(g["lon"], g["lat"], marker="^", color=OI["yellow"], ms=6, mec="k", **kw)
        if tr is not None:
            ax.set_extent([lon[0] - 0.25, lon[-1] + 0.25, lat[0] - 0.25, lat[-1] + 0.25], crs=tr)
            gl = ax.gridlines(draw_labels=True, lw=0.2, color="0.5",
                              xlocs=np.arange(-106, -92, 4), ylocs=np.arange(26, 38, 2))
            gl.top_labels = gl.right_labels = False
    fig.suptitle(f"Near-surface soil water before/after Hurricane Harvey (star: Houston; triangles: USGS gauges)\n"
                 f"{SUBTITLE}", fontsize=11)
    out = os.path.join(figdir, "soilwater10cm_harvey.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def spinup_plot(post, figdir):
    r = json.load(open(os.path.join(post, "spinup_drift.json")))
    cy = r["cycle_years"]
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.2))
    for ax, (v, lab, scale, unit, crit_unit) in zip(axs, (
            ("TWS", "Terrestrial water storage, TWS", 1.0, "mm", "mm/yr"),
            ("ZWT", "Water table depth, ZWT", 1.0, "m", "cm/yr"))):
        info = r["variables"][v]
        y = np.array(info["domain_mean_annual_series"]) * scale
        yrs = np.arange(1, y.size + 1)
        ax.plot(yrs, y, "o-", color=OI["blue"], ms=4)
        for b in range(cy, y.size, cy):
            ax.axvline(b + 0.5, color="0.7", lw=0.8, ls=":")
        ax.set_xlabel("Spin-up year (NLDAS-2 2010-2014 looped)")
        ax.set_ylabel(f"Domain-mean annual {v} ({unit})")
        if v == "ZWT":
            ax.invert_yaxis()
        k = 100.0 if v == "ZWT" else 1.0
        crit = info["criterion_abs_domain_mean"] * k
        txt = (f"last-cycle drift {info['drift_cycle_mean_domain'] * k:+.3f} {crit_unit} "
               f"(criterion |.| < {crit:g}) {'PASS' if info['pass'] else 'FAIL'}\n"
               f"95th pct |cell drift| {info['p95_abs_cell_drift'] * k:.3f} {crit_unit}")
        ax.text(0.98, 0.04, txt, transform=ax.transAxes, fontsize=8, ha="right", va="bottom",
                bbox=dict(fc="white", ec="0.7"))
        if y.size > 20:
            ax.axvline(20.5, color=OI["vermillion"], lw=1.0, ls="--")
            ax.text(20.7, 0.5, "20-yr check failed:\n+10-yr extension", rotation=90, fontsize=7,
                    color=OI["vermillion"], va="center", transform=ax.get_xaxis_transform())
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        ax.set_title(lab, fontsize=10)
        ax.grid(alpha=0.3)
    fig.suptitle(f"Spin-up equilibrium check ({r['n_years']} years, cold start)\n{SUBTITLE}", fontsize=11)
    fig.tight_layout()
    out = os.path.join(figdir, "spinup_drift.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rundir")
    ap.add_argument("case")
    ap.add_argument("postdir")
    ap.add_argument("figdir")
    ap.add_argument("--which", default="hydro,maps,spinup")
    ap.add_argument("--map-days", default="2017-08-24,2017-08-31")
    ap.add_argument("--hydro-range", default="2017-06-01,2017-09-30")
    a = ap.parse_args()
    os.makedirs(a.figdir, exist_ok=True)
    w = a.which.split(",")
    if "hydro" in w:
        print(hydrographs(a.postdir, a.figdir, *a.hydro_range.split(",")))
    if "maps" in w:
        print(soilwater_maps(a.rundir, a.case, a.figdir, tuple(a.map_days.split(","))))
    if "spinup" in w:
        print(spinup_plot(a.postdir, a.figdir))


if __name__ == "__main__":
    main()
