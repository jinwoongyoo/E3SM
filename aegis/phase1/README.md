# Aegis Phase 1 — E3SM land baseline over Texas (Hurricane Harvey)

A regional, land-only E3SM run (ELM satellite phenology + MOSART river routing,
forced by NLDAS-2 hourly data through DATM) over a Texas box at 0.5°.
It is the **uncorrected "original E3SM" baseline** that later Aegis
AI-corrected land states will be compared against.

> **Read this first.** This is a baseline, **not a validated product**:
> ELM in SP mode (prescribed MODIS phenology, no crop/BGC), forced by NLDAS-2,
> **uncalibrated** (default ELM/MOSART parameters), on a 0.5° grid. The 0.5°
> MOSART network cannot resolve Houston's bayous (Buffalo, Brays, Cypress Creek
> are far smaller than one cell). River inflow from outside the box is lost
> (see "Domain"). Scores below show how the uncalibrated model does; they are
> not a calibration target.

Everything runs on the `aegis-mac` machine described in `aegis/README.md`
(Phase 0). Data live under `/Volumes/SSD-Data/aegis-data/e3sm-work/phase1/`
(`$P1` below); this directory holds only the scripts, so it can reproduce the
work end to end.

## Configuration

| Item | Value |
|---|---|
| Compset (long name; there is no alias) | `2000_DATM%NLDAS2_ELM%SP_SICE_SOCN_MOSART_SGLC_SWAV` |
| Resolution | `ELMMOS_USRDAT`, `ELM_USRDAT_NAME=r05_texas` (lnd = atm = rof grid, idmap lnd↔rof) |
| DATM mode | `CLMNLDAS2`: 3 streams (Solar, Precip, TPQWL) from `atm/datm7/atm_forcing.datm7.NLDAS2.0.125d.v1`, 0.125° hourly, noleap |
| Calendar | `NO_LEAP` (the DATM NLDAS-2 files already have Feb 29 removed) |
| Driver | `moab` (E3SM default; `DRIVER` in `scripts/common.sh`) |
| PEs | 6 MPI tasks, 1 thread (machine cap; shared with a CI runner) |
| Coupling | ATM/LND 48 per day (30 min); ROF 8 per day in the spin-up, 24 per day (hourly) in production so MOSART can write hourly output |
| Surface data | r05 `surfdata_0.5x0.5_simyr2000_c200624.nc` (the IERA5ELM / r05 default, simyr 2000) subset to the box |
| River network | `MOSART_global_half_20180721a.nc` subset to the box |

### Domain (`scripts/make_inputs.py`)

Box 25.5–37°N, 107–93°W → 23 × 28 = 644 r05 cells, of which **592 are land**
under the E3SM v3 land mask `domain.lnd.r05_IcoswISC30E3r5.231121.nc`.
`make_inputs.py` writes three files, each with sha256 recorded in
`$P1/inputs/inputs_manifest.json`:

* `domain.lnd.r05_texas.<tag>.nc`: a 2-D (ni=28, nj=23) subset of the r05 domain.
* `surfdata_r05_texas_simyr2000.<tag>.nc`: the matching `lsmlat/lsmlon` slab of the r05 surfdata.
* `MOSART_r05_texas.<tag>.nc`: the MOSART subset. `ID` is renumbered 1..644
  (row-major) and `dnID` is remapped. A cell whose downstream cell is outside
  the box becomes an outlet (`dnID=-9999`, `fdir=0`): 17 new edge outlets.
  `areaTotal*` keep their global values (full upstream area), and so does
  every other field.

Basin check: each gauge is matched to a MOSART cell (see "Gauge matching").
The diagnostic traces the gauge's whole basin upstream from its terminal outlet:

Model/USGS area is MOSART `areaTotal2` of the matched cell divided by the USGS
**total** drainage area (`drain_area_va`). Against the USGS contributing area
(`contrib_drain_area_va`, which excludes non-contributing playa/closed basins)
the ratio would be 1.28 for Brazos and 1.53 for Colorado; the other three
gauges have contributing = total area.

