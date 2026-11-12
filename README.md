# wiz-rv

RISC-V cores written in [Wiz](https://github.com/wiz-pl/wiz)'s hardware description
library, built with grail (Wiz's build tool), checked in lockstep against an executable
ISA specification written in Wiz, and placed and routed for small FPGAs.

It exists to use Wiz's HDL for something the size of a processor and to write down what
that was like: see [FINDINGS.md](FINDINGS.md).

```
src/Rv/Isa.wiz       the ISA: RV32I / RV32E as a pure step function on an architectural state
src/Rv/Asm.wiz       a small assembler (mnemonics as functions, labels, two passes)
src/Rv/Progs.wiz     test programs (riscv-tests style: they print results, then ebreak)
src/Rv/Core.wiz      the multi-cycle core, parameterised by register count and memory size
src/Rv/Lockstep.wiz  the core against the specification, cycle by cycle / instruction by instruction
src/Rv/Pipe.wiz      the 5-stage pipelined core (the Doom machine's, at 100 MHz)
src/Rv/PLockstep.wiz the pipelined core against the specification, instruction by instruction at retirement
app/rv.wiz           the flow driver: Verilog, yosys, nextpnr
tests/*.wiz          grail tests
```

## The machine

RV32I (32 registers) or RV32E (16), the unprivileged base ISA v2.1 without CSRs:
ECALL, EBREAK, an illegal instruction, a misaligned load, store or jump target stop the
machine with a trap code (`src/Rv/Isa.wiz` has the list) instead of trapping; FENCE is a
no-op. Memory is 2^n bytes from address 0 (addresses wrap); the program image is its
initial contents and execution starts at 0. A store to an address with bit 31 set
writes its low byte to the output port instead.

## The core

Multi-cycle, a 32-bit datapath, everything big in block RAM: the memory as four byte
lanes (so byte and halfword stores are single writes), the register file twice (two
read ports). Two cycles per instruction (decode, execute), three for loads and stores,
three plus the shift amount for shifts (a one-place-per-cycle shifter in place of a
barrel shifter). `src/Rv/Core.wiz` has the phase diagram.

Optionally (`mx`) the M extension: a one-cycle 64-bit multiplier (DSP blocks on a
Xilinx part) and a 32-cycle restoring divider.

## The pipelined core

`src/Rv/Pipe.wiz`: five stages, in order, at the full clock rate (no clock enable):

* **F**: the next fetch address goes to block RAM: the on-chip RAM's fetch copy and the
  I-cache (16 KB, 16-byte lines, direct-mapped).
* **D**: the I-cache hit check and the decode. The register file is two RAM32M copies,
  read asynchronously, with a bypass of R's write.
* **E**: the ALU and the barrel shifter. Branches are predicted not taken and resolved
  here; a taken branch or jump is registered and redirects the fetch a cycle later, so
  it costs 2 cycles. Also here: the traps, and the four 16 × 16 partial products of the
  multiplier (4 DSP48E1). The divider is iterative (33 cycles; E waits). The D-side
  memories are read at the address.
* **M**: the load data comes from the on-chip RAM's data copy, the D-cache (16 KB,
  write-through, no allocation on a store) or I/O. Also here: the store merge and the
  product's sum.
* **R**: the register file is written. Any instruction that cannot complete kills
  everything younger here (a trap, an I- or D-cache miss, which is replayed after the
  fill), so traps are precise.

Forwarding goes from M and R into E. A load or product that E needs costs one cycle. The
forwarding selects and that interlock are decided a cycle ahead into E's registers.

Every block RAM and LUT-RAM write port is driven from registers: the on-chip RAM, both
caches, their tags and the register file. A store's write is done the cycle after it
leaves M, and loads forward from that write and from the one before it. DDR stores go
through a one-entry store buffer.

A store that may hit fetched instructions restarts the fetch after it: any on-chip
store, or a DDR store to a line that is in the I-cache, which is then invalidated. So
self-modifying code behaves as the specification says.

The ISA (src/Rv/Isa.wiz) and the bus to DDR are unchanged.

Lockstep (`tests/plockstep.wiz`, src/Rv/PLockstep.wiz): at every retirement the PC and
every register (both copies) must be the specification's. At the end come the trap, the
output, both copies of the on-chip RAM and DDR. All the programs of tests/lockstep.wiz
agree, with the same output as the multi-cycle core, including the boot loader loading
over the UART into DDR and the compiled C test (1060 instructions).

Cycle counts against the multi-cycle core: alu 66 vs 149 cycles (62 instructions), sort
600 vs 705, sum 59 vs 76. Every on-chip store restarts the fetch, which costs sort and
mem; DDR code does not pay this.

## Results

| design | part | logic | block RAM | Fmax (nextpnr) |
|---|---|---|---|---|
| RV32E, 2 KB, LEDs (`rv32e_hx1k`) | iCE40-HX1K (tq144, iCEstick pins) | 1036 / 1280 LCs (80 %) | 8 / 16 | 37 MHz |
| RV32IM, 16 KB, UART (`rv32im_arty_uart`) | Artix-7 XC7A35T (Arty A7-35T) | about 970 LUTs, 300 FFs, 10 DSP48E1 | 4 RAMB36E1 + 12 RAM32M (the register file) | 78.9 MHz: run at half rate, 50 MHz (FINDINGS.md, H5) |
| pipelined RV32IM, 16 KB, UART (`p_arty`, app/pgen.wiz) | XC7A35T | about 2000 LUTs, 936 FFs, 4 DSP48E1 | 12 RAMB36E1 + 2 RAMB18E1 + 12 RAM32M (no DDR, so no caches) | 106.9 MHz, run at 100 |
| the Doom machine, pipelined (`doom_top`) | XC7A35T | about 5100 LUTs, 3900 FFs, 4 DSP48E1 (with wiz-ddr3's controller, cache, PHY) | 23 RAMB36E1 + 4 RAMB18E1 + 12 RAM32M | 104.8 MHz, run at 100 (no multicycle constraints) |

(The Arty build is artix-target's openXC7 flow: yosys, nextpnr-xilinx, Project X-Ray.)

## The Arty demo

`rv32im_arty_uart` (src/Rv/Board.wiz): the core's output port is a UART transmitter,
its input port a receiver, 115473 baud (a little fast of the FT2232's 115384.6), BTN0
resets the core, LD4 blinks, LD5 … LD7 show a trap code. The program (`Prog.demo` in
src/Rv/Progs.wiz, assembled by src/Rv/Asm.wiz) prints

```
wiz-rv RV32IM on Arty
M self-test: PASS
primes up to 1000:
2 3 5 7 11 … 997
> 
```

and then echoes what is typed. The self-test compares 40 M results computed on the
board with the specification's (`Rv.muldiv`, evaluated when the program is assembled).
On the host: `picocom -b 115200 /dev/serial/by-id/usb-Digilent_*-if01-port0`, then BTN0.
It ran on the user's Arty A7-35T on 2026-11-12 (loaded by artix-target): the 711 bytes
above, byte for byte, then the echo.

Lockstep (`tests/lockstep.wiz`): the core and the specification agree, instruction by
instruction (PC and every register at each instruction boundary, all memory and the
output at the end), on programs exercising every RV32I instruction, the traps, RV32E's
register limit, and (RV32IM) every M instruction on the edge cases.

Proofs (`src/Rv/Proofs.wiz`, kernel-checked): from the decode phase, two cycles of the
RV32E core give the specification's PC and rd for XOR, OR, AND, XORI, ORI, ANDI, LUI and
AUIPC, for every PC, register file, memory (holding the instruction at PC) and every
value of the core's other registers. FINDINGS.md, H2, says why not the others.

## Toolchain

The HDL memories are Wiz PR #166 and the fast netlist simulator PR #199, both unmerged
when this was written: the toolchain here is wiz master 50cd3e7 with both branches
merged locally (`wiz-toolchain` names it). `flake.nix` gives yosys, nextpnr-ice40,
icestorm and Icarus Verilog.

```sh
grail build          # check the library, compile the driver
grail test           # the specification tests and the lockstep simulations
.grail/bin/rv all    # Verilog, synthesis, place and route
```

## Doom

The machine for Doom on the Arty (src/Rv/Doom.wiz): the pipelined RV32IM core at 100 MHz
(`doomTop`; `doomTopHalf` is the multi-cycle core at half rate; `doomSys` takes the rate
and the core) with a bus to the
Arty's 256 MB DDR3 (through the write-back cache and the controller of wiz-ddr3, written
in Wiz too), 16 KB of on-chip RAM holding a boot loader (`Prog.boot`, written with the
assembler), and its I/O: the UART at 1 Mbaud, a cycle counter, a sound FIFO played at
11025 Hz as PWM on JB pin 1 (a piezo between JB1 and GND on JB5, or across JB1 and JB2,
which carries the PWM's complement, for twice the swing), and a 96 × 64
framebuffer sent continuously to a PmodOLEDrgb on JA.

```
0x00000000  16 KB on-chip RAM (the boot loader)
0x40000000  DDR3, 256 MB: Doom from here, its WAD at 0x48000000
0x80000000  UART · +0x10/+0x14 cycles · +0x30 sound sample · +0x34 sound FIFO free
0x81000000  the framebuffer (RGB 565, halfwords)
```

The software (sw/, built by nix/doom.nix with the RV32IM toolchain of nix/riscv.nix):
doomgeneric (fetched at a pinned commit), a platform layer (the frame downscaled to
96 × 64, time from the cycle counter, keys from the UART if any; without them Doom plays
its demos), a sound module (eight effect channels and the music mixed into the FIFO:
music × 2, effects × 0.6, a gain of 1.5 and a soft limiter, tuned by ear on the piezo),
a music synthesizer (sw/mus_synth.c: the MUS score drives six square-wave voices with a
decay envelope, an octave up for the piezo, channel 15 as noise; `mustest` in
sw/iss renders a lump to WAV on the host), newlib's system calls
(the console on the UART, the WAD as the one file). `rvload PORT doom.bin doom1.wad`
(app/rvload.wiz) sends both through the boot loader and starts Doom. The shareware
`doom1.wad` is not in the repository (wad/ is ignored).

On the board (2026-11-12, with wiz-ddr3 f99ab70): the boot loader printed "wiz-rv boot",
"DDR ok"; rvload loaded doom.bin and the WAD into DDR and Doom started (its whole
start-up on the console, as in the simulator). `scripts/arty-load.sh` is what was run
(SRAM load, then rvload when the board says "DDR ok").

With the pipelined core at 100 MHz (2026-11-12, doom_top at 100.12 MHz in nextpnr): Doom's
demo loop at about 15 frames a second (69 to 83 frames per 5 s), about 278 M instructions
per 500 M cycles, so CPI about 1.8. (The perf line's "CPI x100" divides the 50 MHz cycle
counter by the instruction count: 89 there is 1.78.) The multi-cycle core at half rate
managed about 4 frames a second, at CPI 3.9 in 50 MHz cycles. A bus access is under way in about half of the
cycles, and the front end waits for a miss or a restart in about a quarter. The OLED
streamer's "odd" count rose by about 25 to 30 per 5 s, out of about 120 refreshes. It
counts a refresh whose checksum changed with no framebuffer write since the last
refresh, so a write during the previous refresh, after its pixel was sent, also counts.
With Doom drawing faster, that artefact grows. It needs a look at the panel.

Checked so far: the core's bus and the boot loader in the lockstep against the
specification (with a DDR model), and compiled C (sw/ctest: gcc's output and newlib's
string functions, 1060 instructions, generated into src/Rv/CTest.wiz by app/bin2wiz); the whole machine but the DDR controller in Icarus
Verilog (`simTop`: it boots, loads a program into DDR over the UART, runs it);
Doom itself on a host instruction-set simulator of the machine (sw/iss/iss.c: frames as
images, sound as a WAV file): the demo loop at about 3.7 frames a second at the core's
50 MHz, cache misses not counted.

## Next

* **Doom on the Arty** (doomgeneric, bare-metal RV32IM): a GCC toolchain (Nix
  `pkgsCross.riscv32-embedded`) and a small runtime (crt0, linker script, newlib's
  syscalls on the UART); peripherals on the I/O space: a timer, the UART, an SPI master
  for the PmodOLEDrgb (SSD1331, 96 × 64, 16-bit colour) and a QSPI flash reader for the
  WAD; instruction and data caches; a block-RAM heap for bring-up, then DDR3 (the
  Arty's 256 MB) as its own milestone.
* Proofs beyond the bitwise instructions need bit-vector rewriting (FINDINGS.md, H2).
