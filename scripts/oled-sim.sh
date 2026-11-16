#!/bin/sh
# The OLED framebuffer and controller in Icarus Verilog (sim/tb_oled.v): the SSD1331's
# SPI stream over six refreshes, checked against the controller's protocol, and the
# double buffering (a frame drawn into the bank not shown is shown whole). Light: about
# 1.3 M clocks of a small circuit.
#
#   ./scripts/oled-sim.sh         (wiz on PATH, or WIZ=…; iverilog on PATH, else from nixpkgs)
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
WIZ=${WIZ:-wiz}
mkdir -p build
"$WIZ" run -I src app/oledgen.wiz
if command -v iverilog >/dev/null 2>&1; then
  iverilog -g2012 -o build/tb_oled.vvp sim/tb_oled.v build/oled_fb.v
  out=$(vvp -n build/tb_oled.vvp)
else
  out=$(nix shell nixpkgs#iverilog -c sh -c 'iverilog -g2012 -o build/tb_oled.vvp sim/tb_oled.v build/oled_fb.v && vvp -n build/tb_oled.vvp')
fi
printf '%s\n' "$out"
printf '%s\n' "$out" | grep -q '^PASS oled-sim'
