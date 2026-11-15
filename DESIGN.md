# golem: the SoC top level

`golem` is wiz-rv's first SoC: a RISC-V core, wiz-ddr3's DDR3 controller, a UART and
a PmodOLEDrgb framebuffer on one bus, with the memory map below written down in one
place. It composes the pieces that were already here (the cores, wiz-ddr3's cache and
controller, the Doom machine's UART/OLED/timer/framebuffer) instead of replacing
them; the new code is a bus with an address decode and an arbiter, a simulation top,
and the software's map.

```
        ┌──────────────────────────────────────────── golem ────────────────────────────────────────────┐
        │                                                                                                │
 GIn ──▶│ UART rx ─▶│ machine (`Doom.doomSysCfg`)                       │◀─ MMIO ─┐                       │
        │            │  pipelined core (100 MHz) or multi-cycle (½)      │         │                       │
        │            │  UART · cycle counter · sound FIFO · framebuffer   │         │                       │
        │            └───────────────┬───────────────────────────────────┘         │                       │
        │                            │ bus request (`DOut.valid/addr/…`)           │                       │
        │                ┌───────────▼──────────┐    ┌──────────────────────────┐   │                       │
        │                │ `GBus.route` decode  │    │ `GBus.arb` (core, host)  │   │                       │
        │                │ DDR 0x40000000 …     │───▶│ one outstanding request  │   │                       │
        │                │ else: answered, err  │    └───────┬──────────────────┘   │                       │
        │                └──────────────────────┘            │ CacheReq/CacheResp    │                       │
        │                                        ┌───────────▼───────────┐           │                       │
        │                                        │ wiz-ddr3 8 KB cache   │           │                       │
        │                                        │ controller · PHY      │◀── Ddr3Pads (board)            │
        │                                        └───────────────────────┘           │                       │
        └───────────────────────────────────────────────────────────────────────────────────────────────┘
```

`golem` is the pipelined core at 100 MHz; `golemMc` is the conservative variant, the
multi-cycle core at half rate (the Doom machine's `doomHalf` arrangement). Both use
wiz-ddr3's cache and controller at the full rate and the existing bus adapter
(`busStep`, src/Rv/Doom.wiz), which crosses the core's rate in registers.

## Memory map

| range | device | notes |
|---|---|---|
| `0x0000_0000` – `0x0000_3FFF` | 16 KB on-chip RAM | the boot ROM at reset; the core's `m0` … `m3` (wb = 12) |
| `0x4000_0000` – `0x4FFF_FFFF` | 256 MB DDR3 | through wiz-ddr3's 8 KB write-back cache, controller and PHY |
| `0x8000_0000` + `0x00` | UART data | read: the next byte or `-1`; write: send (1 Mbaud, 8N1) |
| `0x8000_0000` + `0x04` | UART status | bit 0 transmitter idle, bit 1 a byte is waiting |
| `0x8000_0000` + `0x10/0x14` | cycle counter | 64 bits, low/high; 100 MHz |
| `0x8000_0000` + `0x30/0x34` | sound FIFO | sample out / free places (PWM on JB1) |
| `0x8000_0000` + `0x40` | DDR status | bit 0 calibration done, bit 1 failed |
| `0x8000_0000` + `0x50 … 0x7c` | performance counters | instructions, bus/memory cycles, cache hits/misses, framebuffer writes, OLED refreshes |
| `0x8000_0000` + `0x80` | OLED controller | the pins and program counter (debug) |
| `0x8000_1000` + `0x00/0x10` | mailbox | per hart: message/valid, and the boot entry address |
| `0x8000_2000` | PLIC-style controller | priorities, pending, per-context enable/threshold, claim/complete |
| `0x8000_4000` + `0x00/0x4000/0xbff8` | CLINT-like timer | `msip` per hart, `mtimecmp` (64-bit per hart), `mtime` |
| `0x8100_0000` – `0x8100_2FFF` | framebuffer | 96 × 64 RGB 565, row-major, halfword stores (12 KB) |

Everything is word-addressable except the framebuffer, which the core writes as
halfwords; byte and halfword stores work everywhere the core's memory does. The map is
`src/Rv/Golem/Map.wiz` (hardware constants and the decode predicates) and
`sw/golem.h` (the same for C). It is the Doom machine's map, so Doom's software keeps
working; `golem.h` adds the UART status register, the interrupt/timer blocks and their
helpers.

The bus decode sends every address with bit 30 set (and bit 31 clear) to DDR, as the
core's memory does; an address in `0x5000_0000` – `0x7FFF_FFFF` is answered at once
with `ready` and `err` (and zero for a read) instead of hanging. MMIO is decoded by the
machine at the core's I/O port (`DOut.ioa`, bit 31 set), not on this bus: the core's
`Out` keeps the two apart, so the UART and the framebuffer cost no bus arbitration.

## The bus and its arbiter

`CacheReq`/`CacheResp` (valid, `addr[27:0]`, we, `wdata`, `wstrb`; ready, rvalid,
`rdata`), the interface wiz-ddr3's cache and the core's bus adapter already share.

* `GBus.route` takes the core's request and the slave's answer, runs the existing
  adapter (`busStep`), and suppresses the request unless the address is in DDR. An
  unmapped request is answered immediately (`err` high); the core sees the same
  `ready`/`rvalid` protocol and cannot hang on a wild pointer.
* `GBus.arb` has two masters: the core and a host loader. The core wins ties, and the
  owner keeps the bus until its answer (`ready` or `rvalid`), so a line fill is not
  interrupted. A master that drops `valid` mid-request (a loader stopped early, a core
  that traps) ends the request instead of owning the bus forever. The hardware top ties
  the loader's request off; the simulation top exposes it (useful for bring-up: put a
  word or a program in DDR without bit-banging the UART).
* `GBus.ramStep` is a behavioural DDR (words with byte masks, answering two cycles
  after the request) behind the same interface, for simulation.

Both the adapter and the arbiter are registers around combinational code, so they run
at the bus's 100 MHz whatever rate the core runs at.

## Interrupts, timer and harts

The multicore decisions M6/M7 (`wiz-notes/golem-multicore-decisions.md`) ask for a
CLINT-like per-hart timer, a simple PLIC-style external path, an IPI mailbox, and a
documented boot ABI. All three blocks are in `src/Rv/Golem/Intc.wiz`, inside the
machine's I/O window; the machine decodes a 16-bit register offset (`GMap.mmioOff`) so
that they do not alias the 8-bit-address UART and performance registers. The framebuffer
(bit 24 of the address) is excluded from their decode.

| register | address | meaning |
|---|---|---|
| `msip(h)` | `0x8000_4000 + 4h` | the doorbell: write 1 releases hart `h`, write 0 clears it |
| `mtimecmp(h)` | `0x8000_8000 + 8h` | 64-bit compare value (low word, then `+4`) |
| `mtime` | `0x8000_fff8/fffc` | 64-bit counter, incremented every machine cycle |
| `PRIO(s)` | `0x8000_2000 + 4s` | source priority, 3 bits (0: never taken) |
| `PENDING` | `0x8000_2020` | the pending bitmap (read) |
| `ENABLE(c)` | `0x8000_2040 + 4c` | enabled sources of context `c` |
| `THRESH(c)` | `0x8000_2060 + 4c` | the priority threshold of context `c` |
| `CLAIM(c)` | `0x8000_2080 + 4c` | read: take the highest-priority source (0: none); write: complete it |
| `IPI_DATA(h)` | `0x8000_1000 + 8h` | a message for hart `h`; a read takes it and clears its valid bit |
| `IPI_STATUS(h)` | `0x8000_1004 + 8h` | bit 0: a message is waiting |
| `BOOT_ENTRY(h)` | `0x8000_1010 + 4h` | the entry address hart 0 gives hart `h` |

The `mtimecmp`/`mtime` layout is the standard CLINT's (msip at `+0`, mtimecmp at
`+0x4000`, mtime at `+0xbff8`), rebased from `0x0200_0000` to `0x8000_4000` so that it
stays inside the I/O window. Two contexts: 0 is hart 0's M-mode, 1 is hart 1's. The
four sources are 1 the UART's received byte (a live level), 2 hart 0's mailbox, 3 hart
1's mailbox, and 4 a spare external input (tied low on this board). A message posted to
hart `h` raises source `2 + h`; a claim clears the pending bit and marks the source in
service for that context (so a second claim returns 0), a write to the same claim
register (the completion) clears the in-service bit, and a live level such as the
UART's sets the pending bit again until software drains the UART.