| Basin (gauge) | Whole basin inside box | Model/USGS area (total) |
|---|---|---|
| Brazos (08114000 Richmond) | yes | 1.006 |
| Trinity (08066500 Romayor) | yes | 0.884 |
| San Jacinto W Fk (08068000) | yes | 1.245 |
| Cypress Ck (08069000) | yes | 3.618 |
| Colorado TX (08162000 Wharton) | yes | 1.113 |

**Inflow lost at the box edge.** 22 box cells receive flow from outside the
box. Most are on the west edge (Rio Grande / Pecos from New Mexico and
Colorado) and the north edge (Canadian, Red, Arkansas tributaries at 36.75°N).
The Rio Grande basin above its mouth has 27 of 203 cells outside the box, about
70,000 km². That inflow is simply absent in this run, so Rio Grande and Red
River flows are not meaningful. The five Harvey gauges lie in basins that are
fully inside the box.

## Reproduce

All CIME commands need the e3sm env first on `PATH`. `scripts/common.sh` sets
it, along with every path, the compset and the forcing hook.

```bash
S=/Volumes/SSD-Data/aegis-data/E3SM/aegis/phase1/scripts
. $S/common.sh                                # sets PATH, P1, WORK, DIN, ...
PY=/Volumes/SSD-Data/aegis-data/conda-envs/e3sm-tools/bin/python   # tools env (env/)

# 0. inputs
# 0a. global static inputs for make_inputs.py / remap_ne30pg2.py. The cases
#     reference only the Texas subsets, so check_input_data never fetches these.
E3SM_IN=https://web.lcrc.anl.gov/public/e3sm/inputdata
for r in share/domains/domain.lnd.r05_IcoswISC30E3r5.231121.nc \
         lnd/clm2/surfdata_map/surfdata_0.5x0.5_simyr2000_c200624.nc \
         rof/mosart/MOSART_global_half_20180721a.nc \
         cpl/gridmaps/ne30pg2/map_r05_to_ne30pg2_traave.20231130.nc; do
  mkdir -p "$DIN/$(dirname $r)"
  curl -fL -C - --retry 5 -o "$DIN/$r" "$E3SM_IN/$r"    # resumable
done
#     expected sizes (bytes): 25,922,096 / 2,376,363,028 / 42,521,304 / 34,925,320
# 0b. NLDAS-2 2010-2017: 288 files, 204.2 GB = 190.2 GiB
bash $S/fetch_nldas2.sh 2010 2017 12          # resumable, size-verified (OSDF, svn fallback)
$PY  $S/fetch_usgs.py $P1/obs                 # USGS daily discharge + site info
(cd $P1 && $PY $S/make_inputs.py inputs --tag c261123)

# 1. spin-up (cold start, NLDAS-2 2010-2014 looped, 20 yr)
bash $S/case_spinup.sh            # create + build
FI_PROVIDER=tcp bash $S/case_spinup.sh submit     # 4 x 5 yr (RESUBMIT=3)
$PY  $S/spinup_drift.py $WORK/scratch/p1tx.nldas2.spinup/run p1tx.nldas2.spinup $P1/post/spinup_drift.json
# if it fails: extend once by 10 yr, then re-check
#   cd $CASE_SPINUP && ./xmlchange CONTINUE_RUN=TRUE,STOP_N=5,RESUBMIT=1 && ./case.submit

# 2. production 2010-01-01 -> 2017-09-30 (hybrid from the spin-up restart;
#    0031-01-01 because the spin-up needed the 10-yr extension)
bash $S/case_production.sh create 0031-01-01
bash $S/case_production.sh segA   # -> 2017-08-15
bash $S/case_production.sh segB   # branch, hourly output -> 2017-09-15
bash $S/case_production.sh segC   # branch -> 2017-10-01
# each segment resets RUN_TYPE/RUN_REFCASE/RUN_REFDATE (and, for segB/segC, the
# rpointer files), so a single segment can be re-run on its own

# 3. post-processing (remap to ne30pg2, USGS scoring, figures)
R=$WORK/scratch/p1tx.nldas2.prod/run; C=p1tx.nldas2.prod
$PY $S/remap_ne30pg2.py $R $C h1 $P1/post/elm_daily_ne30pg2_texas.nc
$PY $S/remap_ne30pg2.py $R $C h2 $P1/post/elm_hourly_ne30pg2_texas.nc
$PY $S/score_usgs.py $R $C $P1/inputs/MOSART_r05_texas.c261123.nc $P1/obs/usgs_daily_q.csv $P1/post
$PY $S/make_figures.py $R $C $P1/post $P1/figures
```

