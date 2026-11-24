# Common settings for the Aegis Phase 1 E3SM (ELM SP + MOSART) Texas baseline.
# Source from bash:  . aegis/phase1/scripts/common.sh
# shellcheck shell=bash

export PATH=/Volumes/SSD-Data/aegis-data/conda-envs/e3sm/bin:/usr/bin:/bin:/usr/sbin:/sbin
export TMPDIR=/Volumes/SSD-Data/aegis-data/e3sm-work/tmp

E3SM_ROOT=/Volumes/SSD-Data/aegis-data/E3SM
WORK=/Volumes/SSD-Data/aegis-data/e3sm-work
export P1=$WORK/phase1               # phase-1 data root
export DIN_LOC_ROOT=${DIN_LOC_ROOT:-$WORK/inputdata}   # CIME inputdata root
DIN=$DIN_LOC_ROOT                    # (read by make_inputs.py, remap_ne30pg2.py, fetch_nldas2.sh)
TOOLS_PY=/Volumes/SSD-Data/aegis-data/conda-envs/e3sm-tools/bin/python
SCRIPTS=$E3SM_ROOT/aegis/phase1/scripts

# Texas-box r05 inputs built by make_inputs.py
INPUT_TAG=${INPUT_TAG:-c261123}
INPUTS=$P1/inputs
DOMAIN_FILE=domain.lnd.r05_texas.$INPUT_TAG.nc
SURF_FILE=$INPUTS/surfdata_r05_texas_simyr2000.$INPUT_TAG.nc
MOSART_FILE=$INPUTS/MOSART_r05_texas.$INPUT_TAG.nc

COMPSET=2000_DATM%NLDAS2_ELM%SP_SICE_SOCN_MOSART_SGLC_SWAV
RES=ELMMOS_USRDAT
MACH=aegis-mac
COMPILER=gnu
NTASKS=6                             # machine cap (shared with a CI runner)
DRIVER=${DRIVER:-moab}

CASE_SPINUP=${CASE_SPINUP:-$P1/cases/p1tx.nldas2.spinup}
CASE_PROD=${CASE_PROD:-$P1/cases/p1tx.nldas2.prod}

# ---------------------------------------------------------------------------
# Forcing hook. Everything forcing-specific lives here; swapping NLDAS-2 for
# ERA5 later means adding a branch below (DATM_MODE + user_datm.streams.txt.*
# files in aegis/phase1/forcing/<name>/) and setting FORCING=era5.
# ---------------------------------------------------------------------------
FORCING=${FORCING:-nldas2}
apply_forcing() {   # usage: apply_forcing CASEDIR
  local c=$1
  case $FORCING in
    nldas2)
      (cd "$c" && ./xmlchange DATM_MODE=CLMNLDAS2) ;;
    era5)
      (cd "$c" && ./xmlchange DATM_MODE=ELMERA5) ;;
    *) echo "unknown FORCING=$FORCING" >&2; return 1 ;;
  esac
  # optional stream overrides (e.g. a Texas subset of the forcing files)
  local d=$E3SM_ROOT/aegis/phase1/forcing/$FORCING
  if [ -d "$d" ]; then
    for f in "$d"/user_datm.streams.txt.*; do
      [ -e "$f" ] || continue
      sed "s#@P1@#$P1#g; s#@DIN@#$DIN#g" "$f" > "$c/$(basename "$f")"
    done
  fi
}
