# The host instruction-set simulator of the wiz-rv machine (sw/iss/iss.c).
#   nix-build nix/iss.nix -o build/iss
# gives build/iss/bin/iss.  The ISS is a C program with no dependencies beyond libc.
{ nixpkgs ? <nixpkgs> }:
let
  pkgs = import nixpkgs {};
in pkgs.stdenv.mkDerivation {
  pname = "wiz-rv-iss";
  version = "0";
  src = ../sw/iss;
  nativeBuildInputs = [ pkgs.gcc ];
  buildPhase = ''
    $CC -O2 -Wall -Wextra -o iss iss.c
  '';
  installPhase = ''
    mkdir -p $out/bin
    cp iss $out/bin/
  '';
}
