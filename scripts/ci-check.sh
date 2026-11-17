#!/bin/sh
# `wiz check` every module of the library (src/, the proofs in src/Rv/Proofs.wiz and
# src/Rv/TrapProofs/ included) and the programs (app/), JOBS at a time (default 2), each
# in its own process. Exits 1 if any file fails; prints the failing files' output.
# CI's `wiz check` job runs this (.github/workflows/ci.yml); locally, put it under the
# project's job runner. WIZ: the command that runs wiz (default: wiz). DDR3: wiz-ddr3's
# src directory (default: ../wiz-ddr3/src, as grail.wiz has it). Arguments: the files to
# check instead of all of them.
set -u
cd "$(dirname "$0")/.." || exit 2
WIZ=${WIZ:-wiz}
DDR3=${DDR3:-../wiz-ddr3/src}
LOGS=${LOGS:-.grail/ci-check}
mkdir -p "$LOGS"
if [ $# -eq 0 ]; then
  # shellcheck disable=SC2046 # no spaces in the repository's paths
  set -- $(find src app -name '*.wiz' | sort)
fi
# one line per file: "ok   FILE SECONDS" or "FAIL FILE SECONDS"
printf '%s\n' "$@" | xargs -P "${JOBS:-2}" -I{} sh -c '
  f=$1; log=$2/$(printf %s "$f" | tr / _).log; t0=$(date +%s)
  if $3 check -I src -I "$4" "$f" > "$log" 2>&1; then r=ok; else r=FAIL; fi
  echo "$(printf %-4s $r) $f $(( $(date +%s) - t0 ))s"
' sh {} "$LOGS" "$WIZ" "$DDR3" | tee "$LOGS/summary.txt"
n=$(grep -c '^FAIL' "$LOGS/summary.txt")
total=$(wc -l < "$LOGS/summary.txt")
for f in $(awk '$1 == "FAIL" { print $2 }' "$LOGS/summary.txt"); do
  echo "::group::$f"; cat "$LOGS/$(printf %s "$f" | tr / _).log"; echo "::endgroup::"
done
echo "$((total - n)) of $total files check"
[ "$n" -eq 0 ]