Run the Python scripts from `scripts/` (or set `PYTHONPATH=$S`); they share
`p1lib.py`.

### Tools environment

`env/environment.yml` (conda-forge only) and the explicit lock file
`env/conda-osx-arm64.lock.txt` define the post-processing env at
`/Volumes/SSD-Data/aegis-data/conda-envs/e3sm-tools`:

```bash
~/miniforge3/bin/mamba create -p <prefix> --file env/conda-osx-arm64.lock.txt
```

The E3SM build/run env (`conda-envs/e3sm`) is not modified.

### Swapping the forcing (ERA5 later)

**The ERA5 path is untested end to end.** Only NLDAS-2 has been built and run.

`apply_forcing` in `scripts/common.sh` sets `DATM_MODE` from `FORCING`
(`nldas2` → `CLMNLDAS2`, `era5` → `ELMERA5`) and copies any
`forcing/<FORCING>/user_datm.streams.txt.*` templates into the case, replacing
`@P1@`/`@DIN@`. Stream files alone are not enough to switch forcing:

* `COMPSET` is hard-coded to `2000_DATM%NLDAS2_...` in `scripts/common.sh`
  (line 22) and must be changed to the ERA5 DATM compset.
* `DATM_CLMNCEP_YR_START/END/ALIGN` are set in `case_spinup.sh` and
  `case_production.sh` for NLDAS-2 2010–2014 / 2010–2017 and must match the
  ERA5 years available.
* The DATM calendar handling, time-axis offsets and any domain/mesh for the
  ERA5 grid must be checked; none of this has been exercised.

## Gauge matching

USGS gauges (`scripts/p1lib.py: GAUGES`) are matched to MOSART cells. The
candidates are the cell containing the gauge and its 8 neighbours, limited to
cells that drain to the same terminal outlet. The score is
`|ln(areaTotal2 / USGS drainage area)| + 0.25 × distance in cells`, and the
lowest score wins. The two San Jacinto gauges, W Fork 08068000 (2,145 km²) and
Cypress Creek 08069000 (738 km²), are at or below the area of one 0.5° cell
(~2,670 km²). Both gauges physically lie in cell 30.25°N 95.25°W
(`areaTotal2` 5,341 km², two cells), but both were matched to its western
neighbour 30.25°N 95.75°W, whose `areaTotal2` (2,670 km²) is only its own cell
area: a one-cell headwater with no upstream routing. Both simulated series are
therefore identical and reflect that one cell's local runoff, not routed flow.
Their area ratios (1.25 and 3.62) and scores mainly show this resolution limit.

## Known quirks / deviations

* Spin-up length: the design's 20 years failed the TWS criterion
  (+1.86 mm/yr), so the run was extended by 10 years once, as the design
  allows. Production starts from 0031-01-01.
* MOSART runs without reservoirs (`wrmflag=.false.`, the default). CIME still
  requires and stages the default reservoir parameter file.

* The driver's default is `end_restart=.false.`, so `case_production.sh`
  sets `end_restart = .true.` in `user_nl_cpl`. Without it, segment A writes
  no restart at its end date (2017-08-15) and the branches cannot start.
* `ROF_NCPL=24` in production. With the spin-up's 3-hour MOSART step,
  `rtmhist_nhtfrq=-1` (hourly) is not a multiple of the step and MOSART falls
  back to monthly output.
* The branch segments keep the case name (`RUN_REFCASE == CASE`). The driver
  then sets `brnch_retain_casename=.true.` automatically, so history file
  names continue unbroken.
