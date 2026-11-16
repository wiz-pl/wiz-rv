#!/bin/sh
# One command for the headless RV/Doom software check:
#
#   ./scripts/iss-check.sh
#
# Builds the host ISS, the C/assembly benchmark and the Doom image with nix-build
# (no compiler on PATH, no hardware), then runs the benchmark and the Doom first-frame
# smoke test. The Doom test SKIPs if wad/doom1.wad is absent; the benchmark always
# runs. `make check` is the same thing.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
mkdir -p build

nix-build nix/iss.nix -o build/iss
nix-build nix/bench.nix -o build/bench
nix-build nix/doom.nix -o build/doom

./scripts/iss-bench.sh
./scripts/iss-doom-smoke.sh
