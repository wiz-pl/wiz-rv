#!/bin/sh
# Run the independent-oracle harness.  With --nix, put sail-riscv and Spike on
# PATH from nixpkgs first (exact versions this harness was written against:
# sail-riscv 0.12, spike 1.1.0-unstable-2026-10-20).
#
#   oracle/scripts/run-oracle.sh build
#   oracle/scripts/run-oracle.sh selftest
#   oracle/scripts/run-oracle.sh run
#   oracle/scripts/run-oracle.sh rvfi --pipe --fixture hazard
#   oracle/scripts/run-oracle.sh --nix run
#   oracle/scripts/run-oracle.sh --nix run --backends sail,spike
set -eu
cd "$(dirname "$0")/../.."
if [ "${1:-}" = "--nix" ]; then
  shift
  exec nix shell 'nixpkgs#sail-riscv' 'nixpkgs#spike' -c \
    python3 oracle/scripts/oracle.py "$@"
fi
exec python3 oracle/scripts/oracle.py "$@"