* In a branch run the coupler (`restart_file` unset in `drv_in`) and DATM
  (`restfilm` unset) read `rpointer.drv` / `rpointer.atm`, which point to the
  newest restart in the run directory. `case_production.sh` therefore rewrites
  all rpointers to the branch date before `segB`/`segC`, and `segA` restores
  the hybrid settings, so segments can be re-run in any order. (The original
  A→B→C sequence did not need this; the fix only matters for re-runs.)
* `create_clone` does not run `case.setup`, so `case_production.sh` runs it.
* NaNs that are expected, not errors:
  * One r05 cell (29.25N, 94.25W; Galveston Bay shore) is ~99% wetland with
    land fraction 0.04. ELM has no soil column there, so `SOILWATER_10CM` and
    `ZWT` are NaN.
  * MOSART writes NaN discharge at ocean/isolated cells (`mask` 2) and at
    outlets (`mask` 3). Every gauge cell is a land cell (`mask` 1).

* `map_r05_to_ne30pg2_traave.20231130.nc` is listed in `config_grids.xml`
  under `cpl/gridmaps/r05/`, but the file on the inputdata server is under
  `cpl/gridmaps/ne30pg2/`. It was fetched from the latter.
* The NLDAS-2 DATM files are not on the E3SM (LCRC) inputdata server.
  `fetch_nldas2.sh` gets them from the CESM inputdata OSDF mirror
  (`osdf-director.osg-htc.org/ncar/gdex/d651077/cesmdata/inputdata`;
  it supports HTTP Range, so partial files resume),
  falling back to the svn server (byte-identical, slow, ignores Range).
  Files go to the same relative path under `DIN_LOC_ROOT`, so CIME's
  `check_input_data` finds them. Only the final response's `Content-Length`
  is used, and only if it is > 1 MB, so an error page can never accept or prune
  a file. The script exits non-zero unless all (Y1−Y0+1)×36 files are present.
* ELM ignores history-namelist changes on `CONTINUE_RUN` (history tapes come
  from the restart). So the hourly window (2017-08-15 → 09-15) and the
  following segment are **branch** runs. As a result, the h0 (monthly) files
  for 2017-08 and 2017-09 are partial; use the daily h1 tape for those months.

## Run log / results

### NLDAS-2 download

288 monthly files (3 streams × 96 months, 2010-01 to 2017-12), 204.2 GB
(decimal, 10⁹ bytes) = 190.2 GiB (2³⁰ bytes), the sum of file sizes in bytes
(re-measured with `stat`; `du` agrees). An earlier draft gave 199.6 GB, which
was the `du -k` KiB count mislabelled as kB. All files were checked against the server `Content-Length`. Over OSDF with
12 parallel connections the rate was 4–8 MB/s in total (about 7.5 h).

### Spin-up (`p1tx.nldas2.spinup`)

The run is a cold start that loops NLDAS-2 2010–2014 (`DATM_CLMNCEP_YR_ALIGN=1`).
Drift compares the mean of the last 5-year forcing cycle with the mean of the
cycle before it, using annual means of the monthly h0 fields, area × landfrac
weighted. The design criteria are |TWS drift| < 1 mm/yr and |ZWT drift| < 5 cm/yr.

| Check | TWS drift (mm/yr) | ZWT drift (cm/yr) | Worst 5% of cells: TWS / ZWT | Result |
|---|---|---|---|---|
| after 20 yr | +1.86 | −0.20 | > 21.3 mm/yr / > 13.6 cm/yr | **fail** (TWS) |
| after 30 yr (+10-yr extension, done once as designed) | −0.72 | +0.79 | > 10.1 mm/yr / > 6.8 cm/yr | **pass** |

Positive ZWT drift means the water table is deepening. 46% of cells meet the
TWS criterion on their own and 90% meet the ZWT criterion, so individual
cells still drift even though the domain mean passes. Figure: `$P1/figures/spinup_drift.png`.
Numbers: `$P1/post/spinup_drift.json` (and `spinup_drift_y20.json` in `$P1/logs/`).

Run times on 6 MPI tasks were 1,601–2,141 s per 5-year segment, 202–270
simulated years per day. The total was 10,612 s (2.95 h) for 30 years.

