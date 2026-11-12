# Doom (doomgeneric, GPL-2.0, fetched at a pinned commit) for the wiz-rv Arty machine:
# the platform layer and newlib's system calls in sw/, the RV32IM toolchain of
# riscv.nix. Produces doom.elf and doom.bin (the image for DDR at 0x40000000).
#   nix-build nix/doom.nix
{ nixpkgs ? <nixpkgs>, sound ? true }:
let
  pkgs = import nixpkgs {};
  rv = import ./riscv.nix { inherit nixpkgs; };
  src = pkgs.fetchFromGitHub {
    owner = "ozkl"; repo = "doomgeneric";
    rev = "e257a09527062bfb986b6e5e0780839b6cbd5b71";
    hash = "sha256-A25lWVT5YBFXmMB1EP91ntLvOW9UkeN9vUwopKpJHY4=";
  };
  doomSrc = "dummy am_map doomdef doomstat dstrings d_event d_items d_iwad d_loop d_main d_mode d_net f_finale f_wipe g_game hu_lib hu_stuff info i_cdmus i_endoom i_joystick i_scale i_sound i_system i_timer memio m_argv m_bbox m_cheat m_config m_controls m_fixed m_menu m_misc m_random p_ceilng p_doors p_enemy p_floor p_inter p_lights p_map p_maputl p_mobj p_plats p_pspr p_saveg p_setup p_sight p_spec p_switch p_telept p_tick p_user r_bsp r_data r_draw r_main r_plane r_segs r_sky r_things sha1 sounds statdump st_lib st_stuff s_sound tables v_video wi_stuff w_checksum w_file w_main w_wad z_zone w_file_stdc i_input i_video doomgeneric";
in pkgs.stdenvNoCC.mkDerivation {
  pname = "wiz-rv-doom";
  version = "0";
  inherit src;
  sw = ../sw;
  nativeBuildInputs = [ rv.gcc ];
  buildPhase = ''
    CC=riscv32-none-elf-gcc
    FLAGS="-march=rv32im -mabi=ilp32 -O2 -ffunction-sections -fdata-sections -DDOOMGENERIC_RESX=320 -DDOOMGENERIC_RESY=200 -DNORMALUNIX -D_DEFAULT_SOURCE -DFEATURE_SOUND ${if sound then "" else "-DNO_SOUND_OUT"} -w"
    mkdir obj
    for f in ${doomSrc}; do $CC $FLAGS -Idoomgeneric -I$sw/stub -c doomgeneric/$f.c -o obj/$f.o; done
    $CC $FLAGS -Idoomgeneric -I$sw -c $sw/doomgeneric_wizrv.c -o obj/platform.o
    $CC $FLAGS -I$sw -c $sw/syscalls.c -o obj/syscalls.o
    $CC $FLAGS -Idoomgeneric -I$sw -c $sw/sound_wizrv.c -o obj/sound.o
    $CC $FLAGS -c $sw/crt0.S -o obj/crt0.o
    $CC $FLAGS -nostartfiles -T $sw/link.ld -Wl,--gc-sections -Wl,-Map,doom.map obj/*.o -o doom.elf -lm -lc -lgcc
    riscv32-none-elf-objcopy -O binary doom.elf doom.bin
    riscv32-none-elf-size doom.elf
  '';
  installPhase = ''
    mkdir -p $out
    cp doom.elf doom.bin doom.map $out/
  '';
}
