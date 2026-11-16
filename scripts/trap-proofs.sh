#!/bin/sh
# Check the multi-cycle core's trap-entry proofs (proofs/TrapProofs/*.wiz), JOBS at a
# time (default 2; each in its own process). WIZ: the command that runs
# wiz (default: wiz; it may have words in front, e.g. a job runner).
cd "$(dirname "$0")/.."
WIZ=${WIZ:-wiz}
one() {
  if $WIZ check -I src -I proofs "$1" > "$1.log" 2>&1 && ! grep -q error "$1.log"; then echo "ok   $1"; else echo "FAIL $1"; cat "$1.log"; fi
}
n=0
for f in proofs/TrapProofs/*.wiz; do
  [ "$f" = proofs/TrapProofs/Base.wiz ] && continue
  one "$f" &
  n=$((n + 1))
  if [ $n -ge ${JOBS:-2} ]; then wait; n=0; fi
done
wait
