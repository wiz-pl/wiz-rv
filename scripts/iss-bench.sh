#!/bin/sh
# Run the freestanding RV32IM benchmark (sw/bench) in the host ISS.
#
#   ./scripts/iss-bench.sh
#   ISS=build/iss/bin/iss BENCH=build/bench/bench.bin ./scripts/iss-bench.sh
#
# The ISS loads bench.bin at 0x40000000 and starts there (the DDR layout the boot
# loader + rvload use). It prints instructions and cycles for the whole program;
# the benchmark also prints its own per-section cycle counts from the machine's
# cycle counter (sw/hw.h). No hardware is involved.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ISS=${ISS:-$root/build/iss/bin/iss}
BENCH=${BENCH:-$root/build/bench/bench.bin}

if [ ! -x "$ISS" ]; then
  echo "SKIP iss-bench: no ISS at $ISS (run: make iss)"
  exit 0
fi
if [ ! -f "$BENCH" ]; then
  echo "SKIP iss-bench: no benchmark at $BENCH (run: make bench)"
  exit 0
fi

out=$(mktemp) || exit 1
err=$(mktemp) || { rm -f "$out"; exit 1; }
trap 'rm -f "$out" "$err"' EXIT HUP INT TERM

if ! "$ISS" "$BENCH" -n 200000000 > "$out" 2> "$err"; then
  cat "$out"
  cat "$err" >&2
  echo "FAIL iss-bench: the ISS returned nonzero" >&2
  exit 1
fi

cat "$out"
cat "$err" >&2

if ! grep -q '^bench: PASS ' "$out"; then
  echo "FAIL iss-bench: no 'bench: PASS' line" >&2
  exit 1
fi
if ! grep -q '^\[iss\] .* instructions, .* cycles' "$err"; then
  echo "FAIL iss-bench: the ISS printed no instruction/cycle summary" >&2
  exit 1
fi
echo "PASS iss-bench"