`mip` is assembled from the blocks, and this is the contract the core's interrupt input
must implement (`Intc.mip`, `Intc.take`, `Intc.cause`):

| bit | name | source |
|---|---|---|
| 3 | MSIP | `msip(hart)` |
| 7 | MTIP | `mtime >= mtimecmp(hart)` |
| 11 | MEIP | the PLIC has a source for the hart's context |

The other `mip` bits read 0 (no supervisor or user mode). `mie` has the same three bits
and an interrupt is taken when `mstatus.MIE` is set and `mip & mie != 0`; the code is
MEI (11), then MSI (3), then MTI (7), matching the privileged specification's priority.
Trap entry is the standard M-mode one: `mepc = pc`, `mcause = 0x8000_0000 | code`,
`mstatus.MPIE = mstatus.MIE`, `mstatus.MIE = 0`, `mstatus.MPP = M`, `pc = mtvec` (direct
mode only). `mret` restores `MIE = MPIE` and returns to `mepc`.

**The core does not implement this yet.** `Rv.Core`/`Rv.Pipe` have no machine CSRs and
no interrupt input (`In` has no `irq`); the blocks are the prerequisite, and the
`Intc.mip`/`Intc.take`/`Intc.cause` functions are the specification to wire in. Until
then software polls: `MTIME_LO/HI` against `MTIMECMP`, `IPI_STATUS`, and `PENDING`
(`sw/golem.h` has the addresses, the `mip`/`mie` bits and the helper calls).
`tests/golem_intc.wiz` checks the timer, the UART and mailbox paths, claim/complete,
the `mip`/`mie` gating, the priority between MSI and MTI, and the boot handshake.