### Production (`p1tx.nldas2.prod`)

Hybrid from `p1tx.nldas2.spinup` 0031-01-01, real years 2010–2017
(`DATM_CLMNCEP_YR_ALIGN=2010`), `NO_LEAP` calendar.

| Segment | Period | Run time | Throughput (sim yr/day) |
|---|---|---|---|
| A (hybrid) | 2010-01-01 → 2017-08-15 | 2,513 s | 262 |
| B (branch, hourly) | 2017-08-15 → 2017-09-15 | 37 s | 197 |
| C (branch) | 2017-09-15 → 2017-10-01 | 15 s | 254 |

Output in `$WORK/scratch/p1tx.nldas2.prod/run`:

| Tape | Content |
|---|---|
| ELM `h0` | monthly |
| ELM `h1` | daily: 2,828 days, 2010-01-01 → 2017-09-30, no gaps; one file per year plus one per branch |
| ELM `h2` | hourly: 744 h, 2017-08-15 00:00 → 2017-09-15 00:00 |
| MOSART `h1`, `h2` | the same daily and hourly sampling |

Feb 29 does not exist in the model or the forcing; the USGS series drop it
before scoring.


### Post-processing (`$P1/post`, `$P1/figures`)

* `elm_daily_ne30pg2_texas.nc` (2,828 days) and `elm_hourly_ne30pg2_texas.nc`
  (744 h) hold the 13 key ELM fields remapped to ne30pg2 with
  `map_r05_to_ne30pg2_traave.20231130.nc`. Weights are S × landfrac over the
  valid box cells, so the remap conserves the land-weighted mean (checked to
  1e-9). The files cover the 85 ne30pg2 columns that overlap the box:
  * 57 columns lie fully inside the box.
  * 4 columns are all ocean, so they are NaN.
  * `ncol_global` gives each column's index in the global ne30pg2 grid.
  * `box_area_frac` and `land_area_frac` tell users how much of each column
    the Texas run covers.
* `scores.json` / `scores.csv`: MOSART `RIVER_DISCHARGE_OVER_LAND_LIQ`
  vs USGS daily mean discharge (Feb 29 dropped). `gauge_daily_sim_obs.csv`
  holds the paired series (`sim_m3s` = UTC days, `sim_localday_m3s` = local
  days where hourly output exists).

**Time basis.** Model time is UTC (NLDAS-2 is UTC; stream offset 0), so the
daily h1 tape holds UTC-day means. USGS daily values are local-day means
(America/Chicago; CDT = UTC−5 in Aug–Sep). For the Harvey window the model
daily means are therefore rebuilt from the hourly h2 tape as America/Chicago
local days, using only days with all their hours on the tape. h2 ends at
2017-09-15 00Z, so the window scored is **Aug 15 – Sep 13 local (30 days)**.
The full-period scores keep the UTC-day h1 means, with a residual 5–6 h
offset. Using fixed CST (UTC−6) instead of America/Chicago changes no peak
date and the window NSE by ≤ 0.04.

Peak timing is the calendar-date difference sim − obs. The CTSM NLDAS-2
files omit Feb 29, so model dates are real dates, and a difference of model
record indices would undercount by one day across 2016-02-29; no scored peak
pair straddles that date, so the choice does not change any number. On ties the first
(earliest) day is the peak; tied days are listed in `scores.json`
(`peak_*_tie_dates`). The Brazos observed peak is a tie (3,398 m³/s on both
Aug 31 and Sep 1), so its timing is −3 d against Aug 31 (−4 d against Sep 1).

