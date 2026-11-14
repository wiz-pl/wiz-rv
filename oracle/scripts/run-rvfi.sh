#!/bin/sh
# Generate (and, if the tools exist, run) the riscv-formal checks for the emitted
# Wiz multi-cycle RV32I core.
#
#   oracle/scripts/run-rvfi.sh --fixture alu
#   oracle/scripts/run-rvfi.sh --fixture alu --sby
#   oracle/scripts/run-rvfi.sh --fixture alu --sby --jobs 2
#   oracle/scripts/run-rvfi.sh --instruction add --sby
#   oracle/scripts/run-rvfi.sh --all-insns
#   oracle/scripts/run-rvfi.sh --pipe --fixture hazard      # pipeline rvfi adapter (lint)
#   oracle/scripts/run-rvfi.sh --pipe --instruction add --sby  # riscv-formal insn_add
#   oracle/scripts/run-rvfi.sh --pipe --all-insns              # all 37 base-I checks
#   oracle/scripts/run-rvfi.sh --fixture alu --sby --checks 'insn_add_ch0 insn_lw_ch0'
#   oracle/scripts/run-rvfi.sh --list
#
# It always generates the rvfi wrapper (mkrvfi.py) and lints the wrapper + core
# with iverilog when iverilog is on PATH.  With --sby it fetches riscv-formal at
# the pinned revision (read-only: a clone under oracle/.build), writes a core
# directory (core.v, rvfi.v, wrapper.sv, checks.cfg), runs
# checks/genchecks.py, and runs the generated checks with `sby -f` (a simple
# --jobs pool; no make dependency).
#
# --pipe selects the pipelined core (Rv.Pipe.pipeRvfiCore, emitted by
# oracle/wiz/emit_pipe.wiz), whose outputs are the rvfi retirement port
# (Pp.rvfi): mkrvfi_pipe.py only adds an adapter that ties the bus/I/O inputs and
# adds rvfi_order/mode/ixl.  With --instruction <name> it emits a core whose lane
# memory is that instruction repeated and runs the riscv-formal insn check at the
# pipeline's retirement cycle (4); --pipe --all-insns runs every base-I check.
# Without --instruction the fixture program is a sequence trace (`--sby` is then a
# clean SKIP: the instruction under test would not be at the check cycle).  The
# sequence trace itself is `oracle.py rvfi --pipe`.
#
# Missing tools are a clean SKIP (exit 0); a failing check is a FAIL (exit 1)
# and the script prints the check name and the failing assertion lines from the
# sby log.  A skip is not a pass.
#
# Pinned riscv-formal revision and tool versions used for the first run are in
# oracle/riscv-formal/README.md.  Override the revision with --rev (or
# RISCV_FORMAL_REV); do not point it at a moving branch.

set -eu
cd "$(dirname "$0")/../.."

# The revision this harness was written and run against (2026-07-16).
PINNED_REV=c992aa61fdfe0846c5ed90324c596202a1c69b76

VERILOG=
FIXTURE=alu
OUT=build/rvfi.v
RUN_SBY=0
LIST=0
JOBS=${JOBS:-1}
CHECKS=
CFG=oracle/riscv-formal/checks.cfg
RF_DIR=${RISCV_FORMAL_DIR:-oracle/.build/riscv-formal}
RF_REV=${RISCV_FORMAL_REV:-$PINNED_REV}
FORMAL_MBITS=${FORMAL_MBITS:-8}
INSTRUCTION=
DEPTH=
ALL_INSNS=0
PIPE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --verilog) VERILOG=$2; shift 2 ;;
    --fixture) FIXTURE=$2; shift 2 ;;
    --instruction) INSTRUCTION=$2; shift 2 ;;
    --all-insns) ALL_INSNS=1; shift ;;
    --pipe) PIPE=1; shift ;;
    --out) OUT=$2; shift 2 ;;
    --sby) RUN_SBY=1; shift ;;
    --list) LIST=1; shift ;;
    --jobs) JOBS=$2; shift 2 ;;
    --checks) CHECKS=$2; shift 2 ;;
    --cfg) CFG=$2; shift 2 ;;
    --riscv-formal) RF_DIR=$2; shift 2 ;;
    --rev) RF_REV=$2; shift 2 ;;
    --mbits) FORMAL_MBITS=$2; shift 2 ;;
    -h|--help) sed -n '2,44p' "$0"; exit 0 ;;
    *) echo "run-rvfi.sh: unknown argument $1" >&2; exit 2 ;;
  esac
