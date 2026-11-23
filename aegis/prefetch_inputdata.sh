#!/usr/bin/env bash
# Parallel prefetch of the input files a CIME case needs (Buildconf/*.input_data_list).
# CIME's own check_input_data downloads serially; for the DATM CLM_QIAN stream
# (1188 monthly T62 files, ~37.4 GiB) that is slow. Each file is tried on the E3SM
# server first, then on the CESM inputdata mirrors (svn server and NCAR GDEX/OSDF,
# which serve byte-identical files). Stalled transfers are aborted and retried.
# Downloads are checked (NetCDF/HDF5 magic for .nc, non-empty non-HTML otherwise)
# before being moved into place.
#
# Usage: prefetch_inputdata.sh CASEROOT [NJOBS]   (NJOBS default 6)
# Uses the conda env $AEGIS_E3SM_ENV (default below) for CIME's xmlquery, which
# needs the env's python3 and xmllint (config_machines.xml uses DTD entities).
# Exit status: 0 if every listed file under DIN_LOC_ROOT is present afterwards,
# 1 if any file is still missing, 2 on usage errors.
# Works with the macOS system bash 3.2 and BSD xargs.
set -euo pipefail

usage() { echo "usage: $0 CASEROOT [NJOBS]" >&2; exit 2; }
[ $# -ge 1 ] && [ $# -le 2 ] || usage
CASEROOT=$1
NJOBS=${2:-6}
case $NJOBS in ''|*[!0-9]*) echo "error: NJOBS must be a positive integer" >&2; usage ;; esac
[ "$NJOBS" -ge 1 ] || usage
AEGIS_E3SM_ENV=${AEGIS_E3SM_ENV:-/Volumes/SSD-Data/aegis-data/conda-envs/e3sm}
export PATH="$AEGIS_E3SM_ENV/bin:$PATH"
for tool in python3 xmllint; do
  p=$(command -v "$tool" || true)
  case $p in
    "$AEGIS_E3SM_ENV/bin/"*) ;;
    *) echo "error: $tool must come from $AEGIS_E3SM_ENV/bin (found '${p:-none}'); set AEGIS_E3SM_ENV" >&2; exit 2 ;;
  esac
done
[ -d "$CASEROOT/Buildconf" ] && [ -x "$CASEROOT/xmlquery" ] ||
  { echo "error: $CASEROOT is not a CIME case (no Buildconf/ or xmlquery)" >&2; exit 2; }
shopt -s nullglob
lists=("$CASEROOT"/Buildconf/*.input_data_list)
shopt -u nullglob
[ ${#lists[@]} -gt 0 ] ||
  { echo "error: no Buildconf/*.input_data_list in $CASEROOT (run case.setup first)" >&2; exit 2; }

DIN=$(cd "$CASEROOT" && ./xmlquery --value DIN_LOC_ROOT)
while [ "${DIN%/}" != "$DIN" ]; do DIN=${DIN%/}; done
[ -n "$DIN" ] || { echo "error: empty DIN_LOC_ROOT" >&2; exit 2; }
export DIN

fetch() {
  set -euo pipefail
  local f=$1 rel=${1#"$DIN"/} tmp attempt s
  if [ -s "$f" ]; then echo "HAVE    $rel"; return 0; fi
  mkdir -p "$(dirname "$f")"
  # one worker process per file, so a global name and process-wide traps are safe
  FETCH_TMP="$f.part.$$"; tmp=$FETCH_TMP
  trap 'rm -f "$FETCH_TMP"' EXIT
  trap 'rm -f "$FETCH_TMP"; exit 130' INT TERM
  local cesm=(https://svn-ccsm-inputdata.cgd.ucar.edu/trunk/inputdata
              https://osdf-director.osg-htc.org/ncar/gdex/d651077/cesmdata/inputdata)
  # alternate the CESM mirror order to spread load
  if (( $$ % 2 )); then cesm=("${cesm[1]}" "${cesm[0]}"); fi
  for attempt in 1 2 3; do
    for s in https://web.lcrc.anl.gov/public/e3sm/inputdata "${cesm[@]}"; do
      rm -f "$tmp"
      curl -sfL --connect-timeout 20 --speed-limit 50000 --speed-time 30 \
           -o "$tmp" "$s/$rel" || continue
      valid "$tmp" "$f" || { echo "BADFILE $rel from $s" >&2; continue; }
      mv -f "$tmp" "$f"
      if [ -s "$f" ]; then echo "OK      $rel"; return 0; fi
    done
  done
  rm -f "$tmp"
  echo "MISSING $rel"
  return 1
}

# valid TMPFILE TARGETNAME: non-empty; NetCDF/HDF5 magic for *.nc; never HTML.
valid() {
  local t=$1 name=$2 magic
  [ -s "$t" ] || return 1
  magic=$(LC_ALL=C head -c 4 "$t" | od -An -tx1 | tr -d ' \n')
  case $name in
    *.nc) case $magic in 43444601|43444602|43444605|89484446) return 0 ;; *) return 1 ;; esac ;;
  esac
  ! LC_ALL=C head -c 1024 "$t" | grep -aqiE '<!doctype html|<html'
}
export -f fetch valid

set +e
cat "${lists[@]}" |
  sed -n 's/^[^=]*= *//p' |
  sed 's/[[:space:]]*$//' |
  awk -v pfx="$DIN/" 'index($0, pfx) == 1 && substr($0, length($0)) != "/"' |
  sort -u |
  tr '\n' '\0' |
  xargs -0 -n 1 -P "$NJOBS" bash -c 'set -euo pipefail; fetch "$1"' _ |
  awk '
    /^HAVE/    { have++; next }
    /^OK/      { ok++ }
    /^MISSING/ { miss++ }
    { print; fflush() }
    END {
      printf "prefetch summary: %d already present, %d downloaded, %d missing\n", have, ok, miss
      exit (miss > 0)
    }'
st=("${PIPESTATUS[@]}")
set -e
# stages: cat sed sed awk sort tr xargs(fails if any fetch failed) summary-awk
for i in "${!st[@]}"; do
  if [ "${st[$i]}" -ne 0 ]; then
    echo "prefetch: FAILED (pipeline exit statuses: ${st[*]})" >&2
    exit 1
  fi
done
