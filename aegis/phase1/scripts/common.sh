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

# FORCING selects the DATM forcing (nldas2 | era5); see apply_forcing below
FORCING=${FORCING:-nldas2}
case $FORCING in
  nldas2) COMPSET=2000_DATM%NLDAS2_ELM%SP_SICE_SOCN_MOSART_SGLC_SWAV ;;
  era5)   COMPSET=2000_DATM%ERA5_ELM%SP_SICE_SOCN_MOSART_SGLC_SWAV ;;   # = IERA5ELM
  *) echo "unknown FORCING=$FORCING" >&2; return 1 2>/dev/null || exit 1 ;;
esac
RES=ELMMOS_USRDAT
MACH=aegis-mac
COMPILER=gnu
NTASKS=6                             # machine cap (shared with a CI runner)
DRIVER=${DRIVER:-moab}

CASE_SPINUP=${CASE_SPINUP:-$P1/cases/p1tx.$FORCING.spinup}
CASE_PROD=${CASE_PROD:-$P1/cases/p1tx.$FORCING.prod}

# ---------------------------------------------------------------------------
# Forcing hook: DATM_MODE plus optional user_datm.streams.txt.* templates in
# aegis/phase1/forcing/<FORCING>/ (era5: the Texas subset built by
# era5_forcing.py, since E3SM's ERA5 inputdata only has 1979 and 1981).
# ---------------------------------------------------------------------------
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
