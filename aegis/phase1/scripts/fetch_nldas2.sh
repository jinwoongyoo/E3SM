#!/usr/bin/env bash
# Resumable, size-verified download of the CTSM/E3SM DATM NLDAS-2 forcing
# (DATM_MODE=CLMNLDAS2: atm_forcing.datm7.NLDAS2.0.125d.v1/{Solar,Precip,TPQWL})
# from the CESM inputdata mirrors into DIN_LOC_ROOT (the same paths CIME's
# check_input_data would use). ~2.2 GB per month (CONUS, hourly, 0.125 deg).
#
# usage: fetch_nldas2.sh YEAR_START YEAR_END [NJOBS]   (NJOBS default 4)
# A file is accepted only when its size equals the server Content-Length and it
# starts with a NetCDF/HDF5 signature. Partial files (*.part) are resumed with
# curl -C -. Re-running is safe and only fetches what is missing. The script
# exits non-zero unless all (YEAR_END-YEAR_START+1)*36 files (3 streams x 12
# months) are reported present, so a worker that dies silently is caught.
set -euo pipefail
[ $# -ge 2 ] || { echo "usage: $0 YEAR_START YEAR_END [NJOBS]" >&2; exit 2; }
Y0=$1; Y1=$2; NJOBS=${3:-4}
DIN=${DIN_LOC_ROOT:-/Volumes/SSD-Data/aegis-data/e3sm-work/inputdata}
export DIN
REL=atm/datm7/atm_forcing.datm7.NLDAS2.0.125d.v1

fetch1() {
  set -euo pipefail
  local rel=$1 f="$DIN/$1" part="$DIN/$1.part" len s m attempt
  # OSDF first: ~4 MB/s per connection and supports byte ranges (resume).
  # The svn server is ~0.5 MB/s per connection and ignores Range (no resume),
  # so it is only a fallback. The files on both are byte-identical.
  local mirrors=(https://osdf-director.osg-htc.org/ncar/gdex/d651077/cesmdata/inputdata
                 https://svn-ccsm-inputdata.cgd.ucar.edu/trunk/inputdata)
  mkdir -p "$(dirname "$f")"
  for attempt in 1 2 3 4 5; do
    for s in "${mirrors[@]}"; do
      # "|| true": under set -e a failed HEAD would otherwise end fetch1
      # silently and orphan the file.
      # only the final response of the redirect chain counts: reset on each
      # status line (a redirect's own Content-Length must not be used)
      len=$( { curl -sfIL --connect-timeout 20 --max-time 60 "$s/$rel" || true; } |
            tr -d '\r' | awk '/^HTTP\//{v=""} tolower($1)=="content-length:"{v=$2} END{print v}')
      # every NLDAS-2 monthly file is > 1 GB; a missing/zero/odd length (e.g. an
      # error page) must never be used to accept or prune a file
      case $len in ''|*[!0-9]*) continue ;; esac
      [ "$len" -gt 1000000 ] || continue
      if [ -f "$f" ] && [ "$(stat -f %z "$f")" = "$len" ]; then echo "HAVE    $rel"; return 0; fi
      if [ -f "$part" ] && [ "$(stat -f %z "$part")" -gt "$len" ]; then rm -f "$part"; fi
      if [ "$s" = "${mirrors[0]}" ]; then
        curl -sfL --connect-timeout 20 --speed-limit 20000 --speed-time 60 -C - \
             -o "$part" "$s/$rel" || true
      else
        # svn ignores Range, so "-C -" can never finish a partial file there:
        # fetch the whole file and keep it only if it is complete.
        curl -sfL --connect-timeout 20 --speed-limit 20000 --speed-time 60 \
             -o "$part.svn" "$s/$rel" || true
        if [ -f "$part.svn" ] && [ "$(stat -f %z "$part.svn")" = "$len" ]; then
          mv -f "$part.svn" "$part"
        else
          rm -f "$part.svn"
        fi
      fi
      if [ -f "$part" ] && [ "$(stat -f %z "$part")" = "$len" ]; then
        m=$(LC_ALL=C head -c 4 "$part" | od -An -tx1 | tr -d ' \n')
        case $m in 43444601|43444602|43444605|89484446) ;;
          *) echo "BADMAGIC $rel" >&2; rm -f "$part"; continue ;; esac
        mv -f "$part" "$f"; echo "OK      $rel $len"; return 0
      fi
    done
    sleep $((attempt * 10))
  done
  echo "MISSING $rel"; return 1
}
export -f fetch1

for y in $(seq "$Y0" "$Y1"); do for m in 01 02 03 04 05 06 07 08 09 10 11 12; do
  echo "$REL/TPQWL/ctsmforc.NLDAS2.0.125d.v1.TPQWL.$y-$m.nc"
  echo "$REL/Precip/ctsmforc.NLDAS2.0.125d.v1.Prec.$y-$m.nc"
  echo "$REL/Solar/ctsmforc.NLDAS2.0.125d.v1.Solr.$y-$m.nc"
done; done | xargs -n 1 -P "$NJOBS" bash -c 'fetch1 "$1"' _ |
  awk -v want=$(( (Y1 - Y0 + 1) * 36 )) \
      '/^HAVE/{h++} /^OK/{o++} /^MISSING/{x++} {print; fflush()}
       END{printf "fetch_nldas2: %d present, %d downloaded, %d missing, %d expected\n",h,o,x,want
           if (h + o != want) {printf "fetch_nldas2: FAIL, %d files unaccounted for\n", want - h - o; exit 1}}'
