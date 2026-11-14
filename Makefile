# Host builds of the wiz-rv software: the instruction-set simulator, the C/assembly
# benchmark, and the Doom image. Everything goes through nix-build, so no host or
# cross compiler has to be on PATH.
#
#   make iss          build/iss/bin/iss                    (nix/iss.nix)
#   make bench        build/bench/bench.bin                 (nix/bench.nix)
#   make run-bench    run the benchmark in the ISS          (scripts/iss-bench.sh)
#   make doom         build/doom/doom.bin                   (nix/doom.nix, external source)
#   make doom-smoke   boot Doom to its first frame in the ISS (scripts/iss-doom-smoke.sh)
#   make check        run-bench + doom-smoke (each SKIPs if its fixtures are absent)
#
# Doom is GPL-2.0 and is not vendored: nix/doom.nix fetches doomgeneric at a pinned
# commit. The shareware WAD fixture is wad/doom1.wad (git-ignored).
NIX_BUILD ?= nix-build

.PHONY: all iss bench run-bench doom doom-smoke check

all: iss bench

iss:
	@mkdir -p build
	$(NIX_BUILD) nix/iss.nix -o build/iss

bench:
	@mkdir -p build
	$(NIX_BUILD) nix/bench.nix -o build/bench

run-bench: iss bench
	./scripts/iss-bench.sh

doom:
	@mkdir -p build
	$(NIX_BUILD) nix/doom.nix -o build/doom

doom-smoke: iss doom
	./scripts/iss-doom-smoke.sh

check:
	./scripts/iss-check.sh
