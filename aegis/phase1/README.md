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
| Driver | see "Run log" (`DRIVER` in `scripts/common.sh`) |
| PEs | 6 MPI tasks, 1 thread (machine cap; shared with a CI runner) |
| Coupling | ATM/LND 48 per day (30 min), ROF 8 per day |
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

| Basin (gauge) | Whole basin inside box | Model/USGS area |
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

# 0. inputs (static files via CIME inputdata; NLDAS-2 2010-2017, ~210 GB)
bash $S/fetch_nldas2.sh 2010 2017 10          # resumable, size-verified, 2 mirrors
$PY  $S/fetch_usgs.py $P1/obs                 # USGS daily discharge + site info
(cd $P1 && $PY $S/make_inputs.py inputs --tag c261123)

# 1. spin-up (cold start, NLDAS-2 2010-2014 looped, 20 yr)
bash $S/case_spinup.sh            # create + build
bash $S/case_spinup.sh submit     # 4 x 5 yr (RESUBMIT=3)
$PY  $S/spinup_drift.py $WORK/scratch/p1tx.nldas2.spinup/run p1tx.nldas2.spinup $P1/post/spinup_drift.json

# 2. production 2010-01-01 -> 2017-09-30 (hybrid from the spin-up restart)
bash $S/case_production.sh create 0021-01-01
bash $S/case_production.sh segA   # -> 2017-08-15
bash $S/case_production.sh segB   # branch, hourly output -> 2017-09-15
bash $S/case_production.sh segC   # branch -> 2017-10-01

# 3. post-processing (remap to ne30pg2, USGS scoring, figures)
```

### Tools environment

`env/environment.yml` (conda-forge only) and the explicit lock file
`env/conda-osx-arm64.lock.txt` define the post-processing env at
`/Volumes/SSD-Data/aegis-data/conda-envs/e3sm-tools`:

```bash
~/miniforge3/bin/mamba create -p <prefix> --file env/conda-osx-arm64.lock.txt
```

The E3SM build/run env (`conda-envs/e3sm`) is not modified.

### Swapping the forcing (ERA5 later)

`apply_forcing` in `scripts/common.sh` is the only forcing-specific code. It
sets `DATM_MODE` from `FORCING` (`nldas2` → `CLMNLDAS2`, `era5` → `ELMERA5`).
It also copies any `forcing/<FORCING>/user_datm.streams.txt.*` templates into
the case, replacing `@P1@`/`@DIN@`. To switch, run with `FORCING=era5` and,
if needed, add stream files.

## Gauge matching

USGS gauges (`scripts/p1lib.py: GAUGES`) are matched to MOSART cells. The
candidates are the cell containing the gauge and its 8 neighbours, limited to
cells that drain to the same terminal outlet. The score is
`|ln(areaTotal2 / USGS drainage area)| + 0.25 × distance in cells`, and the
lowest score wins. The two San Jacinto gauges, W Fork 08068000 (2,145 km²) and
Cypress Creek 08069000 (738 km²), are at or below the area of one 0.5° cell
(~2,670 km²), so their area ratios are poor (1.2 and 3.6) and both map to the
same cell. Their scores mainly show this resolution limit.

## Known quirks / deviations

* `map_r05_to_ne30pg2_traave.20231130.nc` is listed in `config_grids.xml`
  under `cpl/gridmaps/r05/`, but the file on the inputdata server is under
  `cpl/gridmaps/ne30pg2/`. It was fetched from the latter.
* The NLDAS-2 DATM files are not on the E3SM (LCRC) inputdata server.
  `fetch_nldas2.sh` gets them from the CESM svn inputdata server or its OSDF
  mirror (byte-identical) into the same relative path under `DIN_LOC_ROOT`.
* ELM ignores history-namelist changes on `CONTINUE_RUN` (history tapes come
  from the restart). So the hourly window (2017-08-15 → 09-15) and the
  following segment are **branch** runs. As a result, the h0 (monthly) files
  for 2017-08 and 2017-09 are partial; use the daily h1 tape for those months.

## Run log / results

_Filled in as the milestones complete._
