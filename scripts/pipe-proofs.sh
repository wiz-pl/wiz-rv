#!/bin/sh
# Check the pipelined core's single-instruction proofs (src/Rv/PipeProofs/*.wiz) outside
# grail, one `wiz check` per file, JOBS at a time (default 1), printing each file's wall
# time and peak memory. `grail build` checks the same files as part of the library; this
# is for timing them one by one. The five `Qp.Claim` files are the slow ones
# (src/Rv/PipeProofs/README.md has the measured figures). WIZ: the command that runs wiz
# (default: wiz; it may have words in front, e.g. a job runner).
cd "$(dirname "$0")/.."
WIZ=${WIZ:-wiz}
one() {
  if /usr/bin/env time -f "%e s %M KB" -o "$1.time" $WIZ check -I src -I ../wiz-ddr3/src "$1" > "$1.log" 2>&1 \
      && ! grep -q error "$1.log"; then echo "ok   $1 $(cat "$1.time")"; else echo "FAIL $1 $(cat "$1.time")"; cat "$1.log"; fi
}
one src/Rv/PipeProofs/Base.wiz
n=0
for f in src/Rv/PipeProofs/*.wiz; do
  [ "$f" = src/Rv/PipeProofs/Base.wiz ] && continue
  one "$f" &
  n=$((n + 1))
  if [ $n -ge ${JOBS:-1} ]; then wait; n=0; fi
done
wait
