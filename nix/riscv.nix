# The cross toolchain for the core: RV32IM, soft float (ilp32), newlib (strict alignment). nixpkgs's
# pkgsCross.riscv32-embedded is rv32gc/ilp32d, which the core cannot run, so this is
# the same cross system with the core's architecture.
#   nix-build nix/riscv.nix -A gcc
{ nixpkgs ? <nixpkgs> }:
let
  pkgs = import nixpkgs {
    crossSystem = {
      config = "riscv32-none-elf";
      libc = "newlib";
      gcc = { arch = "rv32im"; abi = "ilp32"; };
    };
    # newlib's string functions assume misaligned word accesses work (gcc's default
    # tuning says they are merely slow); the core traps on them: build it for strict
    # alignment
    crossOverlays = [ (final: prev: {
      newlib = prev.newlib.overrideAttrs (o: {
        preBuild = (o.preBuild or "") + ''
          makeFlagsArray+=("CFLAGS_FOR_TARGET=-g -O2 -mstrict-align")
        '';
      });
    }) ];
  };
in {
  gcc = pkgs.buildPackages.gcc;
  binutils = pkgs.buildPackages.binutils;
  newlib = pkgs.newlib;
}
