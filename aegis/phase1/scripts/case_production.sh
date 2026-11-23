#!/usr/bin/env bash
# Phase 1 production case: hybrid start from the spin-up restart, real years
# 2010-01-01 .. 2017-10-01 with NLDAS-2 2010-2017 (ALIGN=2010).
# ELM keeps history tapes on continue runs (they come from the restart file),
# so the hourly window uses branch segments of the same case:
#   A  hybrid  2010-01-01 -> 2017-08-15   h0 monthly, h1 daily
#   B  branch  2017-08-15 -> 2017-09-15   h0, h1 + h2 hourly
#   C  branch  2017-09-15 -> 2017-10-01   h0, h1
# h0 files for 2017-08 and 2017-09 therefore only cover Aug 15-31 and
# Sep 15-30 (a branch restarts the monthly accumulation); use h1 for those months.
#
# usage: case_production.sh create REFDATE   (REFDATE = spin-up restart date, e.g. 0021-01-01)
#        case_production.sh segA|segB|segC   (configure + run that segment)
set -euo pipefail
. "$(dirname "$0")/common.sh"
C=$CASE_PROD
# dates (overridable for a short test chain)
PROD_START=${PROD_START:-2010-01-01}
PROD_YR_END=${PROD_YR_END:-2017}
SEG_A_STOP=${SEG_A_STOP:-2017-08-15}     # = start of the hourly window
SEG_B_STOP=${SEG_B_STOP:-2017-09-15}     # = end of the hourly window
SEG_C_STOP=${SEG_C_STOP:-2017-10-01}
CASE_NAME=$(basename "$C")
SPIN_NAME=$(basename "$CASE_SPINUP")

KEY="'H2OSOI','SOILWATER_10CM','TSOI','H2OSNO','QRUNOFF','QOVER','QDRAI','ZWT','TWS','FSH','EFLX_LH_TOT','RAIN','TSA'"

write_nl() {  # write_nl hourly(0|1)
  local hourly=$1
  {
    echo "fsurdat = '$SURF_FILE'"
    echo "hist_fincl1 = $KEY,'WA','SNOW'"
    echo "hist_fincl2 = $KEY"
    if [ "$hourly" = 1 ]; then
      echo "hist_fincl3 = $KEY"
      echo "hist_nhtfrq = 0, -24, -1"
      echo "hist_mfilt  = 1, 365, 744"
    else
      echo "hist_nhtfrq = 0, -24"
      echo "hist_mfilt  = 1, 365"
    fi
  } > user_nl_elm
  {
    echo "frivinp_rtm  = '$MOSART_FILE'"
    echo "frivinp_mesh = '$INPUTS/$DOMAIN_FILE'"
    echo "rtmhist_fincl2 = 'RIVER_DISCHARGE_OVER_LAND_LIQ','RIVER_DISCHARGE_TO_OCEAN_LIQ','QSUR_LIQ','QSUB_LIQ','STORAGE_LIQ'"
    if [ "$hourly" = 1 ]; then
      echo "rtmhist_fincl3 = 'RIVER_DISCHARGE_OVER_LAND_LIQ','RIVER_DISCHARGE_TO_OCEAN_LIQ'"
      echo "rtmhist_nhtfrq = 0, -24, -1"
      echo "rtmhist_mfilt  = 1, 365, 744"
    else
      echo "rtmhist_nhtfrq = 0, -24"
      echo "rtmhist_mfilt  = 1, 365"
    fi
  } > user_nl_mosart
}

case ${1:-} in
  create)
    REFDATE=${2:?REFDATE}
    [ -e "$C" ] && { echo "case exists: $C" >&2; exit 1; }
    "$E3SM_ROOT"/cime/scripts/create_clone --case "$C" --clone "$CASE_SPINUP" --keepexe \
        --cime-output-root "$WORK/scratch"
    cd "$C"
    ./case.setup
    apply_forcing "$C"
    ./xmlchange DATM_CLMNCEP_YR_START=${PROD_START%%-*},DATM_CLMNCEP_YR_END=$PROD_YR_END,DATM_CLMNCEP_YR_ALIGN=${PROD_START%%-*}
    ./xmlchange RUN_TYPE=hybrid,RUN_REFCASE="$SPIN_NAME",RUN_REFDATE="$REFDATE",RUN_REFTOD=00000
    ./xmlchange RUN_STARTDATE=$PROD_START,GET_REFCASE=FALSE,ELM_FORCE_COLDSTART=off,RESUBMIT=0
    ./xmlchange DOUT_S=FALSE
    # hourly river coupling (spin-up used the default 3 h): MOSART history
    # frequency is in rof steps, so hourly rtmhist output needs a 1 h rof step
    ./xmlchange ROF_NCPL=24
    # the driver default is end_restart=.false.; each segment must end with a
    # restart set at its STOP_DATE for the next (branch) segment
    echo "end_restart = .true." >> user_nl_cpl
    RUNDIR=$(./xmlquery --value RUNDIR); SRUN=$(cd "$CASE_SPINUP" && ./xmlquery --value RUNDIR)
    mkdir -p "$RUNDIR"
    cp -p "$SRUN"/"$SPIN_NAME".*.r*."$REFDATE"-00000.nc "$RUNDIR"/
    ls -la "$RUNDIR"
    ;;
  segA)
    cd "$C"
    write_nl 0
    ./xmlchange CONTINUE_RUN=FALSE,STOP_OPTION=date,STOP_DATE=${SEG_A_STOP//-/}
    ./xmlchange REST_OPTION=nyears,REST_N=1
    nice -n 10 ./case.submit
    ;;
  segB|segC)
    cd "$C"
    if [ "$1" = segB ]; then REF=$SEG_A_STOP; STOP=${SEG_B_STOP//-/}; write_nl 1
    else REF=$SEG_B_STOP; STOP=${SEG_C_STOP//-/}; write_nl 0; fi
    # RUN_REFCASE == CASE -> the driver sets brnch_retain_casename=.true. (ELM needs it)
    ./xmlchange RUN_TYPE=branch,RUN_REFCASE="$CASE_NAME",RUN_REFDATE=$REF,RUN_REFTOD=00000,GET_REFCASE=FALSE
    ./xmlchange CONTINUE_RUN=FALSE,STOP_OPTION=date,STOP_DATE=$STOP,REST_OPTION=nyears,REST_N=1
    nice -n 10 ./case.submit
    ;;
  *) echo "usage: $0 create REFDATE | segA | segB | segC" >&2; exit 2 ;;
esac
