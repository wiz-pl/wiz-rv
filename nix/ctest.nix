# sw/ctest for the on-chip RAM: ctest.bin (from address 0).   nix-build nix/ctest.nix
{ nixpkgs ? <nixpkgs> }:
let
  pkgs = import nixpkgs {};
  rv = import ./riscv.nix { inherit nixpkgs; };
in pkgs.stdenvNoCC.mkDerivation {
  pname = "wiz-rv-ctest";
  version = "0";
  src = ../sw/ctest;
  nativeBuildInputs = [ rv.gcc ];
  buildPhase = ''
    riscv32-none-elf-gcc -march=rv32im -mabi=ilp32 -O2 -nostartfiles -T link.ld -Wl,--gc-sections crt0.S ctest.c -o ctest.elf -lc -lgcc
    riscv32-none-elf-objcopy -O binary ctest.elf ctest.bin
    riscv32-none-elf-size ctest.elf
  '';
  installPhase = "mkdir -p $out; cp ctest.elf ctest.bin $out/";
}