done

if [ "$PIPE" = 1 ]; then
  EMIT=oracle/.build/emit_pipe
  if [ ! -x "$EMIT" ]; then
    echo "SKIP rvfi pipe core: $EMIT not built"
    echo "     build it: light wiz build oracle/wiz/emit_pipe.wiz -I oracle/wiz -I src -o $EMIT"
    exit 0
  fi
  if [ -n "$VERILOG" ]; then
    echo "run-rvfi.sh: --pipe emits its own core; do not pass --verilog" >&2
    exit 2
  fi
  if [ "$ALL_INSNS" = 1 ]; then
    rc=0
    for name in $(python3 oracle/scripts/formal_insns.py --list); do
      echo "=== instruction $name ==="
      oracle/scripts/run-rvfi.sh --pipe --instruction "$name" --sby --jobs 1 || rc=1
    done
    exit $rc
  fi
  if [ -n "$INSTRUCTION" ]; then
    # The pipeline retires at R, one cycle after the multi-cycle core's completion:
    # every base-I class (ALU, branch/jump, load) has its first beat at cycle 4.
    FIX=oracle/.build/formal-$INSTRUCTION.hex
    python3 oracle/scripts/formal_insns.py --name "$INSTRUCTION" --out "$FIX" >/dev/null
    DEPTH=4
    VERILOG=oracle/.build/rvfi-pipe-formal-$INSTRUCTION.v
    "$EMIT" "$FIX" "$FORMAL_MBITS" > "$VERILOG"
    echo "# pipe core: formal-$INSTRUCTION, $FORMAL_MBITS address bits -> $VERILOG (check cycle $DEPTH)"
    [ -z "$CHECKS" ] && CHECKS="insn_${INSTRUCTION}_ch0"
  else
    VERILOG=oracle/.build/rvfi-pipe-$FIXTURE.v
    "$EMIT" "oracle/fixtures/$FIXTURE.hex" 0 > "$VERILOG"
    echo "# pipe core: $FIXTURE, the fixture's address bits -> $VERILOG"
  fi
  # the pipeline's check cycles differ from the multi-cycle core's
  [ "$CFG" = oracle/riscv-formal/checks.cfg ] && CFG=oracle/riscv-formal/checks-pipe.cfg
  if [ "$OUT" = "build/rvfi.v" ]; then OUT=build/rvfi_pipe.v; fi
  python3 oracle/scripts/mkrvfi_pipe.py --verilog "$VERILOG" --out "$OUT"
  if command -v iverilog >/dev/null 2>&1; then
    echo "$ iverilog -g2005 -Wall -o /dev/null $VERILOG $OUT"
    if iverilog -g2005 -Wall -o /dev/null "$VERILOG" "$OUT"; then
      echo "PASS iverilog lint (rvfi adapter + core)"
    else
      echo "FAIL iverilog lint (rvfi adapter + core)" >&2
      exit 1
    fi
  else
    echo "SKIP iverilog lint: iverilog not on PATH"
    echo "     nix shell nixpkgs#iverilog -c oracle/scripts/run-rvfi.sh --pipe --fixture $FIXTURE"
  fi
  if [ "$RUN_SBY" = 0 ] && [ "$LIST" = 0 ]; then
    echo "SKIP riscv-formal checks: pass --sby (or --list) to use them"
    exit 0
  fi
  if [ "$RUN_SBY" = 1 ] && [ -z "$INSTRUCTION" ]; then
    echo "SKIP riscv-formal checks: --pipe --sby needs --instruction <name>"
    echo "     (a formal check constrains one instruction at the check cycle; the"
    echo "      fixture program is a sequence trace, not a repeated instruction)"
    exit 0
  fi
else


