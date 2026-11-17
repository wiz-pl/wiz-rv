#!/bin/sh
# The cache's area and timing on the Arty A7-35T and A7-100T: gen (the Wiz driver),
# then yosys synthesis and nextpnr-xilinx for both parts. The tools are found on PATH or
# in the Nix store (as scripts/golem-board.sh does).
#
#   scripts/cache-area.sh gen
#   scripts/cache-area.sh synth      yosys, utilisation in build/NAME.stat
#   scripts/cache-area.sh soc        the full golem (with the cache): yosys, then
#                                    nextpnr-xilinx for a35t and a100t, 100 MHz
#   scripts/cache-area.sh all        gen, synth, soc
#   scripts/cache-area.sh report     the last run's summary
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

YOSYS=${CACHE_YOSYS:-$(find_bin yosys /nix/store/*-yosys-*/bin/yosys || true)}
NEXTPNR=${CACHE_NEXTPNR:-$(find_bin nextpnr-xilinx /nix/store/*-nextpnr-*/bin/nextpnr-xilinx || true)}
CHIPDB=${CACHE_CHIPDB:-}
if [ -z "$CHIPDB" ]; then
  CD=$(first_file /nix/store/*-arty-chipdb-*/xc7a35tcsg324.bin || true)
  [ -n "$CD" ] && CHIPDB="$(dirname "$CD")"
fi

designs="cache_wb cache_wt cache_wb_na"
parts="a35t a100t"

gen() {
  [ -x .grail/bin/cache ] || { echo "no .grail/bin/cache: run \`grail build\` first" >&2; exit 1; }
  .grail/bin/cache gen
}

synth() {
  [ -n "$YOSYS" ] || { echo "yosys not found" >&2; exit 1; }
  for d in $designs; do
    echo "== $d: yosys synth_xilinx"
    "$YOSYS" -q -l "build/$d.yosys.log" -p "synth_xilinx -flatten -abc9 -arch xc7 -top $d; tee -q -o build/$d.stat stat; write_json build/$d.json" "build/$d.v"
    grep -E "Number of cells|LUT[1-6]|FDRE|FDSE|RAMB36|RAMB18|RAM32M|DSP48E1|Estimated number of LCs" "build/$d.stat" || true
  done
}

soc() {
  [ -x .grail/bin/golem ] || { echo "no .grail/bin/golem: run `grail build` first" >&2; exit 1; }
  [ -n "$YOSYS" ] || { echo "yosys not found" >&2; exit 1; }
  [ -n "$NEXTPNR" ] || { echo "nextpnr-xilinx not found" >&2; exit 1; }
  [ -n "$CHIPDB" ] || { echo "no chipdb directory (set CACHE_CHIPDB)" >&2; exit 1; }
  .grail/bin/golem gen
  echo "== golem: yosys synth_xilinx"
  "$YOSYS" -q -l build/golem.yosys.log -p "synth_xilinx -flatten -abc9 -arch xc7 -top golem; tee -q -o build/golem.stat stat; write_json build/golem.json" build/golem.v
  grep -E "LUT[1-6]|FDRE|FDSE|RAMB36|RAMB18|RAM32M|DSP48E1|Estimated number of LCs" build/golem.stat || true
  for p in $parts; do
    case "$p" in
      a35t) db="$CHIPDB/xc7a35tcsg324.bin" ;;
      a100t) db="$CHIPDB/xc7a100tcsg324.bin" ;;
    esac
    mkdir -p "build/$p"
    echo "== golem on $p"
    "$NEXTPNR" --chipdb "$db" --xdc build/golem.xdc --json build/golem.json \
      --fasm "build/$p/golem.fasm" --log "build/$p/golem.nextpnr.log" -q
    grep "Max frequency for clock" "build/$p/golem.nextpnr.log" | tail -1 || true
  done
}

report() {
  for d in $designs; do
    echo "== $d (cache only, yosys)"
    [ -e "build/$d.stat" ] && grep -E "LUT[1-6]|FDRE|FDSE|RAMB36|RAMB18|Estimated number of LCs" "build/$d.stat" || true
  done
  echo "== golem (with the cache)"
  [ -e build/golem.stat ] && grep -E "LUT[1-6]|FDRE|FDSE|RAMB36|RAMB18|RAM32M|DSP48E1|Estimated number of LCs" build/golem.stat || true
  for p in $parts; do
    [ -e "build/$p/golem.nextpnr.log" ] && echo "$p: $(grep 'Max frequency for clock' "build/$p/golem.nextpnr.log" | tail -1)" || true
  done
}

case "${1:-}" in
  gen) gen ;;
  synth) gen; synth ;;
  soc) soc ;;
  all) gen; synth; soc ;;
  report) report ;;
  *) echo "usage: cache-area.sh gen | synth | soc | all | report" >&2; exit 1 ;;
esac
