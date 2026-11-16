# sw/ — software for the wiz-rv machine

The RV32IM bare-metal software: the boot loader's payloads (compiled C), Doom, the
sound and music modules, and two host tools (an instruction-set simulator and a
music renderer). The hardware side is in `src/Rv/` (`README.md`, "Doom"); the
memory map below is the contract between the two, and the boot flow is checked end
to end in the executable lockstep (`bench/boot.wiz`).

```
sw/hw.h                 the machine as C sees it: the memory map, I/O registers, hw_cycles()
sw/crt0.S               entry for a program in DDR: the stack, .bss, main(0, 0), exit
sw/link.ld              DDR at 0x40000000, stack top 0x44000000
sw/syscalls.c           newlib: the console on the UART, the heap, the WAD as the one file
sw/doomgeneric_wizrv.c  doomgeneric's platform: 320x200 -> 96x64, ticks, UART keys
sw/sound_wizrv.c        effects and music mixed into the sound FIFO
sw/mus_synth.c          the MUS music synthesizer (also compiled into sw/iss/mustest.c)
sw/tone/tone.c          a sound-path test: a 441 Hz triangle
sw/ctest/ctest.c        the C lockstep test: newlib's string functions, M, prints
sw/ctest/crt0.S         its entry for the on-chip RAM (stack at 0x3ff0)
sw/ctest/link.ld        and its linker script (at 0)
sw/ctest/bench.c        the benchmark (freestanding): map, strings, sort, M, CRC
sw/ctest/boothello.c    the boot flow's small C payload for the lockstep ("c ok")
sw/ctest/benchcrt0.S    the entry for both DDR payloads (stack 0x44000000, .bss, main, ebreak)
sw/iss/iss.c            a host RV32IM simulator of the machine (frames as PPM, sound as WAV)
sw/iss/mustest.c        renders a MUS lump to a WAV on the host
sw/Makefile             the builds below
```

## Toolchain

RV32IM, `ilp32`, soft float, newlib. `nix/riscv.nix` is the cross toolchain: it is
nixpkgs's `riscv32-none-elf` with `-march=rv32im -mabi=ilp32` (nixpkgs's
`pkgsCross.riscv32-embedded` is rv32gc/ilp32d, which this core cannot run) and
newlib rebuilt with `-mstrict-align`, because newlib's string functions assume
misaligned word accesses work and the core traps on them.

```sh
nix-build nix/riscv.nix -A gcc --no-out-link      # prints the toolchain (cached)
export PATH=$(nix-build nix/riscv.nix -A gcc --no-out-link)/bin:$PATH
make -C sw all                                     # bench, boot, ctest, tone
make -C sw doom                                    # nix/doom.nix (doomgeneric, pinned)
make -C sw iss                                     # the host simulator, build/sw/iss
```

