#!/bin/sh
# Check the multi-cycle core's single-instruction proofs (proofs/CoreProofs.wiz).
# These are the two-cycle `rfl` claims; they are opt-in because the C extension's
# expansion makes the kernel's reduction of the 32-bit path exceed a 4 GiB cap
# (FINDINGS.md, H12). WIZ: the command that runs wiz (default: wiz).
cd "$(dirname "$0")/.."
WIZ=${WIZ:-wiz}
exec $WIZ check -I src -I lib proofs/CoreProofs.wiz
