# sw/tone for DDR (as Doom: from 0x4000_0000, loaded by rvload).   nix-build nix/tone.nix
{ nixpkgs ? <nixpkgs> }:
let
  pkgs = import nixpkgs {};
  rv = import ./riscv.nix { inherit nixpkgs; };
in pkgs.stdenvNoCC.mkDerivation {
  pname = "wiz-rv-tone";
  version = "0";
  src = ../sw;
  nativeBuildInputs = [ rv.gcc ];
  buildPhase = ''
    riscv32-none-elf-gcc -march=rv32im -mabi=ilp32 -O2 -I. -nostartfiles -T link.ld -Wl,--gc-sections crt0.S syscalls.c tone/tone.c -o tone.elf -lc -lgcc
    riscv32-none-elf-objcopy -O binary tone.elf tone.bin
  '';
  installPhase = "mkdir -p $out; cp tone.elf tone.bin $out/";
}
