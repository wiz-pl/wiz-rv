#!/bin/sh
# Check the pipelined core's single-instruction proofs (proofs/PipeProofs/*.wiz), JOBS at a
# time (default 2). The five `Qp.Claim` files (Xor, Or, And, Lui, Auipc) are one whole-record
# `rfl` each: about 20 minutes and up to 5 GB. The `Qp.ClaimG` files are field by field,
# seconds to a minute once Base.wiz is cached (FINDINGS.md H10). WIZ: the command that
# runs wiz (default: wiz; it may have words in front, e.g. a job runner).
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
