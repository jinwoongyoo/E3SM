#!/usr/bin/env bash
# Create, configure and build the Phase 1 spin-up case:
#   cold start, NLDAS-2 2010-2014 looped (ALIGN=1), 20 model years (4 x 5 yr).
# usage: case_spinup.sh [create|build|submit]   (default: create+build)
set -euo pipefail
. "$(dirname "$0")/common.sh"
step=${1:-all}
C=$CASE_SPINUP

if [ "$step" = all ] || [ "$step" = create ]; then
  [ -e "$C" ] && { echo "case exists: $C" >&2; exit 1; }
  "$E3SM_ROOT"/cime/scripts/create_newcase --case "$C" --compset "$COMPSET" --res "$RES" \
      --machine "$MACH" --compiler "$COMPILER" --driver "$DRIVER" \
      --output-root "$WORK/scratch" --handle-preexisting-dirs u
  cd "$C"
  ./xmlchange ELM_USRDAT_NAME=r05_texas
  for X in LND ATM ROF; do
    ./xmlchange ${X}_DOMAIN_FILE="$DOMAIN_FILE",${X}_DOMAIN_PATH="$INPUTS"
  done
  ./xmlchange NTASKS=$NTASKS,NTHRDS=1,ROOTPE=0
  ./xmlchange NTASKS_IAC=1,NTASKS_ESP=1
  apply_forcing "$C"
  ./xmlchange DATM_CLMNCEP_YR_START=2010,DATM_CLMNCEP_YR_END=2014,DATM_CLMNCEP_YR_ALIGN=1
  ./xmlchange RUN_TYPE=startup,RUN_STARTDATE=0001-01-01,ELM_FORCE_COLDSTART=on
  ./xmlchange STOP_OPTION=nyears,STOP_N=5,REST_OPTION=nyears,REST_N=1,RESUBMIT=3
  ./xmlchange DOUT_S=FALSE,JOB_WALLCLOCK_TIME=24:00:00
  cat > user_nl_elm <<EOF
fsurdat = '$SURF_FILE'
! monthly h0 (default fields) plus the spin-up diagnostics
hist_fincl1 = 'TWS','ZWT','H2OSOI','SOILWATER_10CM','H2OSNO','QRUNOFF','QOVER','QDRAI','RAIN','EFLX_LH_TOT','TSOI','WA'
! annual means of the drift variables
hist_fincl2 = 'TWS','ZWT','SOILWATER_10CM','WA','H2OSNO'
hist_nhtfrq = 0, -8760
hist_mfilt  = 1, 1
hist_avgflag_pertape = 'A', 'A'
EOF
  cat > user_nl_mosart <<EOF
frivinp_rtm  = '$MOSART_FILE'
frivinp_mesh = '$INPUTS/$DOMAIN_FILE'
EOF
  ./case.setup
fi

if [ "$step" = all ] || [ "$step" = build ]; then
  cd "$C"
  nice -n 10 ./case.build
fi

if [ "$step" = submit ]; then
  cd "$C"
  nice -n 10 ./case.submit
fi
