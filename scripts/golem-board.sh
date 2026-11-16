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
#   scripts/golem-board.sh flash [BIT]        print the load command; only runs with
#                                             GOLEM_FLASH=1 (the brief does not
#                                             authorise hardware)
#
# Options after the command: --boot rom|loader (default loader, Prog.boot), --variant
# golem|mc|four|four_nol1|both (default golem; mc is golemMc at 50 MHz effective;
# four is four multi-cycle harts with per-hart L1s, four_nol1 the same without them).
# `four` is the A7-35T multicore target: 4 harts, shared UART/OLED/timer/mailbox and
# DDR. Its harts are enabled every other cycle, so its XDC uses a 20 ns (50 MHz) target
# and `timing` checks 50 MHz for it; the bus/DDR stay at 100 MHz. See DESIGN.md,
# "Four harts" and "Timing: the harts are a 50 MHz (20 ns) target".
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

exec .grail/bin/golem "$@"
