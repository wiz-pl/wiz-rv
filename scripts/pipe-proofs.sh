#!/bin/sh
# Check the pipelined core's single-instruction proofs (proofs/PipeProofs/*.wiz), JOBS at a
# time (default 2; each takes about 20 minutes and 1 to 2 GB). WIZ: the command that runs
# wiz (default: wiz; it may have words in front, e.g. a job runner).
cd "$(dirname "$0")/.."
WIZ=${WIZ:-wiz}
one() {
  if $WIZ check -I src -I proofs "$1" > "$1.log" 2>&1 && ! grep -q error "$1.log"; then echo "ok   $1"; else echo "FAIL $1"; cat "$1.log"; fi
}
n=0
for f in proofs/PipeProofs/*.wiz; do
  [ "$f" = proofs/PipeProofs/Base.wiz ] && continue
  one "$f" &
  n=$((n + 1))
  if [ $n -ge ${JOBS:-2} ]; then wait; n=0; fi
done
wait
