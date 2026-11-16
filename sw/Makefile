# sw/: RV32IM software for the wiz-rv machine (sw/README.md).
#
# The cross compiler is the RV32IM / ilp32 / newlib toolchain of nix/riscv.nix:
#
#   export PATH=$(nix-build ../nix/riscv.nix -A gcc --no-out-link)/bin:$PATH
#   make -C sw all
#
# `make doom` uses nix/doom.nix instead (doomgeneric is fetched at a pinned commit;
# the derivation is cached):   make -C sw doom
#
# Targets: bench (the C benchmark, into DDR), boot (the lockstep's small payload),
# ctest (into the on-chip RAM), tone (into DDR), doom, iss (the host
# instruction-set simulator), clean. The generated Wiz image src/Rv/CBoot.wiz is
# rebuilt by `make wiz` (needs .grail/bin/bin2wiz: `grail build bin2wiz`).

TOP     := $(abspath $(CURDIR)/..)
B       := $(TOP)/build/sw
CC      = riscv32-none-elf-gcc
OBJCOPY = riscv32-none-elf-objcopy
SIZE    = riscv32-none-elf-size
HOSTCC  ?= cc
GRAIL   ?= grail

CFLAGS  := -march=rv32im -mabi=ilp32 -O2 -ffunction-sections -fdata-sections
LDFLAGS := -nostartfiles -Wl,--gc-sections

.PHONY: all bench boot ctest tone doom iss mustest wiz clean

all: bench boot ctest tone

$(B):
	mkdir -p $@

# The benchmark: sw/ctest/bench.c at 0x40000000 (sw/link.ld, sw/ctest/benchcrt0.S),
# for sw/iss and the board (load it with rvload). Freestanding: no newlib.
bench: | $(B)
	$(CC) $(CFLAGS) -nostdlib -T link.ld ctest/benchcrt0.S ctest/bench.c -o $(B)/bench.elf -lgcc
	$(OBJCOPY) -O binary $(B)/bench.elf $(B)/bench.bin
	$(SIZE) $(B)/bench.elf

# The boot-flow payload for the lockstep: sw/ctest/boothello.c at 0x40000000, small
# enough that the boot loader can carry it and the kernel can evaluate every
# instruction of the load (bench/boot.wiz).
boot: | $(B)
	$(CC) $(CFLAGS) -nostdlib -T link.ld ctest/benchcrt0.S ctest/boothello.c -o $(B)/boothello.elf -lgcc
	$(OBJCOPY) -O binary $(B)/boothello.elf $(B)/boothello.bin
	$(SIZE) $(B)/boothello.elf

# The same C code as tests/lockstep.wiz's compiled C case: in the on-chip RAM at 0.
ctest: | $(B)
	$(CC) $(CFLAGS) $(LDFLAGS) -T ctest/link.ld ctest/crt0.S ctest/ctest.c -o $(B)/ctest.elf -lc -lgcc
	$(OBJCOPY) -O binary $(B)/ctest.elf $(B)/ctest.bin
	$(SIZE) $(B)/ctest.elf

tone: | $(B)
	$(CC) $(CFLAGS) -I. $(LDFLAGS) -T link.ld crt0.S syscalls.c tone/tone.c -o $(B)/tone.elf -lc -lgcc
	$(OBJCOPY) -O binary $(B)/tone.elf $(B)/tone.bin
	$(SIZE) $(B)/tone.elf

# doomgeneric for the machine: doom.elf and doom.bin at 0x40000000 (nix/doom.nix)
doom:
	nix-build ../nix/doom.nix --no-out-link

# the host instruction-set simulator (sw/iss/iss.c) and the music renderer
iss:
	$(HOSTCC) -O2 -o $(B)/iss iss/iss.c
	$(HOSTCC) -O2 -o $(B)/mustest iss/mustest.c

# Encode build/sw/boothello.bin as a Wiz string (CBoot.hex) for bench/boot.wiz
wiz: boot
	cd $(TOP) && .grail/bin/bin2wiz build/sw/boothello.bin src/Rv/CBoot.wiz CBoot.hex

clean:
	rm -rf $(B)
