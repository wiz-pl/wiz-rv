#!/bin/sh
# golem on the Arty A7-35T: a thin wrapper around `.grail/bin/golem` that finds the
# openXC7 tools in PATH or in the Nix store (this machine's devShell puts them there).
#
#   scripts/golem-board.sh board              the pin/clock/reset check
#   scripts/golem-board.sh gen [--boot rom]   build/golem.v, build/golem.xdc
#   scripts/golem-board.sh synth              gen, then yosys synthesis only
#   scripts/golem-board.sh bit                gen, yosys, nextpnr-xilinx, fasm2frames,
#                                             xc7frames2bit -> build/a35t/golem.bit
#   scripts/golem-board.sh timing             the 100 MHz report from the last run
#   scripts/golem-board.sh dry                board + gen, and the hardware step
#   scripts/golem-board.sh ecp5 [--fabric F] [--top N] [--device 85k|45k] [--seed N]
#                                             synth_ecp5 on the board netlist, with
#                                             the Arty PLL/PHY as black boxes (area);
#                                             --fabric places a fabric-only netlist
#                                             (the study's golem1s_fab/golem4mc_fab)
#                                             with nextpnr-ecp5 for an Fmax
#   scripts/golem-board.sh flash [BIT]        print the load command; only runs with
#                                             GOLEM_FLASH=1 (the brief does not
#                                             authorise hardware)
#
# Options after the command: --boot rom|loader (default loader, Prog.boot), --variant
# golem|mc|both (default golem; mc is golemMc at 50 MHz effective).
#
# Build the driver first: `grail build` (or `heavy grail build`).
set -eu
cd "$(dirname "$0")/.."

first_bin() {
  for p in "$@"; do
    if [ -x "$p" ]; then printf '%s\n' "$p"; return 0; fi
  done
  return 1
}
first_file() {
  for p in "$@"; do
    if [ -e "$p" ]; then printf '%s\n' "$p"; return 0; fi
  done
  return 1
}

find_bin() {
  v=$(command -v "$1" 2>/dev/null || true)
  if [ -n "$v" ]; then printf '%s\n' "$v"; return 0; fi
  shift
  first_bin "$@"
}

case "${1:-}" in
  flash|load)
    BIN=${2:-build/a35t/golem.bit}
    echo "hardware step: openFPGALoader -b arty_a7_35t $BIN  (SRAM only)"
    echo "then, on the UART: stty -F PORT 1000000 raw -echo; cat PORT"
    echo "loader prints \"wiz-rv boot\" and \"DDR ok\"/\"DDR fail\"; LD0 done, LD1 failed"
    if [ "${GOLEM_FLASH:-0}" != "1" ]; then
      echo "not flashing: set GOLEM_FLASH=1 only when the brief authorises the board" >&2
      exit 1
    fi
    OFL=${OPENFPGALOADER:-$(find_bin openFPGALoader /nix/store/*-openfpgaloader-*/bin/openFPGALoader || true)}
    [ -n "$OFL" ] || { echo "openFPGALoader not found" >&2; exit 1; }
    exec "$OFL" -b arty_a7_35t "$BIN"
    ;;
esac

[ -x .grail/bin/golem ] || {
  echo "no .grail/bin/golem: run \`grail build\` first" >&2
  exit 1
}

if [ -z "${GOLEM_YOSYS:-}" ]; then
  YOSYS=$(find_bin yosys /nix/store/*-yosys-[0-9]*/bin/yosys || true)
  [ -n "$YOSYS" ] && export GOLEM_YOSYS="$YOSYS"
fi
if [ -z "${GOLEM_NEXTPNR:-}" ]; then
  NX=$(find_bin nextpnr-xilinx /nix/store/*-nextpnr-*/bin/nextpnr-xilinx || true)
  [ -n "$NX" ] && export GOLEM_NEXTPNR="$NX"
fi
if [ -z "${GOLEM_FASM2FRAMES:-}" ]; then
  F2=$(find_bin fasm2frames /nix/store/*-prjxray-*/bin/fasm2frames || true)
  [ -n "$F2" ] && export GOLEM_FASM2FRAMES="$F2"
fi
if [ -z "${GOLEM_XC7FRAMES2BIT:-}" ]; then
  XB=$(find_bin xc7frames2bit /nix/store/*-prjxray-*/bin/xc7frames2bit || true)
  [ -n "$XB" ] && export GOLEM_XC7FRAMES2BIT="$XB"
