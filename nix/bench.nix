# The freestanding C + assembly benchmark for DDR at 0x40000000: sw/bench/bench.c,
# sw/bench/kernels.S and the machine's own runtime (sw/crt0.S, sw/link.ld,
# sw/syscalls.c).  Produces bench.elf and bench.bin.
#   nix-build nix/bench.nix -o build/bench
# then run it with the host ISS:
#   build/iss/bin/iss build/bench/bench.bin        (scripts/iss-bench.sh)
{ nixpkgs ? <nixpkgs> }:
let
  pkgs = import nixpkgs {};
  rv = import ./riscv.nix { inherit nixpkgs; };
in pkgs.stdenvNoCC.mkDerivation {
  pname = "wiz-rv-bench";
  version = "0";
  src = ../sw;
  nativeBuildInputs = [ rv.gcc ];
  buildPhase = ''
    CC=riscv32-none-elf-gcc
    FLAGS="-march=rv32im -mabi=ilp32 -O2 -I. -ffunction-sections -fdata-sections"
    $CC $FLAGS -nostartfiles -T link.ld -Wl,--gc-sections \
      crt0.S syscalls.c bench/bench.c bench/kernels.S \
      -o bench.elf -lc -lgcc
    riscv32-none-elf-objcopy -O binary bench.elf bench.bin
    riscv32-none-elf-size bench.elf
  '';
  installPhase = ''
    mkdir -p $out
    cp bench.elf bench.bin $out/
  '';
}
