#!/usr/bin/env bash
# Parallel prefetch of the input files a CIME case needs (Buildconf/*.input_data_list).
# CIME's own check_input_data downloads serially; for the DATM CLM_QIAN stream
# (1188 monthly T62 files, ~37.4 GiB) that is slow. Each file is tried on the E3SM
# server first, then on the CESM inputdata mirrors (svn server and NCAR GDEX/OSDF,
# which serve byte-identical files). Stalled transfers are aborted and retried.
# Usage: prefetch_inputdata.sh CASEROOT [NJOBS]
set -euo pipefail
CASEROOT=$1; NJOBS=${2:-6}
DIN=$(cd "$CASEROOT" && ./xmlquery --value DIN_LOC_ROOT)
export DIN
fetch() {
  local f=$1 rel=${1#"$DIN"/} n=$RANDOM
  [ -s "$f" ] && return 0
  mkdir -p "$(dirname "$f")"
  local cesm=(https://svn-ccsm-inputdata.cgd.ucar.edu/trunk/inputdata
              https://osdf-director.osg-htc.org/ncar/gdex/d651077/cesmdata/inputdata)
  # alternate the CESM mirror order to spread load
  if (( n % 2 )); then cesm=("${cesm[1]}" "${cesm[0]}"); fi
  for attempt in 1 2 3; do
    for s in https://web.lcrc.anl.gov/public/e3sm/inputdata "${cesm[@]}"; do
      if curl -sfL --connect-timeout 20 --speed-limit 50000 --speed-time 30 \
           -o "$f.part.$n" "$s/$rel"; then
        mv "$f.part.$n" "$f"; echo "OK  $rel"; return 0
      fi
      rm -f "$f.part.$n"
    done
  done
  echo "MISSING $rel"
}
export -f fetch
cat "$CASEROOT"/Buildconf/*.input_data_list | sed -n 's/^[^=]*= *//p' | grep "^$DIN/" | grep -v '/$' | sort -u |
  xargs -P "$NJOBS" -I{} bash -c 'fetch "$@"' _ {}