| USGS gauge | Model/USGS total drainage area | KGE 2016-01→2017-09 (UTC days) | NSE | Bias | KGE Aug 15–Sep 13 2017 (local days) | NSE | Bias | Peak sim/obs | Peak timing (sim − obs) |
|---|---|---|---|---|---|---|---|---|---|
| 08114000 Brazos @ Richmond | 1.01 | 0.67 | 0.70 | −1% | 0.69 | 0.75 | +28% | 1.03 (3,487 vs 3,398 m³/s) | −3 d |
| 08066500 Trinity @ Romayor | 0.88 | 0.60 | 0.23 | −2% | −0.69 | −1.95 | +135% | 2.50 (6,568 vs 2,628) | +2 d |
| 08068000 W Fk San Jacinto nr Conroe | 1.25 | 0.28 | 0.32 | −13% | 0.26 | 0.29 | −1% | 0.30 (748 vs 2,517) | −1 d |
| 08069000 Cypress Ck nr Westfield | 3.62 | 0.26 | 0.10 | +62% | −0.07 | −0.05 | +100% | 0.89 (748 vs 841) | 0 d |
| 08162000 Colorado @ Wharton | 1.11 | 0.29 | 0.38 | −1% | 0.25 | 0.46 | −29% | 0.37 (927 vs 2,478) | −1 d |

The peak columns are for the Harvey window. An earlier version of this table
scored the window on UTC days (to Sep 15); that shifted the San Jacinto peak
timing to +3 d / +4 d and the Brazos to −2 d.

How to read these scores:

* The Brazos is the only gauge where the uncalibrated model is
  reasonable during Harvey.
* The Trinity peak at Romayor is 2.5 times too high. This is consistent with
  the run having no reservoir regulation: MOSART `wrmflag=.false.`, while Lake
  Livingston sits just upstream of the gauge.
* The Colorado peak is 2.7 times too low. This was not diagnosed; candidate
  causes are the 0.5° smoothing of the intense rain over the lower basin and
  the default runoff parameters.
* The two San Jacinto gauges share one 0.5° cell, so their simulated series
  are identical. They mainly measure the resolution limit (see "Gauge
  matching"). Their peak timing is not robust: the simulated series has two
  almost equal peaks, 748 m³/s on Aug 28 and 742 m³/s on Sep 1 (local days),
  and on UTC days the Sep 1 peak is the larger one.
* Recession and baseflow are too high at most gauges, both in the weeks after
  the peak and in the dry summer.

Figures (`$P1/figures`, Okabe–Ito / cividis / BrBG colour-blind-safe palettes):

* `hydrographs_2017JunSep.png`: daily discharge, observed vs model, Jun–Sep
  2017, with the Harvey rain window shaded. The model is drawn on UTC days
  (dashed) and, for Aug 15–Sep 13, on local days (solid; the basis of the
  scores shown). Panel notes flag the Trinity (no reservoirs) and the shared
  San Jacinto headwater cell.
* `soilwater10cm_harvey.png`: `SOILWATER_10CM` on 2017-08-24 and on
  2017-08-31, and their difference.
* `spinup_drift.png`: domain-mean annual TWS and ZWT over the 30-year
  spin-up.

sha256 of the products (they are not in git):

```
bd03611ba23c21845cc91764ca95bd79c8020690f50a74c9a52c7e846a5b2532  post/elm_daily_ne30pg2_texas.nc
ddf7925ef1769c6b5d857651cb5ad183c21d6172a206f72fd896d0a017b33328  post/elm_hourly_ne30pg2_texas.nc
b6a1f9e98ef22fbe598708f651ce19ded5a87cb9e004d6fa47f3ce8e181db457  post/scores.json
c013351b0d78f47cb6f76371c33dea572629b11af9c1fb9d6438945da38b3990  post/scores.csv
30bd267be9f23c2f09b3653513248b00d7a66a37960fe72474c752bf835816a9  post/gauge_daily_sim_obs.csv
0ea248236bfb81254fa8893f90e0a8622056634de181de52b49130af7f4bd207  post/spinup_drift.json
```

### Limitations (summary)

This is an uncalibrated ELM-SP + MOSART baseline at 0.5° forced by NLDAS-2.
It is not a validated product:

* There are no reservoirs or water management.
* It cannot resolve Houston's bayous or urban drainage.
* River inflow from outside the box is lost (Rio Grande, Red River).
* One spin-up cycle (2010–2014) is reused for 30 years. The domain mean meets
  the drift criterion, but ZWT still deepens slowly (+0.79 cm/yr over years
  21–30) and individual cells are not in equilibrium (see the spin-up table).
