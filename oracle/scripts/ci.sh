#!/bin/sh
# CI / test entry point for the independent oracle.
#
#   oracle/scripts/ci.sh              # selftest + rvfi wrapper lint/simulation
#   oracle/scripts/ci.sh --formal     # also run the riscv-formal checks
#
# A missing build (the Wiz trace binaries) or missing external tools (iverilog,
# sby, yosys, boolector) is a clean SKIP with exit 0; a real comparison failure
# is a FAIL with exit 1.  This is deliberate: CI machines without the formal
# toolchain should not fail the oracle job, but a run that did happen must not
# be reported as a pass when a backend was skipped.
set -eu
cd "$(dirname "$0")/../.."

formal=0
[ "${1:-}" = "--formal" ] && formal=1

if [ -x oracle/.build/isa_trace ] && [ -x oracle/.build/core_trace ]; then
  python3 oracle/scripts/oracle.py selftest || exit 1
else
  echo "SKIP oracle selftest: oracle/.build/{isa,core}_trace not built"
  echo "     light wiz build oracle/wiz/isa_trace.wiz  -I oracle/wiz -I src -o oracle/.build/isa_trace"
  echo "     light wiz build oracle/wiz/core_trace.wiz -I oracle/wiz -I src -o oracle/.build/core_trace"
  echo "     light wiz build oracle/wiz/pipe_trace.wiz -I oracle/wiz -I src -o oracle/.build/pipe_trace"
fi

if [ -x oracle/.build/emit_core ]; then
  if [ "$formal" = 1 ]; then
    oracle/scripts/run-rvfi.sh --instruction add --sby || exit 1
  else
    oracle/scripts/run-rvfi.sh --fixture alu || exit 1
  fi
else
  echo "SKIP oracle rvfi: oracle/.build/emit_core not built"
  echo "     light wiz build oracle/wiz/emit_core.wiz -I oracle/wiz -I src -o oracle/.build/emit_core"
fi

if [ -x oracle/.build/emit_pipe ]; then
  oracle/scripts/run-rvfi.sh --pipe --fixture hazard || exit 1
  python3 oracle/scripts/oracle.py rvfi --pipe --fixture hazard || exit 1
else
  echo "SKIP oracle pipe rvfi: oracle/.build/emit_pipe not built"
  echo "     light wiz build oracle/wiz/emit_pipe.wiz -I oracle/wiz -I src -o oracle/.build/emit_pipe"
fi
