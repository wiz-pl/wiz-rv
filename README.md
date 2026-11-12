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