### The boot ABI

Reset sets every hart's `pc` to 0 (the boot ROM) and `mhartid` to its index; hart 0 is
the boot hart. The protocol:

1. Hart 0 runs the ROM: it waits for the DDR3 calibration, sets up its own traps, and
   initialises the PLIC (priorities, then enables, then its threshold).
2. For each other hart `h`, hart 0 writes the address of `h`'s entry point to
   `BOOT_ENTRY(h)`, then writes 1 to `msip(h)`. This is one store each, in that order;
   the message is the doorbell, the entry address is the sticky register.
3. Hart `h`, if `mhartid != 0`, parks before touching anything shared: it polls
   `msip(h)` (or `IPI_STATUS(h)` for a mailbox message). When the doorbell reads 1 it
   reads `BOOT_ENTRY(h)`, clears `msip(h)` by writing 0, and jumps there. Its stack and
   its page tables (none, AMP) are the entry point's responsibility.

Because a hart cannot read `mhartid` through the (yet non-existent) CSR file, the ROM
in this tree is still single-hart: the park loop and the hart-id branch are the first
two instructions of a second hart's image, not of `GProg.golem`. Hart 1's park loop can
be polled with `MSIP(1)`; there is no `wfi` (it needs the CSR file too).

An IPI after boot uses the same registers: `IPI_DATA(h) = msg` posts a 32-bit word and
raises PLIC source `2 + h`; the receiver claims it (`PLIC_CLAIM(1)` in hart 1's
context), reads the word (which clears `IPI_STATUS`), and completes the source.

The park loop, with the addresses of `sw/golem.h`:

```
park:
    lw   t0, 0x80004004      # MSIP(1): hart 0's doorbell for hart 1
    beqz t0, park
    lw   t1, 0x80001014      # BOOT_ENTRY(1)
    sw   zero, 0x80004004    # clear the doorbell
    jalr zero, 0(t1)         # enter the program hart 0 placed there
```

Because `mtimecmp` is two 32-bit registers, write the high half first and then the low
half: the other order makes a transient compare value from the old high half, which can
raise MTIP for a cycle. `sw/golem.h`'s `golem_set_mtimecmp` does it in that order.

### What this changes in the machines

`Mini.machine` (the simulation) and `Doom.dSys` (the board) both carry `Intc.Ctl` in
their state, decode the 16-bit register offset, read the block into the core's `ioIn`,
and step it once per machine cycle with the UART's received byte as the live source.
Two limits are recorded here rather than hidden:

* `mtime` counts the machine's cycles. On `golem` (pipelined core) that is 100 MHz; on
  `golemMc` the machine is under `Circuit.half`, so `mtime` is 50 MHz. Software that
  needs wall time must scale by the variant (a gap to close by putting the timer in the
  full-rate part, which needs a second MMIO path).