if [ "$ALL_INSNS" = 1 ]; then
  rc=0
  for name in $(python3 oracle/scripts/formal_insns.py --list); do
    echo "=== instruction $name ==="
    oracle/scripts/run-rvfi.sh --instruction "$name" --sby --jobs 1 || rc=1
  done
  exit $rc
fi

# ---- the core Verilog --------------------------------------------------------

if [ -n "$INSTRUCTION" ]; then
  # A core whose whole lane memory is the instruction under test: riscv-formal's
  # insn check constrains the retired instruction, and the core has a fixed
  # program, so this is what makes the check non-vacuous.
  EMIT=oracle/.build/emit_core
  if [ ! -x "$EMIT" ]; then
    echo "SKIP rvfi core: $EMIT not built"
    echo "     build it: light wiz build oracle/wiz/emit_core.wiz -I oracle/wiz -I src -o $EMIT"
    exit 0
  fi
  FIXTURE=formal-$INSTRUCTION
  FIX=oracle/.build/formal-$INSTRUCTION.hex
  DEPTH=$(python3 oracle/scripts/formal_insns.py --name "$INSTRUCTION" --out "$FIX")
  VERILOG=oracle/.build/rvfi-core-$FIXTURE.v
  "$EMIT" "$FIX" "$FORMAL_MBITS" > "$VERILOG"
  echo "# core: $FIXTURE, $FORMAL_MBITS address bits -> $VERILOG (check cycle $DEPTH)"
  [ -z "$CHECKS" ] && CHECKS="insn_${INSTRUCTION}_ch0"
fi

if [ -z "$VERILOG" ]; then
  EMIT=oracle/.build/emit_core
  if [ ! -x "$EMIT" ]; then
    echo "SKIP rvfi core: $EMIT not built"
    echo "     build it: light wiz build oracle/wiz/emit_core.wiz -I oracle/wiz -I src -o $EMIT"
    exit 0
  fi
  VERILOG=oracle/.build/rvfi-core-$FIXTURE.v
  "$EMIT" "oracle/fixtures/$FIXTURE.hex" "$FORMAL_MBITS" > "$VERILOG"
  echo "# core: $FIXTURE, $FORMAL_MBITS address bits -> $VERILOG"
fi

# The formal harness needs the core's register file and byte lanes as *ports*:
# yosys cannot resolve the hierarchical memory references that work in Icarus.
if [ "$RUN_SBY" = 1 ] || [ "$LIST" = 1 ]; then
  FORMAL=${VERILOG%.v}-formal.v
  python3 oracle/scripts/formal_core.py "$VERILOG" "$FORMAL"
  VERILOG=$FORMAL
  python3 oracle/scripts/mkrvfi.py --formal --verilog "$VERILOG" --out "$OUT"
else
  python3 oracle/scripts/mkrvfi.py --verilog "$VERILOG" --out "$OUT"
fi
fi

# ---- wrapper lint ------------------------------------------------------------

if command -v iverilog >/dev/null 2>&1; then
  echo "$ iverilog -g2005 -Wall -o /dev/null $VERILOG $OUT"
  if iverilog -g2005 -Wall -o /dev/null "$VERILOG" "$OUT"; then
    echo "PASS iverilog lint (wrapper + core)"
  else
    echo "FAIL iverilog lint (wrapper + core)" >&2
    exit 1
  fi
else
  echo "SKIP iverilog lint: iverilog not on PATH"
  echo "     nix shell nixpkgs#iverilog -c oracle/scripts/run-rvfi.sh --fixture $FIXTURE"
fi

if [ "$RUN_SBY" = 0 ] && [ "$LIST" = 0 ]; then
  echo "SKIP riscv-formal checks: pass --sby (or --list) to use them"
  exit 0
fi

# ---- the formal tools --------------------------------------------------------

missing=""
for t in sby yosys boolector; do
  command -v "$t" >/dev/null 2>&1 || missing="$missing $t"
