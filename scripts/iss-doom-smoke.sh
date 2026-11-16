#!/bin/sh
# Doom boot smoke test on the host ISS: load doom.bin at 0x40000000 and the shareware
# WAD at 0x48000000 (exactly the memory rvload leaves on the board), run until the
# first frame has been written to the 96x64 OLED framebuffer, and check that the
# banner appeared, a frame was produced, and the ISS stopped cleanly.
#
#   make doom                          # nix-build nix/doom.nix -o build/doom
#   ./scripts/iss-doom-smoke.sh
#   WAD=/path/to/doom1.wad DOOM=build/doom/doom.bin ./scripts/iss-doom-smoke.sh
#
# Doom is external: nix/doom.nix fetches doomgeneric at a pinned commit and builds
# sw/doomgeneric_wizrv.c against it. Neither the Doom source nor doom.bin is in the
# repository, and wad/ is git-ignored. If a fixture is absent this test SKIPs (and
# exits 0); it never downloads anything.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ISS=${ISS:-$root/build/iss/bin/iss}
DOOM=${DOOM:-$root/build/doom/doom.bin}
WAD=${WAD:-$root/wad/doom1.wad}
MAP=${MAP:-$root/build/doom/doom.map}

if [ ! -x "$ISS" ]; then
  echo "SKIP iss-doom-smoke: no ISS at $ISS (run: make iss)"
  exit 0
fi
if [ ! -f "$DOOM" ]; then
  echo "SKIP iss-doom-smoke: no doom.bin at $DOOM (run: make doom)"
  exit 0
fi
if [ ! -f "$WAD" ]; then
  echo "SKIP iss-doom-smoke: no WAD at $WAD (put the shareware doom1.wad in wad/)"
  exit 0
fi

# The layout rvload produces (sw/hw.h): doom.bin at 0x40000000 with the heap up to
# 0x47f00000, the WAD's length at 0x47fffff0, the WAD at 0x48000000 in 256 MB DDR.
# The ISS has the same map; refuse an image pair that cannot fit.
doom_size=$(wc -c < "$DOOM")
wad_size=$(wc -c < "$WAD")
if [ $((0x40000000 + doom_size)) -gt $((0x47f00000)) ]; then
  echo "FAIL iss-doom-smoke: doom.bin ($doom_size bytes) runs into HEAP_END" >&2
  exit 1
fi
if [ $((0x48000000 + wad_size)) -gt $((0x50000000)) ]; then
  echo "FAIL iss-doom-smoke: the WAD ($wad_size bytes) does not fit in DDR" >&2
  exit 1
fi
echo "iss-doom-smoke: doom.bin $doom_size bytes at 0x40000000, WAD $wad_size bytes at 0x48000000"

frames=$(mktemp -d) || exit 1
out=$(mktemp) || { rm -rf "$frames"; exit 1; }
err=$(mktemp) || { rm -rf "$frames" "$out"; exit 1; }
trap 'rm -rf "$frames" "$out" "$err"' EXIT HUP INT TERM

# DG_ScreenBuffer is a pointer; -screen wants the address of that pointer, which the
# linker map has. Without the map, the 96x64 frame is still checked.
screen=
if [ -f "$MAP" ]; then
  screen=$(awk '$2 == "DG_ScreenBuffer" { print $1; exit }' "$MAP")
fi
if [ -n "$screen" ]; then
  set -- -screen "$screen"
else
  set --
fi

# -maxframes 1 stops at the first completed frame; -n is only a safety limit.
if ! "$ISS" "$DOOM" "$WAD" -maxframes 1 -n 100000000 -frames "$frames" "$@" \
     > "$out" 2> "$err"; then
  cat "$out"
  cat "$err" >&2
  echo "FAIL iss-doom-smoke: the ISS returned nonzero" >&2
  exit 1
fi

cat "$out"
cat "$err" >&2

if ! grep -q 'DOOM Shareware' "$out"; then
  echo "FAIL iss-doom-smoke: the Doom banner did not appear" >&2
  exit 1
fi
if ! grep -q '1 frames' "$err"; then
  echo "FAIL iss-doom-smoke: the ISS did not report one frame" >&2
  exit 1
fi
if [ ! -s "$frames/frame00000.ppm" ]; then
  echo "FAIL iss-doom-smoke: no 96x64 frame was written" >&2
  exit 1
fi
if [ -n "$screen" ] && [ ! -s "$frames/full00000.ppm" ]; then
  echo "FAIL iss-doom-smoke: no full 320x200 frame was written (DG_ScreenBuffer=$screen)" >&2
  exit 1
fi
echo "PASS iss-doom-smoke${screen:+ (96x64 and 320x200 frames)}"
