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
src/Rv/DPipe.wiz     the pipelined core in the Doom machine, and its simple-DDR simulation top
src/Rv/Golem.wiz     golem, the SoC top: the core, DDR3, UART and OLED on one bus
src/Rv/GolemSim.wiz  golem with a behavioural DDR, for the simulation test
src/Rv/Golem/*.wiz   its memory map, bus/arbiter and boot ROM
app/rv.wiz           the flow driver: Verilog, yosys, nextpnr
tests/*.wiz          grail tests
```

## The machine

RV32I (32 registers) or RV32E (16), the unprivileged base ISA v2.1, with a bounded
Zicsr subset: one CSR, `mscratch` (0x340), and the six CSR instructions (CSRRW/S/C,
CSRRWI/SI/CI) that the riscv-arch-test Zicsr programs use. Any other CSR number is an
illegal instruction; there is no privilege mode, `mtvec`, or trap handler.
ECALL, EBREAK, an illegal instruction, a misaligned load, store or jump target stop the
machine instead of trapping into a handler. The stopped machine records the RISC-V trap
state: the cause (`mcause`; `src/Rv/Isa.wiz` has the list), `tval` (`mtval`: the
faulting address, or the instruction word for an illegal instruction; 0 for
ECALL/EBREAK) and `epc` (`mepc`: the PC of the trapping instruction). FENCE is a no-op. Memory is 2^n bytes from address 0 (addresses wrap); the program image is its
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

`src/Rv/Pipe.wiz`: five stages, in order, at the full clock rate (no clock enable).
The pipelined core decodes the base ISA and M; it does not implement the bounded
Zicsr subset above (a CSR instruction is an illegal instruction there).

* **F**: the next fetch address goes to block RAM: the on-chip RAM's fetch copy and the
  I-cache (16 KB, 16-byte lines, direct-mapped).
* **D**: the I-cache hit check and the decode. The register file is two RAM32M copies,
  read asynchronously, with a bypass of R's write.
* **E**: the ALU and the barrel shifter. Branches are predicted not taken and resolved
  here; a taken branch or jump is registered and redirects the fetch a cycle later, so
  it costs 2 cycles. Also here: the traps (cause, tval and epc are latched/held at H),
  and the four 16 × 16 partial products of the multiplier (4 DSP48E1). The divider is
  iterative (34 cycles; E waits). The D-side memories are read at the address.
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

The ISA (src/Rv/Isa.wiz) and the bus to DDR are otherwise unchanged.

Proofs (proofs/PipeProofs, `scripts/pipe-proofs.sh`; about 20 minutes each): from D,
with the stages behind it empty, the next fetch address and, three cycles on, R's
retiring instruction (its PC, rd and value) are the specification's. This is the full
claim for XOR, OR, AND, LUI and AUIPC, and field by field without the glue for XORI,
ORI and ANDI (FINDINGS.md, H10).

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
| golem, pipelined (`golem`, board flow) | XC7A35T | 5063 LUTs, 3815 FFs, 4 DSP48E1 (DDR3, UART, OLED, the bus) | 23 RAMB36E1 + 4 RAMB18E1 + 12 RAM32M | 107.3 MHz (nextpnr), run at 100 |

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
instruction (PC, the trap state (cause, tval) and every register at each instruction
boundary; cause, tval and epc, all memory and the output at the end), on programs
exercising every RV32I instruction, the traps, RV32E's register limit, and (RV32IM)
every M instruction on the edge cases.

Proofs (`src/Rv/Proofs.wiz` and `src/Rv/TrapProofs/`, kernel-checked by `grail build`; the
trap-entry, interrupt, MRET, WFI and CSR claims are docs/csr.md's theorem): from the decode phase, two cycles of the
RV32E core give the specification's PC and rd for XOR, OR, AND, XORI, ORI, ANDI, LUI and
AUIPC, for every PC, register file, memory (holding the instruction at PC) and every
value of the core's other registers. The trap-state claims (`Pf.TrapClaimAt`) give the
specification's cause, tval and epc for ECALL, EBREAK, an illegal instruction, and a
misaligned load, store and jump (the address ones from a concrete x1, because the
address adder is not bridged for a symbolic operand yet). FINDINGS.md, H2, says why not
the other instructions.

## Independent oracle

`oracle/` is verification infrastructure, not part of the core. It compares the
executable specification (`Rv.Isa`), the multi-cycle core, an independent Python RV32I
reference, `sail-riscv` and Spike on one architectural trace per instruction (PC, trap
cause, all 32 registers and the data memory), on ALU, branch, load/store, shift and
mixed fixtures. The Wiz sides also emit the rest of the trap state (`tval`, `epc`) on a
`T` line; six `trap_*` fixtures stop the machine on each trap cause and compare it
between `isa`, `core` and `py` (Sail/Spike enter a handler and are reported as skips,
not passes). The recorded run (sail-riscv 0.12, Spike 1.1.1-dev) has 31 passing
comparisons, 0 failures and 2 documented skips (Spike cannot load at 0, so the two
AUIPC fixtures are Sail/Python-only); the trap set adds 33 `isa`/`core`/`py`
comparisons, all passing.

The same directory has an `rvfi` (RISC-V Formal Interface) wrapper for the emitted
core. It is generated from the flat Verilog by `oracle/scripts/mkrvfi.py`, linted with
Icarus, and its rvfi beats are simulated and compared with the Python reference on all
five fixtures. The riscv-formal checks were then run against the pinned revision
`c992aa61fdfe0846c5ed90324c596202a1c69b76` (2026-07-16, yosys 0.70+post, sby 0.70,
boolector 3.2.4, Icarus 13.0): **37/37 `insn_*_ch0` checks pass** (every base-I
instruction), `causal_mem_ch0` passes on the mixed load/store program, and the
`reg`/`pc_fwd`/`pc_bwd`/`causal`/`unique`/`liveness` consistency checks pass on the
load program. No assertion failed. See [oracle/README.md](oracle/README.md) and
[oracle/riscv-formal/README.md](oracle/riscv-formal/README.md).

## Toolchain

The HDL memories (PR #166) and the fast netlist simulator (PR #199) were unmerged when
this was written, so the original toolchain was wiz master 50cd3e7 with both branches
merged locally. They are in master now: `wiz-toolchain` pins `master@071a033a…`, the
first snapshot release that has both, instead of a local-merge description. `flake.nix`
gives yosys, nextpnr-ice40, icestorm and Icarus Verilog.

```sh
grail build          # check the library, compile the driver
grail test           # the specification tests and the lockstep simulations
.grail/bin/rv all    # Verilog, synthesis, place and route
```

## golem, the SoC

`src/Rv/Golem.wiz` is the first top level that puts the pieces together: the pipelined
core (or the multi-cycle core at half rate, `golemMc`), wiz-ddr3's DDR3 cache,
controller and PHY, the UART and the PmodOLEDrgb framebuffer, with an explicit memory
map, a bus decode and a two-master arbiter. The map is the Doom machine's
(16 KB of on-chip RAM at 0, 256 MB of DDR3 at 0x40000000, the UART/timer/sound and
performance counters at 0x80000000, the 96 × 64 framebuffer at 0x81000000) plus a UART
status register, and it is written down once in `src/Rv/Golem/Map.wiz` and
`sw/golem.h`. [DESIGN.md](DESIGN.md) has the table, the bus, the simulation and the
Arty board flow.

The simulation boots a small ROM (`src/Rv/Golem/Prog.wiz`) which prints on the UART,
checks DDR and the timer, draws three pixels into the framebuffer, and calls a routine
it copied into DDR. Four short kernel runs check it (as the lockstep tests do; the
compiled netlist is over the build's memory cap): `tests/golem.wiz` the boot ROM as a program on
the specification, `tests/golem_oled.wiz` the OLED's SPI stream,
`tests/golem_bus.wiz` the bus/arbiter and DDR stub, and `tests/golem_board.wiz` the
Arty configuration (75 pins, 55 top ports, the PLL's clocks, the reset domains).

```sh
grail test golem     # or: wiz check tests/golem.wiz -I src -I ../wiz-ddr3/src …
```

### golem on the Arty A7-35T

`src/Rv/Golem/Board.wiz` is the board configuration and `src/Rv/GolemBoard.wiz` its
circuits: `Ddr3.Board`'s DDR3, clock, UART
and LED constraints plus JA (PmodOLEDrgb), JB (sound) and BTN; the PLL wrapper (100 MHz
input, 800 MHz VCO, 100 MHz `sys`, 400 MHz `sys4x`, 400 MHz `sys4xDqs` at 90°, 200 MHz
`ref200`); and the reset domains. `golem` runs the pipelined core at 100 MHz;
`golemMc` keeps the 100 MHz board clock and enables the multi-cycle core every other
cycle (50 MHz effective). `golem_four` is the 4-hart AMP cut of
[DESIGN.md](DESIGN.md#four-harts): four multi-cycle harts, one shared UART/OLED/timer/
mailbox and DDR, behind the N-master arbiter (`--variant four`; `four_nol1` disables
each hart's L1). The default boot image is `Prog.boot`, the UART loader that
prints `wiz-rv boot` and `DDR ok`/`DDR fail` and accepts `rvload` records; `--boot rom`
selects the self-contained `GProg` bring-up ROM. LD0/LD1 are calibration done/failed
and MMIO `0x8000_0040` reports the same.

```sh
grail build
scripts/golem-board.sh board      # the pin/clock/reset check (also `golem board`)
scripts/golem-board.sh gen        # build/golem.v and build/golem.xdc
scripts/golem-board.sh gen --variant four  # build/golem_four.v (four harts, 20 ns XDC)
scripts/golem-board.sh synth      # yosys only (dry-run path if it is missing)
scripts/golem-board.sh bit        # nextpnr-xilinx + fasm2frames + xc7frames2bit
scripts/golem-board.sh timing     # 100 MHz for golem/golemMc, 50 MHz for the four-hart builds
```

`bit` writes `build/a35t/golem.bit` (and `golem.timing`, `golem.report`). The hardware
step, not run here, is `openFPGALoader -b arty_a7_35t build/a35t/golem.bit`, then the
UART at 1 Mbaud: the calibration line, then `rvload PORT prog.bin` (or
`rvload PORT doom.bin doom1.wad`). [DESIGN.md](DESIGN.md) has the pin table and the
full flow.

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
`doom1.wad` is not in the repository (wad/ is ignored). sw/README.md has the memory
map, the boot protocol, the entry convention and the builds (`make -C sw`); the boot
flow runs end to end in the executable lockstep (bench/boot.wiz).

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
