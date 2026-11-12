#!/bin/sh
# (paths of this machine: openFPGALoader, coreutils; the Arty is found by its FTDI serial)
# under the arty lock: load doom_top into SRAM, capture the boot loader's output, and if it
# says "DDR ok", load Doom with rvload and show its console for a while
cd /workspace/wiz-rv
PORT=/dev/serial/by-id/usb-Digilent_Digilent_USB_Device_210319A28B6A-if01-port0
OFL=/nix/store/x366gdgsvjng8yx0bw3prj0cvxfb6cm7-openfpgaloader-1.2.0/bin/openFPGALoader
STTY=/nix/store/cb987zkxvsv0490753ilrvn5yk7ylgxi-coreutils-9.12/bin/stty
ls -la $PORT || exit 1
BD=$(for d in /sys/bus/usb/devices/*; do [ "$(cat $d/serial 2>/dev/null)" = 210319A28B6A ] && echo "$(cat $d/busnum):$(cat $d/devnum)"; done | head -1)
echo "Arty at USB $BD"
$STTY -F $PORT 1000000 raw -echo -ixon -ixoff cs8 -cstopb -parenb clocal min 1 time 0
( timeout 25 cat $PORT > .scratch/boot.out ) &
CAT=$!
$OFL -b arty_a7_35t --busdev-num $BD build/a35t/doom_top.bit 2>&1 | tail -3
wait $CAT
echo "--- boot output:"; od -c .scratch/boot.out | head -10
if grep -q 'DDR ok' .scratch/boot.out; then
  echo "--- DDR ok: rvload"
  timeout ${RVTIME:-240} .grail/bin/rvload $PORT .scratch/doom/doom.bin wad/doom1.wad 2>&1 | tail -c 4000
else
  echo "--- no DDR ok: not loading Doom"
fi