fi
if [ -z "${GOLEM_CHIPDB:-}" ] && [ -n "${ARTY_CHIPDB:-}" ]; then
  export GOLEM_CHIPDB="$ARTY_CHIPDB"
fi
if [ -z "${GOLEM_CHIPDB:-}" ]; then
  CD=$(first_file /nix/store/*-arty-chipdb-*/xc7a35tcsg324.bin || true)
  [ -n "$CD" ] && export GOLEM_CHIPDB="$(dirname "$CD")"
fi
if [ -z "${GOLEM_DB:-}" ] && [ -n "${PRJXRAY_DB_DIR:-}" ]; then
  export GOLEM_DB="$PRJXRAY_DB_DIR"
fi
if [ -z "${GOLEM_DB:-}" ]; then
  PY=$(first_file /nix/store/*-source/artix7/xc7a35tcsg324-1/part.yaml || true)
  [ -n "$PY" ] && export GOLEM_DB="$(dirname "$(dirname "$(dirname "$PY")")")"
fi
# fasm2frames' Python modules: prjxray itself, the fasm parser (a Python 3.12
# extension) and their dependencies (pyyaml, simplejson, intervaltree, textx, cython).
# The openXC7 devShell exports PRJXRAY_PYTHON_DIR; the Nix store paths are the fallback.
PRJSHARE="${PRJXRAY_PYTHON_DIR:-}"
if [ -z "$PRJSHARE" ] && [ -n "${GOLEM_FASM2FRAMES:-}" ]; then
  PRJSHARE="$(dirname "$(dirname "$GOLEM_FASM2FRAMES")")/usr/share/python3"
fi
FASMSP=""
FASM=$(first_file /nix/store/*-python3*-fasm/lib/python3*/site-packages/fasm/__init__.py || true)
[ -n "$FASM" ] && FASMSP="$(dirname "$(dirname "$FASM")")"
PYENV=""
for p in /nix/store/*-python3-3.12*-env; do
  if [ -e "$p/lib/python3.12/site-packages/intervaltree/__init__.py" ] && [ -e "$p/lib/python3.12/site-packages/textx/__init__.py" ]; then
    PYENV="$p/lib/python3.12/site-packages"; break
  fi
done
PP=""
[ -n "$PRJSHARE" ] && PP="$PRJSHARE"
[ -n "$FASMSP" ] && PP="${PP:+$PP:}$FASMSP"
[ -n "$PYENV" ] && PP="${PP:+$PP:}$PYENV"
[ -n "$PP" ] && export PYTHONPATH="$PP${PYTHONPATH:+:$PYTHONPATH}"

# ECP5 synthesis. The board netlist is Arty-specific: it instantiates a Xilinx
# PLLE2_BASE and the DDR3 ISERDES2/OSERDES2/IDELAYE2 PHY. `read_verilog -lib` keeps
# those as black boxes, which is enough for synth_ecp5 to size the fabric (LUT4, FF,
# DP16KD, DSP), but not enough for nextpnr-ecp5. A fabric-only netlist (no PLL, no
# PHY; the controller's DFI is the top port) can be placed with --fabric.
ecp5_synth() {
  name=$1
  src=$2
  if "$ECP5_YOSYS" -q -l "build/$name.ecp5.log" -p \
      "read_verilog -lib +/xilinx/cells_xtra.v build/ecp5-blackbox.v; synth_ecp5 -top $name; tee -q -o build/$name.ecp5.stat stat; write_json build/$name.ecp5.json" \
      "$src" 2>> "build/$name.ecp5.log"; then
    echo "ecp5: $name area (synth_ecp5)"
    grep -E 'DP16KD|LUT4|TRELLIS_FF|MULT18X18D|CCU2C|PFUMX|L6MUX21|TRELLIS_DPR16X4' \
      "build/$name.ecp5.stat" | head -20
  else
    echo "ecp5: synth_ecp5 failed for $name; see build/$name.ecp5.log" >&2
    grep -m1 -E '^ERROR:' "build/$name.ecp5.log" >&2 || true
    return 1
  fi
}

ecp5_pnr() {
  name=$1
  if [ -z "${ECP5_NEXTPNR:-}" ]; then
    echo "ecp5: nextpnr-ecp5 not found: place-and-route skipped"
    echo "  missing: nextpnr-ecp5 (prjtrellis). Area above is still valid."
    return 0
  fi
  [ -f "build/$name.ecp5.json" ] || return 0
  if grep -q -E '"type": "(PLLE2_BASE|ISERDESE2|OSERDESE2|IDELAYE2|IDELAYCTRL|BUFG|IBUF|OBUF|IOBUF|IOBUFDS|OBUFDS)"' \
      "build/$name.ecp5.json"; then
    echo "ecp5: $name place-and-route skipped: the board netlist keeps the Arty"
    echo "  PLL/DDR3 PHY as Xilinx cells (black boxes), which nextpnr-ecp5 cannot place."
    echo "  missing: an ECP5 board wrapper (EHXPLLL + DDRDLL/DQSBUFM/IDDRX2), not in this tree."
    echo "  fabric-only netlists: scripts/golem-board.sh ecp5 --fabric FILE [--top NAME] [--device 85k|45k]"
    return 0
  fi
  "$ECP5_NEXTPNR" "--$ECP5_DEVICE" --out-of-context --json "build/$name.ecp5.json" \
    --write "build/$name.$ECP5_DEVICE.post.json" --report "build/$name.$ECP5_DEVICE.report" \
    --log "build/$name.$ECP5_DEVICE.nextpnr.log" --freq 100 --seed "$ECP5_SEED" \
    > "build/$name.$ECP5_DEVICE.nextpnr.out" 2>&1 || true
  grep -E 'DP16KD:|TRELLIS_COMB:|TRELLIS_FF:|MULT18X18D:' \
    "build/$name.$ECP5_DEVICE.nextpnr.log" 2>/dev/null | head -4 || true
  grep -E 'Max frequency for clock' \
    "build/$name.$ECP5_DEVICE.nextpnr.log" 2>/dev/null | tail -1 || true
}

if [ "${1:-}" = "ecp5" ]; then
  shift
  ECP5_FABRIC=""
  ECP5_TOP=""
  ECP5_DEVICE="85k"
  ECP5_SEED="1"
  ECP5_VARIANT=""
  prev=""
  for a in "$@"; do
    case "$prev" in
      --fabric) ECP5_FABRIC="$a" ;;
      --top) ECP5_TOP="$a" ;;
      --device) ECP5_DEVICE="$a" ;;
      --seed) ECP5_SEED="$a" ;;
      --variant) ECP5_VARIANT="$a" ;;
    esac
    case "$a" in
      --fabric|--top|--device|--seed|--variant) prev="$a" ;;
      *) prev="" ;;
    esac
  done
  case "$ECP5_DEVICE" in 85k|45k) ;; *)
    echo "ecp5: --device must be 85k or 45k (got '$ECP5_DEVICE')" >&2; exit 2 ;;
  esac
  case "$ECP5_VARIANT" in
    both) ECP5_VARIANTS="golem golem_mc" ;;
    mc|golem_mc) ECP5_VARIANTS="golem_mc" ;;
    *) ECP5_VARIANTS="golem" ;;
  esac
  [ -d build ] || mkdir -p build
  cat > build/ecp5-blackbox.v <<'BB'
// The Arty board's Xilinx PLL and DDR3 PHY cells. `read_verilog -lib` makes these
// black boxes, so synth_ecp5 can size the ECP5 fabric around them. They are not ECP5
// cells: an ECP5 board needs its own PLL/PHY wrapper.
(* blackbox *) module BUFG(input I, output O); endmodule
(* blackbox *) module IBUF(input I, output O); endmodule
(* blackbox *) module OBUF(input I, output O); endmodule
(* blackbox *) module IOBUF(input I, input T, output O, inout IO); endmodule
BB
  ECP5_YOSYS=$(find_bin yosys /nix/store/*-yosys-[0-9]*/bin/yosys || true)
  if [ -z "$ECP5_YOSYS" ]; then
    echo "ecp5: yosys not found in PATH or /nix/store: synthesis skipped" >&2
    echo "  missing: yosys with the synth_ecp5 pass (0.9 or newer)" >&2
    exit 0
  fi
  ECP5_NEXTPNR=$(find_bin nextpnr-ecp5 /nix/store/*-nextpnr-*/bin/nextpnr-ecp5 || true)
  if [ -n "$ECP5_FABRIC" ]; then
    ECP5_TOP=${ECP5_TOP:-$(basename "$ECP5_FABRIC" .v)}
    ecp5_synth "$ECP5_TOP" "$ECP5_FABRIC"
    ecp5_pnr "$ECP5_TOP"
  else
    .grail/bin/golem gen "$@"
    for v in $ECP5_VARIANTS; do
      [ -f "build/$v.v" ] || continue
      ecp5_synth "$v" "build/$v.v"
      ecp5_pnr "$v"
    done
  fi
  exit 0
fi

exec .grail/bin/golem "$@"
