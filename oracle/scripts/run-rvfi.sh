#!/bin/sh
# Generate (and, if the tools exist, check) the rvfi wrapper for the emitted core.
#
#   oracle/scripts/run-rvfi.sh --verilog build/rv32im_arty.v
#   oracle/scripts/run-rvfi.sh --verilog build/rv32im_arty.v --sby
#
# It always generates the wrapper, and lints it with iverilog when iverilog is on
# PATH.  With --sby it also runs riscv-formal's per-instruction checks, which
# needs sby and yosys (and a clone of riscv-formal at a pinned revision).
#
# Run in this branch: generation and `iverilog -g2005 -Wall` lint (iverilog 13.0
# from nixpkgs), and an Icarus simulation of the rvfi beats against the Python
# reference (`oracle.py rvfi`).  NOT run: the riscv-formal checks themselves
# (sby/yosys absent, no riscv-formal clone).  Record every tool version in the
# report when they are run.
set -eu
cd "$(dirname "$0")/../.."

VERILOG=build/rv32im_arty.v
OUT=build/rvfi.v
RUN_SBY=0
RF_DIR=${RISCV_FORMAL_DIR:-oracle/.build/riscv-formal}
RF_REV=${RISCV_FORMAL_REV:-}
while [ $# -gt 0 ]; do
  case "$1" in
    --verilog) VERILOG=$2; shift 2 ;;
    --out) OUT=$2; shift 2 ;;
    --sby) RUN_SBY=1; shift ;;
    --riscv-formal) RF_DIR=$2; shift 2 ;;
    --rev) RF_REV=$2; shift 2 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "run-rvfi.sh: unknown argument $1" >&2; exit 2 ;;
  esac
done

if [ ! -f "$VERILOG" ]; then
  echo "run-rvfi.sh: $VERILOG: no emitted core" >&2
  echo "  generate it first: grail run rv gen   (writes build/<design>.v)" >&2
  exit 2
fi

python3 oracle/scripts/mkrvfi.py --verilog "$VERILOG" --out "$OUT"

if command -v iverilog >/dev/null 2>&1; then
  echo "$ iverilog -g2005 -Wall -o /dev/null $VERILOG $OUT"
  if iverilog -g2005 -Wall -o /dev/null "$VERILOG" "$OUT"; then
    echo "PASS iverilog lint ($(iverilog -V 2>&1 | head -1))"
  else
    echo "FAIL iverilog lint" >&2
    exit 1
  fi
else
  echo "SKIP iverilog lint: iverilog not on PATH"
  echo "     nix shell nixpkgs#iverilog -c oracle/scripts/run-rvfi.sh --verilog $VERILOG"
fi

if [ "$RUN_SBY" = 0 ]; then
  echo "SKIP riscv-formal checks: pass --sby to run them"
  exit 0
fi

if ! command -v sby >/dev/null 2>&1 || ! command -v yosys >/dev/null 2>&1; then
  echo "SKIP riscv-formal checks: sby/yosys not on PATH"
  echo "     nix shell nixpkgs#yosys nixpkgs#sby nixpkgs#iverilog \\"
  echo "       -c oracle/scripts/run-rvfi.sh --verilog $VERILOG --sby"
  exit 0
fi

if [ -z "$RF_REV" ]; then
  echo "run-rvfi.sh: set RISCV_FORMAL_REV to the riscv-formal commit you are testing" >&2
  echo "  (no revision is claimed by this repository; e.g. export RISCV_FORMAL_REV=<sha>)" >&2
  exit 2
fi

if [ ! -d "$RF_DIR" ]; then
  echo "$ git clone https://github.com/YosysHQ/riscv-formal $RF_DIR"
  git clone https://github.com/YosysHQ/riscv-formal "$RF_DIR"
  git -C "$RF_DIR" checkout "$RF_REV"
fi

mkdir -p "$RF_DIR/dut"
cp "$OUT" "$RF_DIR/dut/rvfi_wrapper.v"
# riscv-formal's checks read the wrapper from dut/; the emitted core is a second
# file in the same directory.
cp "$VERILOG" "$RF_DIR/dut/core.v"

echo "$ make -C $RF_DIR/checks"
make -C "$RF_DIR/checks"
for check in insn_ch0 insn_ch1 insn_ch2 rvfi_mem; do
  if [ -f "$RF_DIR/checks/$check/$check.sby" ]; then
    echo "$ sby -f $RF_DIR/checks/$check/$check.sby"
    ( cd "$RF_DIR" && sby -f "checks/$check/$check.sby" ) || exit 1
  else
    echo "SKIP $check (not present in this riscv-formal revision)"
  fi
done
echo "done: record the riscv-formal revision, yosys and sby versions in the report"
