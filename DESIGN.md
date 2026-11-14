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
| `0x8100_0000` – `0x8100_2FFF` | framebuffer | 96 × 64 RGB 565, row-major, halfword stores (12 KB) |

Everything is word-addressable except the framebuffer, which the core writes as
halfwords; byte and halfword stores work everywhere the core's memory does. The map is
`src/Rv/Golem/Map.wiz` (hardware constants and the decode predicates) and
`sw/golem.h` (the same for C). It is the Doom machine's map, so Doom's software keeps
working; `golem.h` adds the UART status register.

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

## Files

```
src/Rv/Golem/Map.wiz    the memory map: constants, decode predicates, MMIO offsets
src/Rv/Golem/Bus.wiz    GBus.route (decode), GBus.arb (two masters), GBus.ramStep (sim DDR)
src/Rv/Golem/Prog.wiz   the boot ROM: banner, DDR/host/timer checks, three pixels, a DDR call
src/Rv/Golem.wiz        GIn/GOut, Golem.step (cache + controller + bus + machine),
                        golem / golemMc (board, with the PHY)
src/Rv/GolemSim.wiz     golemSim: the same machine and bus with a behavioural DDR
src/Rv/DPipe.wiz        the pipelined core in the Doom machine (`doomFull`, `simTop`),
                        kept out of Rv.Doom so the simulation test does not compile it
tests/golem.wiz         the executable simulation (UART bytes and the OLED SPI stream)
sw/golem.h              the memory map and MMIO for software
sw/golem.c              a tiny C hello (banner, cycle counter, three rows)
```

The machine itself is `Doom.doomSysCfg` (src/Rv/Doom.wiz), which is `doomSys` with
the OLED timing configuration as a parameter. The OLED configuration is the only
change to that file along with the UART status register; `doomHalf`/`doomFull` and
their tests are unchanged.

## Simulation

The simulation top is `Golem.golemSim` (src/Rv/GolemSim.wiz): the slim machine
(`Mini.machine`: the multi-cycle core, UART, cycle counter, framebuffer and OLED), the
bus and the arbiter, and `GBus.ramStep` in place of the DDR cache, controller and PHY.
The checks run these definitions in the kernel's evaluator (`#eval`), as the lockstep
tests do. Compiling the machine with `Circuit.simFast` is over the 5 GB build cap
(FINDINGS.md, S1 — the core's IR alone takes tens of minutes and gigabytes), so the
executable checks use values and short runs.

There are three checks, one per piece, because each kernel run's state is large
(`tests/golem*.wiz`):

| test | what it runs | checks |
|---|---|---|
| `tests/golem.wiz` | the boot ROM (`GProg.sim`) as a program on the ISA specification (`Rv.run`) | trap 2 (EBREAK), the UART text |
| `tests/golem_oled.wiz` | the framebuffer and the SSD1331 streamer (`OledSim`, the controller at its `pixels` step) | the first six SPI data bytes: red, green, blue (RGB 565, high byte first) |
| `tests/golem_bus.wiz` | `GBus.route`/`arb`/`ramStep` at values | the host writes `0x600d` to DDR[0], the core reads it back, no error |

The boot check is the program on the specification (the core is the multi-cycle one
that `tests/lockstep.wiz` checks against the same specification; the whole machine with
the core is over the cap); the OLED check sets the controller's clock enable every cycle instead of every
16 and preloads the framebuffer with the three pixels, so 200 cycles carry the first
bytes of a frame; the boot ROM also writes those pixels in the board image, but the
specification sends every store with bit 31 set to the output port, so the lockstep
program (`GProg.sim`) leaves the framebuffer out.

```sh
# the design and the checks, with the toolchain of wiz-toolchain (see README,
# "Toolchain"):
wiz check src/Rv/Golem.wiz   -I src -I ../wiz-ddr3/src
wiz check tests/golem.wiz    -I src -I ../wiz-ddr3/src
wiz check tests/golem_oled.wiz -I src -I ../wiz-ddr3/src
wiz check tests/golem_bus.wiz  -I src -I ../wiz-ddr3/src
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

## Hardware

`Golem.golem` (src/Rv/Golem.wiz) is the board circuit: `Ddr3.Board.clocking`'s PLL
clocks (`sys4x`, `sys4xDqs`, `ref200`, `locked`), the PHY, the controller and cache,
the bus, and the machine. It takes `Timing.arty`. The steps to a bitstream are the
Doom machine's (README.md, "Doom"), with `golem` in place of `doomTop`:

1. a board wrapper with the Arty A7-35T's pin constraints: `Ddr3.Board`'s DDR3 pins,
   the UART (`uart_rx`/`uart_tx`), the four LEDs, and JA's eight pins for the OLED
   (`ja` is the PmodOLEDrgb's SPI and control: PMODEN, VCCEN, RES, D/C, SCLK, MOSI,
   CS; the JXADC/Pmod header's 3.3 V and GND);
2. `.grail/bin/rv`'s flow (yosys, nextpnr-xilinx, `Ddr3.Board`'s XDC) or artix-target's
   openXC7 flow, as in scripts/arty-load.sh; the design targets 100 MHz (the pipeline
   placed at 100.12 MHz in `doomTop`; `golemMc` runs the core at 50 MHz effective and
   needs the same DDR/cache paths at 100);
3. the DDR3 calibration: the core is held in reset until `calDone`/`calFail`
   (`Golem.step`), and the boot ROM's `DDR_STATUS` poll waits for it; the board's
   "DDR ok"/"DDR fail" report is the same as the Doom machine's.
4. loading software: the boot ROM at address 0 is the image in the on-chip RAM. The
   ROM in `GProg` is a test image; a board image would replace it with `Prog.boot`
   (the UART loader, `rvload`) or link `sw/golem.c` at 0. The host loader port is
   tied off on the board; the UART loader is the way in.

What remains for hardware, precisely: pin constraints for golem, the PLL/board wrapper
in the flow driver (the pieces exist in wiz-ddr3's `Ddr3.Board` and wiz-rv's Doom
flow), a board build of the pipeline at 100 MHz and a DDR3 calibration run. None of
the logic is new: `golem` is the Doom machine's blocks with the bus decode and arbiter
in front of the cache.

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
