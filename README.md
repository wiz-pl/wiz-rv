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

## Results

| design | part | logic | block RAM | Fmax (nextpnr) |
|---|---|---|---|---|
| RV32E, 2 KB | iCE40-HX1K (tq144) | 1020 / 1280 LCs (79 %) | 8 / 16 | 40 MHz |
| RV32IM, 16 KB, UART (`rv32im_arty_uart`) | Artix-7 XC7A35T (Arty A7-35T) | about 970 LUTs, 295 FFs, 10 DSP48E1 | 4 RAMB36E1 + 12 RAM32M (the register file) | 79 MHz: run at half rate (FINDINGS.md, H5) |

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

## Next

* **Doom on the Arty** (doomgeneric, bare-metal RV32IM): a GCC toolchain (Nix
  `pkgsCross.riscv32-embedded`) and a small runtime (crt0, linker script, newlib's
  syscalls on the UART); peripherals on the I/O space: a timer, the UART, an SPI master
  for the PmodOLEDrgb (SSD1331, 96 × 64, 16-bit colour) and a QSPI flash reader for the
  WAD; instruction and data caches; a block-RAM heap for bring-up, then DDR3 (the
  Arty's 256 MB) as its own milestone.
* Proofs beyond the bitwise instructions need bit-vector rewriting (FINDINGS.md, H2).