* The block is at the core's I/O port, so an I/O store waits for the UART transmitter to
  be idle (the existing machine's rule for every I/O store). It costs at most the
  remaining byte time, but it means a timer compare write can be delayed.

## Files

```
src/Rv/Golem/Map.wiz    the memory map: constants, decode predicates, MMIO offsets
src/Rv/Golem/Bus.wiz    GBus.route (decode), GBus.arb (two masters), GBus.ramStep (sim DDR)
src/Rv/Golem/Intc.wiz   the CLINT-like timer, the PLIC-style controller, the inter-hart
                        mailbox, `mip`/`mie` and the boot ABI's registers
src/Rv/Golem/Prog.wiz   the boot ROM: banner, DDR/host/timer checks, three pixels, a DDR call
src/Rv/Golem.wiz        GIn/GOut, Golem.step (cache + controller + bus + machine),
                        golem / golemMc (board, with the PHY), the reset/LED policy
src/Rv/GolemBoard.wiz   the board circuits: golem and golemMc for Timing.arty, and
                        the netlist each variant becomes
src/Rv/Golem/Board.wiz  the Arty A7-35T board: boot image, PLL clocking, pins, XDC,
                        reset domains and the `golem board` check
src/Rv/GolemSim.wiz     golemSim: the same machine and bus with a behavioural DDR
src/Rv/DPipe.wiz        the pipelined core in the Doom machine (`doomFull`, `simTop`),
                        kept out of Rv.Doom so the simulation test does not compile it
app/golem.wiz           the board flow: gen, synth, bit, timing, dry (`golem …`)
scripts/golem-board.sh  the flow wrapper: finds the tools, refuses to flash unsigned
tests/golem.wiz         the executable simulation (UART bytes and the OLED SPI stream)
tests/golem_intc.wiz    the timer, the external interrupt path and the boot handshake at values
tests/golem_board.wiz   the `golem board` config/constraints check
sw/golem.h              the memory map and MMIO for software
sw/golem.c              a tiny C hello (banner, cycle counter, three rows)
```

The machine itself is `Doom.doomSysCfg` (src/Rv/Doom.wiz), which is `doomSys` with
the OLED timing configuration as a parameter. The OLED configuration, the UART status
register and the interrupt/timer block (`Intc.Ctl` in the machine's state and its
16-bit I/O decode) are the changes to that file; `doomHalf`/`doomFull` and their tests
are otherwise unchanged.

## Simulation

The simulation top is `Golem.golemSim` (src/Rv/GolemSim.wiz): the slim machine
(`Mini.machine`: the multi-cycle core, UART, cycle counter, framebuffer and OLED), the
bus and the arbiter, and `GBus.ramStep` in place of the DDR cache, controller and PHY.
The checks run these definitions in the kernel's evaluator (`#eval`), as the lockstep
tests do. Compiling the machine with `Circuit.simFast` is over the 5 GB build cap
(FINDINGS.md, S1 — the core's IR alone takes tens of minutes and gigabytes), so the
executable checks use values and short runs.

There are five checks, one per piece, because each kernel run's state is large
(`tests/golem*.wiz`):

| test | what it runs | checks |
|---|---|---|
| `tests/golem.wiz` | the boot ROM (`GProg.sim`) as a program on the ISA specification (`Rv.run`) | trap 2 (EBREAK), the UART text |
| `tests/golem_oled.wiz` | the framebuffer and the SSD1331 streamer (`OledSim`, the controller at its `pixels` step) | the first six SPI data bytes: red, green, blue (RGB 565, high byte first) |
| `tests/golem_bus.wiz` | `GBus.route`/`arb`/`ramStep` at values | the host writes `0x600d` to DDR[0], the core reads it back, no error |
| `tests/golem_intc.wiz` | `Intc` at values | MTIP rises exactly when `mtime` reaches `mtimecmp` (tick 100), cause 7; `mstatus.MIE` gates it; MSI outranks MTI; the UART and mailbox PLIC paths claim, in-service, complete and re-arm (sources 1 and 3); the boot entry and doorbell handshake |
| `tests/golem_board.wiz` | `GBoard` (the Arty configuration) | 75 pins, 55 top ports, clocks 100/400/400/200 MHz, reset domains as the design |

The boot check is the program on the specification (the core is the multi-cycle one
that `tests/lockstep.wiz` checks against the same specification; the whole machine with
the core is over the cap); the OLED check sets the controller's clock enable every cycle instead of every
16 and preloads the framebuffer with the three pixels, so 200 cycles carry the first
bytes of a frame; the boot ROM also writes those pixels in the board image, but the
specification sends every store with bit 31 set to the output port, so the lockstep
program (`GProg.sim`) leaves the framebuffer out.

The interrupt check runs the `Intc` step function at values, not the machine: there is
no two-hart prototype in this tree (the second core, the `mhartid` CSR and the core's
interrupt input are the next change), so the inter-hart part of the check is the
mailbox between two harts' registers — hart 0 posts, hart 1's context claims and reads —
rather than two cores executing. The timer half is the single-hart smoke test M6 asks
for: `mtimecmp = 100` makes MTIP and the cause visible exactly at tick 100.

```sh
# the design and the checks, with the toolchain of wiz-toolchain (see README,
# "Toolchain"):
wiz check src/Rv/Golem.wiz   -I src -I ../wiz-ddr3/src
wiz check tests/golem.wiz    -I src -I ../wiz-ddr3/src
wiz check tests/golem_oled.wiz -I src -I ../wiz-ddr3/src
wiz check tests/golem_bus.wiz  -I src -I ../wiz-ddr3/src
wiz check tests/golem_intc.wiz -I src -I ../wiz-ddr3/src
wiz check tests/golem_board.wiz -I src -I ../wiz-ddr3/src
# or through grail (checks the library and runs the tests):
grail build && grail test golem
```

The checks print (exactly; the `tests/golem*.expected` files):

```
golem boot: trap 2, pc 164, out "golem boot
host ok
timer ok
ddr ok
", PASS
golem oled: 11 data bytes, first six f8 00 07 e0 00 1f  — PASS
golem bus: host wrote 0x600d, core read 24589, err 0 — PASS
golem intc: timer mtip at tick 100, taken 1, cause 7, rearmed 0, csr 0/3; uart claim 1, again 0, completed 1, pending 2; ipi valid 1, meip 1, claim 3, pending 0, msg 24589; boot 0 -> 1 entry 1073742080 — PASS
golem board: 75 pins, 55 top ports, 3 reset domains, clocks 100/400/400/200 MHz, PASS
```

The boot ROM (`GProg.golem`) prints the banner; waits for the DDR status (the stub
reports done); reads DDR[0], which the host loader wrote (`0x600d`; 0 means no loader);
reads the cycle counter; writes red, green and blue at pixels (0,0), (1,0) and (2,0);
copies a routine into DDR, calls it there (`jalr` over the bus) and checks the result;
then `ebreak`s. The OLED check decodes the SPI stream from the JA pins; the bus check
uses the same `GBus` code the board does.

For a compiled netlist run, `Golem.golemSim` is the same circuit; on a machine with
more than the build cap's memory, `Circuit.simFast` (Hdl.Sim) runs it cycle by cycle.
The DDR3 controller and model are not in this run: `Golem.golem` instantiates them,
and `DoomTop.doomSim` is the existing circuit with the controller and the behavioural
device in place of the PHY, if a full-DDR simulation is wanted (it is generated to
Verilog and run in Icarus in wiz-rv's Doom flow).

## The Arty A7-35T board

`Golem.golem` (src/Rv/Golem.wiz) is the board circuit: `Ddr3.Board.clocking`'s PLL
clocks (`sys4x`, `sys4xDqs`, `ref200`, `locked`), the PHY, the controller and cache,
the bus, and the machine. It takes `Timing.arty`. The board's configuration lives in
one place, `src/Rv/Golem/Board.wiz` (boot image, PLL clocking, pin table, XDC and reset
domains); `src/Rv/GolemBoard.wiz` adds the two circuits. `tests/golem_board.wiz` and
`golem board` run the same check over the configuration, without elaborating the
netlist.

### Pins

The Arty A7-35T, XC7A35T in CSG324. `Ddr3.Board` supplies the DDR3 pins and the
clock/UART/LED group (SSTL135 for DDR3, LVCMOS33 for the rest);
`Golem/Board.wiz` adds JA, JB and the buttons.

| resource | pins | what |
|---|---|---|
| `clk` | E3 | 100 MHz oscillator |
| `ddr3_a[13:0]`, `ddr3_ba[2:0]`, `ddr3_dq[15:0]`, `ddr3_dm[1:0]` | 35 pins | DDR3 address/data (SSTL135) |
| `ddr3_ck_p/n`, `ddr3_dqs_p0/n0`, `ddr3_dqs_p1/n1` | 6 | DDR3 clock and strobes (DIFF_SSTL135) |
| `ddr3_ras_n`, `cas_n`, `we_n`, `cs_n`, `cke`, `odt`, `reset_n` | 7 | DDR3 control |
| `uart_rx` / `uart_tx` | A9 / D10 | FT2232 channel B, 1 Mbaud |
| `led[3:0]` | H5 J5 T9 T10 | LD0 calDone, LD1 calFail, LD2 core, LD3 bus |
| `ja[7:0]` | G13 B11 A11 D12 D13 B18 A18 K16 | PmodOLEDrgb (PMODEN, VCCEN, RES, D/C, SCLK, MOSI, CS) |
| `jb[7:0]` | E15 E16 D15 C15 J17 J18 K15 J15 | sound PWM (JB1) and its complement (JB2) |
| `btn[3:0]` | D9 C9 B9 B8 | BTN0 resets the core |

That is 75 package pins and 55 top-level ports (48 DDR3 pads are one-bit ports in the
netlist; JA, JB, the LEDs and the buttons are buses). The `golem board` check asserts
both counts, that every port has a pin of the right width, that no package pin is
used twice, and that the XDC has one `PACKAGE_PIN` line per pin.

### Clocks

`Ddr3.Board.clocking` is a `PLLE2_BASE` from the 100 MHz oscillator: VCO 800 MHz, then
CLKOUT0 ÷ 8 = **100 MHz** (the circuit's `sys` clock), CLKOUT1 ÷ 2 = 400 MHz
(`sys4x`), CLKOUT2 ÷ 2 at 90° = 400 MHz (`sys4xDqs`), CLKOUT3 ÷ 4 = 200 MHz
(`ref200`), and `LOCKED` to the circuit's `locked`. `golem` runs the pipelined core at
the full 100 MHz. `golemMc` cannot slow the PLL to 50 MHz — the PHY needs 400/200 MHz
from the same VCO — so it keeps the 100 MHz board clock and runs the multi-cycle core
behind `Circuit.half`: every register and memory write is enabled every other cycle,
which is 50 MHz effective. The `golem board` check computes the four clocks from the
PLL parameters and compares them with 100/400/400/200 MHz.

The timing target is 100 MHz. `bit` reads the last nextpnr report, writes
`build/a35t/golem.timing`, and fails unless the `ck_CLKOUT0_g` line says
`PASS at 100.00 MHz`; `timing` prints the same report without rebuilding. The build in
this tree (yosys 0.70, nextpnr-xilinx 1.0.0, Project X-Ray): 15894 netlist nodes,
5063 LUTs, 3815 flip-flops, 4 DSP48E1, 23 RAMB36E1 + 4 RAMB18E1 + 12 RAM32M;
nextpnr 107.30 MHz, `PASS at 100.00 MHz`, into `build/a35t/golem.bit`. The bitstream
has not been loaded: no hardware control was authorised for this run.

### Reset domains

Three, all named by functions in `Golem/Board.wiz` and checked at values by
`GBoard.resetProblems`:

* **sys** — `BTN0` (btn bit 0) or `!(calDone | calFail)`: the core, the UART, the
  framebuffer and the bus. The core is held until the DDR3 calibration has finished,
  either way, so a failed calibration still lets the boot image print "DDR fail"
  (`GBoard.coreReset`). The MMIO status at `0x8000_0040` reports the same bits.
* **phy** — `phyRst = !(rstCnt == 255)`, with `rstCnt` counting only while `locked`:
  255 cycles after the PLL locks (`GBoard.phyReset`).
* **ddr** — the controller's `rstN` to the DDR3 pins, from its own reset sequence.

The LEDs carry the calibration: LD0 `calDone`, LD1 `calFail`, LD2 the core's
heartbeat, LD3 the bus's (`GBoard.boardLed`).

### Boot image

The default is the UART loader, `Prog.boot`, the image that is already proven on the
Arty: it waits for the calibration, prints `wiz-rv boot` and `DDR ok` (or
`DDR fail`), then accepts `rvload` records and jumps to the loaded program. That is
the image to use for a C program (`sw/golem.c`, linked at `0x40000000`) or Doom.
`--boot rom` selects `GProg.golem` instead, the self-contained bring-up ROM: banner,
DDR status, timer, three framebuffer pixels and a routine copied into and called from
DDR. The host-loader port of the arbiter is tied off on the board; the UART loader is
the only way in. The choice is written to `build/golem.boot` so a bitstream's image is
recorded next to it.

### Building

```sh
grail build                                  # the library and .grail/bin/golem
scripts/golem-board.sh board                 # the pin/clock/reset check
scripts/golem-board.sh gen                   # build/golem.v, build/golem.xdc
scripts/golem-board.sh synth                 # gen + yosys (utilisation in .stat)
scripts/golem-board.sh bit                   # + nextpnr, fasm2frames, xc7frames2bit
scripts/golem-board.sh timing                # the 100 MHz report from the last run
scripts/golem-board.sh dry                   # board + gen only, then the hardware step
```

`gen` writes the design in the PLL wrapper (`Verilog.emitTop`), checks the netlist's
ports against the pin table (`Xdc.check`) and the XDC's pin-line count, and records the
boot image. `synth` runs `synth_xilinx -flatten -abc9 -arch xc7`; if yosys is missing it
says so and leaves the Verilog and XDC in place (the dry-run path). `bit` runs
`nextpnr-xilinx --chipdb … --xdc … --fasm … --sdf …`, `fasm2frames` and
`xc7frames2bit`, and writes `build/a35t/golem.bit`, `golem.timing` and `golem.report`.
`--variant mc` builds `golem_mc`; `--variant both` builds both. `scripts/golem-board.sh`
finds yosys, nextpnr-xilinx, fasm2frames, xc7frames2bit, the chip database, Project
X-Ray's database and fasm2frames' Python modules (prjxray, fasm, pyyaml, simplejson,
intervaltree) on `PATH`, in `ARTY_CHIPDB`/`PRJXRAY_DB_DIR`/`PRJXRAY_PYTHON_DIR`, or in
the Nix store (`GOLEM_YOSYS`, `GOLEM_NEXTPNR`, `GOLEM_FASM2FRAMES`,
`GOLEM_XC7FRAMES2BIT`, `GOLEM_CHIPDB`, `GOLEM_DB` override them).

### The hardware step

The bitstream is loaded into SRAM (not flashed) with

```sh
openFPGALoader -b arty_a7_35t build/a35t/golem.bit
```

then the UART at 1 Mbaud (`stty -F /dev/serial/by-id/usb-Digilent_*-if01-port0 1000000 raw -echo`,
`cat` the port): the default loader prints `wiz-rv boot` and, after the DDR3
calibration, `DDR ok` or `DDR fail`; LD0/LD1 show the same. Then
`rvload PORT prog.bin` (or `rvload PORT doom.bin doom1.wad`) loads a program into DDR
and jumps to it. A failed calibration is visible on the UART and the LEDs, and the
MMIO status register is readable by software.

What remains is the board run itself: place and route at 100 MHz, load the bitstream,
capture the calibration line, and run the C image or Doom over `rvload`. None of the
logic is new: `golem` is the Doom machine's blocks with the bus decode and arbiter in
front of the cache, and the Doom flow already ran this DDR3/OLED pairing on the same
board.


## Doom

The Doom machine (`src/Rv/Doom.wiz`, `doomTop`) already runs Doom on an Arty with this
DDR3 controller and this OLED. golem reuses `doomSysCfg`, so Doom's software sees the
same map: DDR/WAD addresses, UART, cycle counter, sound FIFO, performance counters and
framebuffer are unchanged, and `sw/hw.h` still describes them. What Doom needs from
golem is the board flow: pin constraints and a bitstream (the previous section), and a
decision on the boot image (Doom's `Prog.boot` loader vs. the ROM). The extra bus
decode and arbiter cost a handful of LUTs and one register pair on the path to the
cache; the UART status register is new and unused by Doom. `golem` itself is sized for
the same XC7A35T as `doomTop`; the multi-cycle `golemMc` is the smaller, slower
fallback.