done
if [ -n "$missing" ]; then
  echo "SKIP riscv-formal checks: missing$missing"
  echo "     nix shell nixpkgs#yosys nixpkgs#sby nixpkgs#boolector nixpkgs#iverilog \\"
  echo "       -c oracle/scripts/run-rvfi.sh --fixture $FIXTURE --sby"
  exit 0
fi

# ---- riscv-formal at the pinned revision ------------------------------------

if [ ! -d "$RF_DIR/.git" ]; then
  echo "$ git clone https://github.com/YosysHQ/riscv-formal $RF_DIR"
  git clone -q https://github.com/YosysHQ/riscv-formal "$RF_DIR"
fi
# The pin may be newer than the clone's default branch tip; fetch it by hash.
git -C "$RF_DIR" fetch -q origin "$RF_REV" 2>/dev/null || true
git -C "$RF_DIR" checkout -q "$RF_REV"
got=$(git -C "$RF_DIR" rev-parse HEAD)
if [ "$got" != "$RF_REV" ]; then
  echo "FAIL riscv-formal revision: wanted $RF_REV, checked out $got" >&2
  exit 1
fi
echo "# riscv-formal: $RF_REV ($(git -C "$RF_DIR" log -1 --format=%cs))"

CORE_DIR=$RF_DIR/cores/wiz-rv
rm -rf "$CORE_DIR"
mkdir -p "$CORE_DIR"
cp "$VERILOG" "$CORE_DIR/core.v"
cp "$OUT" "$CORE_DIR/rvfi.v"
cp oracle/riscv-formal/wrapper.sv "$CORE_DIR/wrapper.sv"
if [ -n "$DEPTH" ]; then
  sed "s/^insn .*/insn $DEPTH/" "$CFG" > "$CORE_DIR/checks.cfg"
else
  cp "$CFG" "$CORE_DIR/checks.cfg"
fi

echo "$ (cd $CORE_DIR && python3 ../../checks/genchecks.py)"
( cd "$CORE_DIR" && python3 ../../checks/genchecks.py ) || {
  echo "FAIL genchecks.py" >&2
  exit 1
}

if [ "$LIST" = 1 ]; then
  ( cd "$CORE_DIR/checks" && ls *.sby | sed 's/\.sby$//' )
  exit 0
fi

targets=${CHECKS:-all}
targets=$(echo "$targets" | tr ',' ' ')
if [ "$targets" = "all" ]; then
  check_list=$(cd "$CORE_DIR/checks" && ls *.sby | sed 's/\.sby$//')
else
  check_list=$targets
fi

# Run sby directly rather than through the generated makefile: `make` is not
# part of the minimal nix shell and its absence would look like a test failure.
echo "$ sby -f <check>.sby  (jobs $JOBS, $(echo "$check_list" | wc -w) check(s))"
set +e
running=0
for check in $check_list; do
  if [ ! -f "$CORE_DIR/checks/$check.sby" ]; then
    echo "FAIL $check (no $check.sby)"
    continue
  fi
  ( cd "$CORE_DIR/checks" && sby -f "$check.sby" ) &
  running=$((running + 1))
  if [ "$running" -ge "$JOBS" ]; then
    wait
    running=0
  fi
done
wait
set -e

# ---- report ----------------------------------------------------------------

failed=0
for check in $check_list; do
  status="$CORE_DIR/checks/$check/status"
  if [ ! -f "$status" ]; then
    failed=$((failed + 1))
    echo "FAIL $check (no status: the check did not complete)"
    continue
  fi
  result=$(cat "$status")
  case "$result" in
  PASS*)
    echo "PASS $check"
    ;;
  *)
    failed=$((failed + 1))
    echo "FAIL $check ($result)"
    log="$CORE_DIR/checks/$check/logfile.txt"
    [ -f "$log" ] || log="$CORE_DIR/checks/$check/engine_0/logfile.txt"
    if [ -f "$log" ]; then
      echo "  --- $check: failing assertions / errors ---"
      grep -aE "Assert|ERROR|Unreached|Timeout|failed|FAIL" "$log" | tail -20 | sed 's/^/  /'
    fi
    ;;
  esac
done
echo
echo "$failed check(s) failed"
[ "$failed" = 0 ] || exit 1
exit 0