`make -C sw all` writes `build/sw/bench.{elf,bin}` (the benchmark),
`build/sw/boothello.{elf,bin}` (the lockstep's small boot payload),
`build/sw/ctest.bin` (the on-chip C test) and `build/sw/tone.bin` (a DDR program).
A host compiler and `make` (nix: `nix-shell -p gnumake gcc`) are needed for `iss`;
the cross builds need only the toolchain above.

The Wiz side is built by grail (the package's `grail.wiz`):

```sh
grail build bin2wiz                 # the binary-to-Wiz-string tool
make -C sw wiz                      # build/sw/boothello.bin -> src/Rv/CBoot.wiz
wiz check -I src bench/boot.wiz       # the boot flow in the lockstep
```

## Memory map

The same numbers are in `sw/hw.h` (with `_Static_assert`s that check the regions do
not overlap) and in `src/Rv/Doom.wiz`. Changing one is a change to the SoC: update
all three. The golem SoC (`src/Rv/Golem/Map.wiz`, `sw/golem.h`) uses this map and
adds one register, a UART status at `0x80000004` (bit 0 transmitter idle, bit 1 a
byte is waiting); the Doom machine leaves that offset returning zero.

| address | size | what |
|---|---|---|
| `0x00000000` | 16 KB | on-chip RAM (block RAM): the boot loader, `Prog.boot`; in the board top it is initialised with the assembled program |
| `0x40000000` | 256 MB | DDR3 through the 8 KB write-back cache; DDR programs (Doom, bench, tone) are loaded here and entered at `0x40000000` |
| `0x47f00000` | — | the end of the heap (`HEAP_END` in `hw.h`): `malloc` grows from `_end` to here |
| `0x47fffff0` | 16 B | the WAD's length, a little-endian `u32` (the boot loader's `rvload` writes it) |
| `0x48000000` | 4 MB | the WAD (`doom1.wad`, shareware; `wad/` is not in the repository) |
| `0x80000000` | page | I/O registers (below) |
| `0x81000000` | 12 KB | the framebuffer, bank 0: 96 × 64 RGB565 halfwords, row-major |
| `0x81004000` | 12 KB | bank 1 (`FB_CTRL` picks the bank shown; src/Rv/OledFb.wiz) |

The I/O registers (`sw/hw.h`):

| offset | access | what |
|---|---|---|
| `0x00` | read / write | the UART: read the next received byte, or -1; write sends a byte (1 Mbaud, 8N1) |
| `0x10`, `0x14` | read | a free-running cycle counter, low and high, at 50 MHz (the core's rate: 100 MHz at half rate) |
| `0x30` | write | one 8-bit unsigned sound sample into the 4096-entry FIFO |
| `0x34` | read | free places in the sound FIFO; the FIFO is played at 11025 Hz as PWM on JB1 |
| `0x40` | read | the DDR controller's status: bit 0 calibrated, bit 1 failed |
| `0x50` … `0x7c` | read | performance counters: instructions, bus cycles, load cycles, long cycles, refetches, cache hits/misses, framebuffer writes, OLED refreshes, odd refreshes, checksum, sound underruns |
| `0x80` | read | the OLED controller's pins and program counter (debug) |
| `0x84` | read/write | `FB_CTRL`: write the bank to show from the next refresh; read `0xDB000000` + 2 × that + the bank shown |

The trap model: a load or store is an I/O access when bit 31 of its address is set
(the core does not decode the map; `src/Rv/Pipe.wiz` sends `ioa` to the machine,
which decodes it in `src/Rv/Doom.wiz`). In the executable specification
(`src/Rv/Isa.wiz`) every such load returns the next input byte, or -1: that is why
the lockstep tests feed the boot loader a `1` for its DDR-status read.

## Boot flow and entry convention

1. **Reset.** `PC = 0`, `x0 = 0`, the other registers 0, the on-chip RAM holding the
   boot loader (`Prog.boot`, assembled by `src/Rv/Asm.wiz`). The boot loader sets
   `x15 = 0x80000000`, prints `wiz-rv boot\n`, and polls `0x80000040` until the
   DDR controller reports calibrated or failed, then prints `DDR ok\n` or
   `DDR fail\n`.
2. **Load.** It reads records from the UART (`rvload`, `app/rvload.wiz`):
   ```
   'L' addr len bytes…   store len bytes at addr (addr, len: 4 bytes each, LE); answers '.'
   'G' addr              answers '!' and jumps to addr
   ```
   `rvload PORT doom.bin doom1.wad` sends the program at `0x40000000`, the WAD's
   length at `0x47fffff0` and the WAD at `0x48000000`, then `G 0x40000000`.
3. **Entry.** A DDR program is entered at its first byte, `0x40000000`, with no
   arguments. `sw/crt0.S` sets `sp = 0x44000000`, zeroes `.bss`, calls
   `main(0, 0)`, and `exit` ends in `ebreak` with `main`'s result in `a0` (trap 2
   stops the machine; a lockstep run compares the stop). Programs may be linked
   anywhere in DDR: RISC-V's `auipc`/`jalr` make the C code position-independent
   within ±2 GB, which is how the same C sources are linked at 0 (the lockstep's
   on-chip test) and at `0x40000000` (the DDR programs).
4. **Observation.** The output port is a store to any address with bit 31 set
   (`OUT` in the C tests): its low byte goes to the UART transmitter. The machine
   stops on `ebreak`, `ecall`, an illegal instruction, a misaligned load, store or
   jump, with the trap code in `src/Rv/Isa.wiz`.

The boot loader is also loaded at 0 for the *lockstep*: `bench/boot.wiz` gives it
the DDR-status byte and a whole `Boot.session` (a load record with
`src/Rv/CBoot.wiz` and a `G`) as its input, and runs it against the specification
instruction by instruction on the 16 KB machine (RV32IM, 32 registers). The
payload it carries there is the tiny `sw/ctest/boothello.c` ("c ok"): the kernel
evaluates every instruction of the load, so the larger `bench.c` is measured in
`sw/iss` and on the board instead.

## Running

* **Board** (Arty A7-35T): `scripts/arty-load.sh` loads the bitstream and then
  `rvload PORT build/sw/doom.bin wad/doom1.wad`. The console is the UART at
  1 Mbaud. BTN0 resets the core; LD5–LD7 show a trap code.
* **Host simulator**: `build/sw/iss doom.bin doom1.wad -maxframes 3` runs Doom in
  the machine model; frames go to PPM with `-frames DIR`, sound to a WAV with
  `-wav FILE`, keys from `-keys "1000:w,1500:f"`. It prints a frame line per
  refresh and, at the end, instructions, cycles, frames and average fps. The
  program's own `perf:` lines read the performance counters, which the simulator
  implements (no caches: every DDR access is one count; cycles follow the
  multi-cycle core's model, not the 100 MHz pipeline's).
* **Lockstep**: `wiz check -I src bench/boot.wiz` (boot loader + the small C payload;
  it is outside `tests/` because grail's per-test timeout is 300 s and a cold check of
  the lockstep takes about six minutes; it is seconds when nothing has changed),
  `grail test lockstep` (every ISA instruction, the traps, RV32E, the boot loader,
  compiled C) and `grail test plockstep` (the pipelined core at retirement). These
  evaluate in the kernel and take minutes (FINDINGS.md S1); `tests/lockstep.expected`
  and the line printed by `bench/boot.wiz` record the instruction and cycle counts.

## Benchmarks and payloads

`sw/ctest/bench.c` is the benchmark: built for DDR at `0x40000000`, it checks the
on-chip RAM, DDR at `0x41000000` and the top of DDR, string operations on a
misaligned buffer, a 16-word sort, `div`/`rem` and a 64-bit product, and a CRC-32,
and prints

```
bench: map ok, str ok, sort ok, m ok, crc ded4d69b
```

It reads no timer, so the same image runs in the ISS and on the board.
The lockstep run has the measured boot cost: the boot loader, the UART load
of the 138-byte payload and the program's `c ok` are 1595 instructions and 4324
cycles in the lockstep (the boot banner, `DDR ok`, the `.`/`!` answers and the
payload's line are the output). In `sw/iss` the benchmark itself is 4009
instructions and 26528 cycles (the ISS's multi-cycle model).

Payload sizes at `-O2` (RV32IM):

| image | bytes | where |
|---|---|---|
| `build/sw/boothello.bin` | 138 | DDR, the lockstep's boot payload (`bench/boot.wiz`) |
| `build/sw/bench.bin` | 1389 (+96 `.bss`) | DDR, the benchmark (`sw/iss`, board) |
| `build/sw/ctest.bin` | 3099 (+64 `.bss`) | on-chip RAM (`0`) |
| `build/sw/tone.bin` | 19216 (text 17850, data 1360, bss 408) | DDR |
| `doom.bin` (`nix/doom.nix`) | 561880 (text 500300, data 61576, bss 241348) | DDR, WAD at `0x48000000` |

Doom in the host simulator (shareware `doom1.wad`, the demo loop;
`build/sw/iss doom.bin doom1.wad -maxframes 3`): the first frame is at
18.9 M instructions and 54.8 M cycles (1.10 s at 50 MHz; Doom's start-up), then
about 3.4 M instructions and 11 M cycles a frame (4.5 fps) early on, and about
4.7–5.4 M instructions a frame (2.6–2.9 fps) once the demo is busy: 2.5 G
instructions reach 532 frames in 183.5 s of simulated time (2.90 fps average),
CPI ≈3.7 in the ISS's multi-cycle cycle model. The simulator does not model the
caches, and its cycles are the multi-cycle core's. On the board (100 MHz
pipelined core) the same loop is about 15 fps and 278 M instructions per 500 M
cycles (CPI ≈1.8).

## The next software blockers

* **The framebuffer path is the platform's cost**: `DG_DrawFrame` writes 6144
  halfwords through the I/O port (about 3.27 M framebuffer writes for 532 frames);
  the machine takes one halfword store each, and Doom's software renderer
  dominates the rest. A 32-bit store writing two pixels (and a `wstrb`-aware
  framebuffer write in `src/Rv/Doom.wiz`) would halve the stores.
* **Sound underruns at a low frame rate**: the FIFO holds 4096 samples (0.37 s)
  and the platform fills it once a frame, so below about 2.7 fps it empties — 112
  ticks in a 5 s window in the ISS. Filling it from the game-tic loop (or a larger
  FIFO) would keep the piezo fed.
* **Caches are not modelled in `sw/iss`**, so its cycles understate the pipelined
  machine on DDR-heavy code; the board's counters are the reference for cache
  behaviour (the `perf:` line prints hits and misses there).
* **Input**: the UART holds one byte and `DG_GetKey` is called once a frame, so
  fast typing is still lossy even with the key queue; a receive FIFO in the
  machine (or polling in `DG_GetKey`'s caller) would fix the hardware side.
* **The lockstep's I/O model is the UART's alone**, so a program that reads the
  cycle counter or a performance counter cannot run in it (the boot payload
  therefore avoids timers, and the benchmark runs in `sw/iss` instead).
