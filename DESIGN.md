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
| `0x4F00_0000` – `0x4FFF_FFFF` | uncached shared aperture | the top 16 MB of DDR: never in a private L1; one bus request per word |
| `0x8000_0000` + `0x00` | UART data | read: the next byte or `-1`; write: send (1 Mbaud, 8N1) |
| `0x8000_0000` + `0x04` | UART status | bit 0 transmitter idle, bit 1 a byte is waiting |
| `0x8000_0000` + `0x08` | hart id | read: this hart's `mhartid` (0 … 3) |
| `0x8000_0000` + `0x10/0x14` | cycle counter | 64 bits, low/high; 100 MHz |
| `0x8000_0000` + `0x30/0x34` | sound FIFO | sample out / free places (PWM on JB1) |
| `0x8000_0000` + `0x40` | DDR status | bit 0 calibration done, bit 1 failed |
| `0x8000_0000` + `0x50 … 0x7c` | performance counters | instructions, bus/memory cycles, cache hits/misses, framebuffer writes, OLED refreshes |
| `0x8000_0000` + `0x80` | OLED controller | the pins and program counter (debug) |
| `0x8000_0000` + `0x90` | `mip` | read: this hart's MSIP/MTIP/MEIP (the `mip` CSR's value, for polling software) |
| `0x8000_1000` + `0x00` | mailbox | per hart: message and valid bit (`+8h`), and the boot entry (`+0x20 + 4h`) |
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
* `GBus.arbN n cap qos` is the N-master form used by `golem_four`: the same contract
  (one request and one answer at a time, the owner holds until its answer) with a
  rotating round-robin pointer, one QoS level per master and a per-master burst cap.
  Each grant advances the pointer, so a master that asks while another is served is at
  most one round away; with `cap = 4` an owner yields after four requests when another
  asks, and an idle set of harts lets the busy one use the bus. The two-master
  `GBus.arb` stays the single-hart fast path, so `golem`/`golemMc` are unchanged;
  `tests/golem_four.wiz` checks the four-hart no-loss and no-starvation properties
  (every window of 20 grants has all four harts).
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
| `MIP` | `0x8000_0090` | read: this hart's `mip` (MSIP/MTIP/MEIP) |
| `ENABLE(c)` | `0x8000_2040 + 4c` | enabled sources of context `c` |
| `THRESH(c)` | `0x8000_2060 + 4c` | the priority threshold of context `c` |
| `CLAIM(c)` | `0x8000_2080 + 4c` | read: take the highest-priority source (0: none); write: complete it |
| `IPI_DATA(h)` | `0x8000_1000 + 8h` | a message for hart `h`; a read takes it and clears its valid bit |
| `IPI_STATUS(h)` | `0x8000_1004 + 8h` | bit 0: a message is waiting |
| `BOOT_ENTRY(h)` | `0x8000_1020 + 4h` | the entry address hart 0 gives hart `h` (0 … 3) |

The `mtimecmp`/`mtime` layout is the standard CLINT's (msip at `+0`, mtimecmp at
`+0x4000`, mtime at `+0xbff8`), rebased from `0x0200_0000` to `0x8000_4000` so that it
stays inside the I/O window. Four contexts, 0 … 3, are the M-mode context of each hart
of `golem_four`; the two-hart machines simply leave 2 and 3 unused. The six sources are
1 the UART's received byte (a live level), 2 hart 0's mailbox, 3 hart 1's mailbox,
4 a spare external input (tied low on this board), 5 hart 2's mailbox and 6 hart 3's
mailbox. A message posted to hart `h` raises source `Intc.mboxSrc h` — 2/3 for harts
0/1 and 5/6 for harts 2/3 — so every hart has a mailbox source in its own context; a
message is also a live level while its valid bit is set. A claim clears the pending bit
and marks the source in service for that context (so a second claim returns 0), a write
to the same claim register (the completion) clears the in-service bit, and a live level
such as the UART's or a still-valid message sets the pending bit again until software
drains it. The context a hart uses is its own hart id.

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
`mstatus.MPIE = mstatus.MIE`, `mstatus.MIE = 0`, `mstatus.MPP = M`, `pc = mtvec` (BASE,
or BASE + 4 × code in vectored mode). `mret` restores `MIE = MPIE` and returns to `mepc`.

Both cores implement this (docs/csr.md: the CSRs, WARL fields, WFI, the halting rule
for exceptions while `mtvec` is 0); `Intc.mip s src h` drives hart h's `In.irqM/T/E`
(docs/plic.md: one PLIC context per hart, `mhartid`). Software may still poll the
read-only `MIP` word or the blocks directly: `MTIME_LO/HI` against `MTIMECMP`,
`IPI_STATUS`, and `PENDING` (`sw/golem.h` has the addresses, the `mip`/`mie` bits and the
helper calls). `tests/golem_intc.wiz` checks the
timer, the UART and mailbox paths in all four contexts, claim/complete, no
cross-context claim, level re-arm, the `mip`/`mie` gating, the priority between MSI and
MTI, and the boot handshake.

### The boot ABI

Reset sets every hart's `pc` to 0 (the boot ROM) and `mhartid` to its index; hart 0 is
the boot hart. The protocol:

1. Hart 0 runs the ROM: it waits for the DDR3 calibration, sets up its own traps, and
   initialises the PLIC for every context (priorities, then enables, then thresholds).
2. For each other hart `h`, hart 0 writes the address of `h`'s entry point to
   `BOOT_ENTRY(h)`, posts a go message to `IPI_DATA(h)` (raising source
   `Intc.mboxSrc h`), then writes 1 to `msip(h)`. These are one store each, in that
   order; the message is the PLIC wake, the doorbell releases the park loop, and the
   entry address is the sticky register.
3. Hart `h`, if `mhartid != 0`, parks before touching anything shared: it polls
   `msip(h)`. When the doorbell reads 1 it reads `BOOT_ENTRY(h)`, clears `msip(h)` by
   writing 0, then polls its own `MIP.MEIP`, claims `PLIC_CLAIM(h)`, reads
   `IPI_DATA(h)` (which clears the valid bit) and completes the source. Then it jumps
   to the entry point. Its stack and its page tables (none, AMP) are the entry point's
   responsibility. This is the software form of interrupt entry until the core has
   CSRs and `mret`.

The core still has no CSR file, so `mhartid` is the read-only MMIO word `HART_ID`
(`0x8000_0008`, `GMap.hartId`); each hart's machine returns its own index. `GProg.golem`
is still a single-hart image; `FProg.four` (`src/Rv/Golem/FourProg.wiz`) is the
four-hart boot and park loop. There is no `wfi` (it needs the CSR file too).

An IPI after boot uses the same registers: `IPI_DATA(h) = msg` posts a 32-bit word and
raises source `Intc.mboxSrc h`; the receiver claims it (`PLIC_CLAIM(h)` in its own
context), reads the word (which clears `IPI_STATUS`), and completes the source. Harts
0/1 therefore use sources 2/3 and harts 2/3 use sources 5/6.

The park loop for hart `h`, with the addresses of `sw/golem.h` (shown for hart 1):

```
    lw   t0, 0x80000008      # HART_ID: mhartid
    beqz t0, boot            # hart 0 boots; harts 1 … 3 park
park:
    lw   t1, 0x80004004      # MSIP(1) for hart 1: 0x80004000 + 4h
    beqz t1, park
    lw   t2, 0x80001024      # BOOT_ENTRY(1): 0x80001020 + 4h
    sw   zero, 0x80004004    # clear the doorbell
plic:
    lw   t3, 0x80000090      # MIP: this hart's interrupt inputs
    andi t3, t3, 0x800       # MEIP
    beqz t3, plic
    lw   t3, 0x80002084      # PLIC_CLAIM(1)
    lw   t4, 0x80001008      # IPI_DATA(1): take the go message
    sw   t3, 0x80002084      # complete the source
    jalr zero, 0(t2)         # enter the program hart 0 placed there
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

## Four harts

`golem_four` is the multi-cycle 4-hart variant of the area study
(`wiz-notes/golem-multicore-area.md`): four independent RV32IM harts, one shared
peripheral set, and one shared DDR. It is the A7-35T configuration — four full-speed
pipelined harts with their 16 KB L1s need 71 RAMB36, 142 % of the 35T, while four
multi-cycle harts fit (39) — and it is an AMP platform, not SMP.

```
  hart 0 core ─ BusA ─ GBus.route ─┐
  hart 1 core ─ BusA ─ GBus.route ─┼─ GBus.arbN (4, round-robin, burst cap 4) ─┐
  hart 2 core ─ BusA ─ GBus.route ─┤                                           │
  hart 3 core ─ BusA ─ GBus.route ─┘                wiz-ddr3 8 KB cache ─ controller ─ PHY ─ DDR3
                                                    ┌───────────────────────┐
  shared peripherals (one instance, 100 MHz):       │ Intc (4 harts, 4 PLIC│
  UART · cycle counter · 96×64 framebuffer · OLED · │ contexts) · IPI · CLINT
```

The code is `src/Rv/Golem/Four.wiz`; the board wrapper is `Golem.four` in
`src/Rv/Golem.wiz` and the boot/ring program is `src/Rv/Golem/FourProg.wiz`. The core is
`Rv.Core` (multi-cycle) with two new parameters:

* `coreStepC … cache` — `cache = false` disables the private L1: every DDR access is
  one bus request, the L1's memories are never written and yosys removes them. The
  single-hart call sites keep `coreStep` (`cache = true`), so `golem`, `golemMc`, the
  Doom machine and the proofs are unchanged. A hart's L1 is selected by `G4.Cfg.l1`
  (one `Bool` per hart): `G4.allL1` is the default, `G4.noL1` is the area cut.
* the uncached shared aperture (`Core.uncBase` = `0x4F00_0000`, 16 MB): an address there
  never hits or fills the L1. It is a property of the *address*, so it works with the L1
  on or off. Mailbox data, flags and any word two harts share belong there; a hart's
  private working set can stay in its L1.

The harts see a clock enable every other cycle (50 MHz effective at the 100 MHz board
clock); the bus, the DDR cache/controller/PHY and the shared peripherals run at
100 MHz. The multi-cycle core is the same one `golemMc` uses, so each hart is ~1
instruction per 2–34 cycles (2 for an ALU instruction); this is the "multi-cycle, not
full rate" limit, and it is why the four-hart target is an AMP/control platform rather
than four Doom-class harts.

### Counts

Yosys `synth_xilinx -flatten -abc9 -arch xc7` for the generated netlists (`build/`, not
checked in), and nextpnr-xilinx 1.0.0 on the Arty chip database:

**These are reported results, not committed artifacts.** No timing report or nextpnr log
is in the tree, and `GOLEM_CHIPDB` is external, so the table cannot be re-derived here.
The newest Fmax recorded in the project notes is 97.5 MHz for the Doom machine
(2026-11-16), below the 100 MHz these designs run at on the board; the 107.30 MHz below
is from an earlier revision and is unverified. See the note in `README.md`.

| variant | LUT | FF | RAMB36 | RAMB18 | DSP48 | nextpnr |
|---|---:|---:|---:|---:|---:|---|
| `golem` (1 pipelined hart) | 5,063 | 3,815 | 23 | 4 | 4 | 107.30 MHz |
| `golem_four` (4 multi-cycle harts, L1 on) | 11,980 | 4,706 | 38 | 5 | 40 | 46.63 MHz (10 ns) / **50.74** (20 ns) |
| `golem_four_nol1` (L1 off) | 10,519 | 4,286 | 22 | 1 | 40 | 47.63 MHz (10 ns) / **52.93** (20 ns) |

`LUT` is the sum of yosys `LUT1 … LUT6` cells (the area study's convention; nextpnr's
`SLICE_LUTX` is 15,398 for `golem_four` and 13,851 for `golem_four_nol1`, because it
counts LUT6 pairs). Against the real 35T capacity: `golem_four` is 58 % LUT, 11 % FF,
**38/50 RAMB36 (76 %)**, 40/90 DSP (44 %); `golem_four_nol1` is 51 % LUT, 10 % FF,
22/50 RAMB36 (44 %), 40/90 DSP. Both fit. The four-hart netlist is within 1 RAMB36 of
the area study's 39-RAMB36 model; the no-L1 cut is within 1 of its 23. The 38 vs 39 is
one shared memory landing in RAMB18 instead of RAMB36.

### Timing: the harts are a 50 MHz (20 ns) target, not 100 MHz

The harts are enabled every other cycle, so the *hart/sys* requirement is a 20 ns
period, not the 10 ns of the single-hart pipelined build. Running nextpnr with a 10 ns
XDC on this design asks it to place and route for a period the harts do not need, and
pessimises the result: it reported 46.63 MHz (`golem_four`) and 47.63 MHz (`nol1`).
With the same netlists and chip database but a **20 ns XDC** (`GBoard.xdc20`), best of
three seeds:

| variant | seed | Fmax (post-route) | at 50 MHz |
|---|---:|:---:|:---:|
| `golem_four` | 1 | 49.36 MHz | FAIL (−0.26 ns) |
| `golem_four` | 3 | 50.62 MHz | PASS (+0.25 ns) |
| `golem_four` | 5 | **50.74 MHz** | **PASS (+0.29 ns)** |
| `golem_four_nol1` | 1 | 48.78 MHz | FAIL (−0.49 ns) |
| `golem_four_nol1` | 2 | 50.99 MHz | PASS (+0.39 ns) |
| `golem_four_nol1` | 3 | **52.93 MHz** | **PASS (+1.11 ns)** |

Both variants close 50 MHz in the best of three: **50.74 MHz (+1.5 %)** for
`golem_four` and **52.93 MHz (+5.9 %)** for `golem_four_nol1`. The close is
seed-sensitive — seed 1 misses by 1.3 % on the full variant — because the router trades
congestion against timing differently per seed; a production build should keep the seed
in the flow (or add margin), not assume any seed closes. The critical path is inside a
hart, not the arbiter or the DDR path; on seed 1 it is 20.26 ns (4.01 ns logic,
16.25 ns routing) and ends at a clock-enable pin of the core.

**Decision: keep one 100 MHz clock domain and the every-other-cycle enable.** The
harts run at 50 MHz effective; the bus, the DDR cache/controller and the shared
peripherals stay at 100 MHz. Any constraint file for a four-hart variant must use the
**20 ns** target, not 10 ns: `GBoard.xdc20` rewrites the board clock constraint and
`GBoard.Variant.target` makes `golem timing` check `PASS at 50.00 MHz` for `four` /
`four_nol1` (the single-hart variants keep 10 ns / 100 MHz). A separate 50 MHz hart
clock is not needed for this target; it remains an option if a future build needs more
margin or must prove the 100 MHz bus and the 50 MHz harts in one constraint file.

**Caveat on the constraint.** The openXC7 report times one clock, `ck_CLKOUT0_g` (the
PLL's system output), so the 20 ns file proves the hart/sys path target. The 100 MHz
bus, DDR cache/controller and shared peripherals are *not* re-proven by this run: the
earlier 10 ns placement is the check for those paths (its only failing path was the
core), and a rigorous single-file sign-off would keep 10 ns for them and use a
multicycle/2-cycle constraint on the hart registers, or a separate 50 MHz hart clock.
The DDR3 PHY's 400 MHz domain is a separate sign-off: it is not derived from this
constraint, and the 7-series chip database in this tree maps `xc7a35t*` to an A7-50T
fabric, so the Fmax is A7-50T timing for a 35T bitstream and optimistic for the real
part. The fit verdicts in this section are the yosys counts against the 35T
capacities.

### Boot, park and the doorbell

Every hart starts at PC 0 in its own 16 KB local RAM and reads `HART_ID` (MMIO offset 8)
for its `mhartid`. Hart 0 is the boot hart: it writes each other hart's entry address to
`BOOT_ENTRY(h)` (`0x8000_1020 + 4h`), posts a go message to `IPI_DATA(h)`
(`0x8000_1000 + 8h`) and then writes 1 to `msip(h)` (`0x8000_4000 + 4h`). Harts 1–3
poll `msip(h)`, read the entry and clear the doorbell; they then wait for their own
`MIP.MEIP`, claim and complete the PLIC source, take the message, and `jalr` there. The
same protocol is the park loop in `FProg.start`; the ring program then uses
`IPI_DATA(h)`/`IPI_STATUS(h)` for the ordered handoff. The `mhartid` register is MMIO,
not a CSR, because `Rv.Core` has no CSR file yet; when it gains one, `mhartid` moves to
the CSR and the MMIO word can stay as a debug alias.

### Limits (read this before claiming SMP)

* **No coherence.** The L1 is private and write-through; a line another hart wrote stays
  stale in it. There is no snoop, no directory and no shared L2. Shared data must go
  through the uncached aperture or a non-shared region; the mailbox/flags are MMIO and
  uncached by construction. The formal statement is the coherence note
  (`/workspace/wiz-notes/golem-coherence-model.md`): cold DDR-only litmus is exactly SC,
  but a private L1 can return stale words (and can livelock a spin), so a warm L1 plus
  shared DDR is not SC.
* **Multi-cycle is not full rate.** Four harts only fit the 35T because the core is
  multi-cycle and (optionally) the L1 is off; the effective rate is ~50 MHz and the IPC
  is the multi-cycle core's (2 cycles per ALU instruction, more for loads, shifts,
  divide). Do not run Doom on all four: Doom is a single-hart workload. A 4-hart
  full-rate build needs the A7-100T (71/135 RAMB36, 20 % LUT) or the L1-off pipelined
  parameter, not this target.
* **`FENCE` and the store buffer.** The multi-cycle core has no store buffer: a store's
  bus phase (`P`) waits for `ready` before the next instruction, so a store followed by
  a flag store is ordered at the shared cache. `FENCE` is decoded and takes one drain
  phase (`Ph.w`); on this core it is a one-cycle ordering point, not a wait for a
  buffer. The pipelined core is different: its one-entry store buffer can let an MMIO
  flag pass a pending DDR store, which is the `ring pipe` anomaly in
  `tests/golem_litmus.wiz`; that is why this target uses the multi-cycle core. A real
  drain fence on `Rv.Pipe` (wait for `bu.sbv == 0` and the bus idle) is a separate
  change.
* **Atomics are at the single point, not in the hart.** LR.W, SC.W and the AMOs are
  decoded (`src/Rv/Core.wiz`) and accepted **only on the uncached aperture**
  (`0x4F00_0000 … 0x4FFF_FFFF`). On-chip RAM is per hart, so an atomic there is done
  locally and is trivially single-hart. An atomic to a *private-cached* DDR line, or to
  MMIO, traps `illegal`; it cannot be made correct while the L1 is incoherent, because
  another hart's store can leave the hart's private copy stale. The shared aperture's
  operations are executed by `GBus.Atom` (`src/Rv/Golem/Bus.wiz`): the engine holds the
  bus owner for the whole operation (`GBus.arbNH`'s `hold`), performs the AMO's read-
  modify-write itself, and keeps the per-hart reservations where it sees every hart's
  store. A reservation is on the 16-byte line; any store, successful SC or AMO to that
  line from any hart clears it. Cost at the cache's one-request rate: LR one read; SC
  one write if the reservation is live (one read then failure if not); AMO one read
  plus one write, and other masters wait while the engine holds the line. The write-
  back of the shared cache to DDR is behind this point, so it is not an invalidation
  event; the private L1 is not in the atomic path at all.
* **Two-hart runs.** The atomics engine (`GBus.Atom`/`GBus.arbNH`) is parameterised
  by the master count and keeps four reservation slots; the model tests it with two
  harts as well as four. The SoC has one four-hart top: a two-hart image parks harts
  2/3 on their doorbells, which is the same hardware with two harts active. There is no
  separate two-hart bitstream at this base (the older `agent/golem-2hart` prototype is
  a different, simulation-only machine).
* **The coherence caveat remains.** Atomics make counters and locks correct at the
  shared point, but they do **not** make the private L1 coherent. Shared data protected
  by a lock must still live in the uncached aperture (or be accessed only after a
  software handoff that guarantees a fresh fill); normal loads/stores to a cached DDR
  line can return stale words. The litmus tests in `tests/golem_litmus.wiz` state this:
  the LR/SC result has exactly one winner, a store by another hart invalidates a
  reservation, and a four-hart AMO sum is exact.
* **One MMIO port per cycle.** The four harts share one UART/Intc/framebuffer decode.
  If two harts write in the same cycle the lowest hart id wins (and the other write is
  dropped); if a read and a write coincide, the write's register is used for the
  interrupt block and the read is non-consuming. Software uses the mailbox rather than
  concurrent MMIO writes; the conflict policy is deterministic, not a lock.
* **Mailbox/PLIC widths.** All four harts have their own `msip`, `mtimecmp` and mailbox
  data/status pair, and each mailbox raises a source in that hart's own context (2/3
  for harts 0/1, 5/6 for harts 2/3). The PLIC has four contexts and six sources. The A
  extension and LR/SC are at the shared point (above), so a shared counter can use an
  AMO instead of a mailbox handoff.
* **No sound or performance counters** on this target (JB is tied low); the UART,
  timer, framebuffer and OLED are shared. The `Intc` test still covers the block.

### Simulation and synthesis

`tests/golem_four.wiz` (check) runs the interconnect with four scripted masters: no lost
or duplicated request, and fairness — every window of 20 grants contains all four harts,
and the grant counts differ by at most the burst cap (4). `tests/golem_four_ring.wiz`
drives the real `Intc` with four hart state machines behind one round-robin MMIO port:
each increments its private counter and passes it through the mailbox in order
h0 → h1 → h2 → h3 → h0, and the final counters are exactly `[20,8,12,16]` with hart 0
setting the done flag (24 cycles). `tests/golem_four_plic.wiz` drives the same real
`Intc` through the boot sequence with four hart machines: hart 0 posts a go message and
rings each doorbell; harts 1/2/3 wake on their own sources (3/5/6), claim, take the
message and complete before entering the ring. `tests/golem_four_litmus.wiz` runs the same ring in
the coherence model's multi-cycle mode and asserts the only allowed outcome is the SC
one, `[4,1,2,3]`. The compiled `Circuit.simFast` run of the four real cores is in
`src/Rv/Golem/FourProg.wiz`'s program but is not a committed test: the netlist
construction for four cores is far over the 60 s test budget in this toolchain (the
same limit `tests/long.wiz` hits).

```
scripts/golem-board.sh gen   --variant four        # build/golem_four.v/.xdc
scripts/golem-board.sh synth --variant four        # yosys: build/golem_four.stat
scripts/golem-board.sh bit   --variant four        # nextpnr + bitstream (optional)
scripts/golem-board.sh gen   --variant four_nol1   # the no-L1 cut
```

## Files

```
src/Rv/Golem/Map.wiz    the memory map: constants, decode predicates, MMIO offsets
src/Rv/Golem/Bus.wiz    GBus.route (decode), GBus.arb (two masters), GBus.arbN (N masters,
                        round-robin/QoS/burst cap), GBus.arbNH (atomic hold),
                        GBus.Atom (shared-point LR/SC/AMO), GBus.ramStep (sim DDR)
src/Rv/Golem/Intc.wiz   the CLINT-like timer, the PLIC-style controller, the inter-hart
                        mailbox, `mip`/`mie` and the boot ABI's registers
src/Rv/Golem/Prog.wiz   the boot ROM: banner, DDR/host/timer checks, three pixels, a DDR call
src/Rv/Golem/Four.wiz   the four-hart SoC: G4.step (four cores, shared MMIO, GBus.arbN,
                        cache), the board-style and behavioural-DDR tops
src/Rv/Golem/FourProg.wiz the four-hart boot/park loop and the mailbox ring program
src/Rv/Golem/CohModel.wiz the abstract N-master memory model behind the litmus tests
src/Rv/Golem.wiz        GIn/GOut, Golem.step (cache + controller + bus + machine),
                        golem / golemMc (board, with the PHY), the reset/LED policy
src/Rv/GolemBoard.wiz   the board circuits: golem, golemMc, golem_four and
                        golem_four_nol1 for Timing.arty, and each variant's netlist
src/Rv/Golem/Board.wiz  the Arty A7-35T board: boot image, PLL clocking, pins, XDC,
                        reset domains and the `golem board` check
src/Rv/GolemSim.wiz     golemSim: the same machine and bus with a behavioural DDR
src/Rv/DPipe.wiz        the pipelined core in the Doom machine (`doomFull`, `simTop`),
                        kept out of Rv.Doom so the simulation test does not compile it
app/golem.wiz           the board flow: gen, synth, bit, timing, dry (`golem …`)
scripts/golem-board.sh  the flow wrapper: finds the tools, refuses to flash unsigned
tests/golem.wiz         the executable simulation (UART bytes and the OLED SPI stream)
tests/golem_intc.wiz    the timer, the external interrupt path and the boot handshake at values
tests/golem_four.wiz    the four-hart interconnect: no loss, and fairness under the cap
tests/golem_four_litmus.wiz the 4-hart mailbox ring in the coherence model (SC only)
tests/golem_four_ring.wiz the four-hart mailbox ring with the real Intc (MMIO, round-robin)
tests/golem_four_plic.wiz the four-hart boot/wake: each hart's PLIC source claims its mailbox
tests/golem_plic_harts.wiz four real cores take MEI through their own PLIC contexts (docs/plic.md)
tests/golem_litmus.wiz  the bus litmus: SC shapes, warm caches, LR/SC, AMO sum
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

There are six checks, one per piece, because each kernel run's state is large
(`tests/golem*.wiz`):

| test | what it runs | checks |
|---|---|---|
| `tests/golem.wiz` | the boot ROM (`GProg.sim`) as a program on the ISA specification (`Rv.run`) | trap 2 (EBREAK), the UART text |
| `tests/golem_oled.wiz` | the framebuffer and the SSD1331 streamer (`OledSim`, the controller at its `pixels` step) | the first six SPI data bytes: red, green, blue (RGB 565, high byte first) |
| `tests/golem_bus.wiz` | `GBus.route`/`arb`/`ramStep` at values | the host writes `0x600d` to DDR[0], the core reads it back, no error |
| `tests/golem_intc.wiz` | `Intc` at values | MTIP rises exactly when `mtime` reaches `mtimecmp` (tick 100), cause 7; `mstatus.MIE` gates it; MSI outranks MTI; the UART and mailbox PLIC paths claim, in-service, complete and re-arm in all four contexts (sources 1, 3, 5 and 6); no cross-context claim; the boot entry and doorbell handshake |
| `tests/golem_plic_harts.wiz` | `Intc` with four real multi-cycle cores | every hart sleeps in WFI with MEIE; hart 0 enables context h for source `mboxSrc h` and posts 100+h; each hart takes MEI (mcause 0x8000000b), claims its own source in its own context (via `mhartid`), reads its message, completes, MRETs and halts; nothing left pending |
| `tests/golem_four_plic.wiz` | `Intc` with four hart state machines | hart 0 enables each context and posts a go message; harts 1/2/3 wake on MEIP and claim sources 3/5/6, take messages 101/202/303 and complete; harts 2/3 have no MEIP before the message |
| `tests/golem_board.wiz` | `GBoard` (the Arty configuration) | 75 pins, 55 top ports, clocks 100/400/400/200 MHz, reset domains as the design |

The boot check is the program on the specification (the core is the multi-cycle one
that `tests/lockstep.wiz` checks against the same specification; the whole machine with
the core is over the cap); the OLED check sets the controller's clock enable every cycle instead of every
16 and preloads the framebuffer with the three pixels, so 200 cycles carry the first
bytes of a frame; the boot ROM also writes those pixels in the board image, but the
specification sends every store with bit 31 set to the output port, so the lockstep
program (`GProg.sim`) leaves the framebuffer out.

The interrupt checks run the `Intc` step function at values (`tests/golem_plic_harts.wiz`
adds four real cores taking the external interrupt through their own PLIC contexts:
docs/plic.md). `golem_intc` posts,
claims and completes through one context at a time; `golem_four_plic` runs four hart
state machines behind one MMIO port: hart 0 enables each context and posts a go
message, and harts 1/2/3 leave the doorbell wait, poll `MIP.MEIP`, claim their own
source, take the message and complete it. The timer half is the single-hart smoke test
M6 asks for: `mtimecmp = 100` makes MTIP and the cause visible exactly at tick 100.

```sh
# the design and the checks, with the toolchain of wiz-toolchain (see README,
# "Toolchain"):
wiz check src/Rv/Golem.wiz   -I src -I ../wiz-ddr3/src
wiz check tests/golem.wiz    -I src -I ../wiz-ddr3/src
wiz check tests/golem_oled.wiz -I src -I ../wiz-ddr3/src
wiz check tests/golem_bus.wiz  -I src -I ../wiz-ddr3/src
wiz check tests/golem_intc.wiz -I src -I ../wiz-ddr3/src
wiz check tests/golem_four_plic.wiz -I src -I ../wiz-ddr3/src
wiz check tests/golem_plic_harts.wiz -I src -I ../wiz-ddr3/src
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
golem intc: timer mtip at tick 100, taken 1, cause 7, rearmed 0, csr 0/3; uart claim 1, again 0, completed 1, pending 2; ipi valid 1, meip 1, claim 3, pending 0, msg 24589; ipi0 [1 1 2 12345 ]; ctx2/3 [1 1 0 5 6 0 0 0 5 8738 13107 ], uart ctx2/3 [1 1 0 1 0 1 ], ext [4 0 4 ]; boot 0 -> 1 entry 1073742080 — PASS
golem four plic: phases [13 5 5 5 ], sources [0 3 5 6 ], messages [0 101 202 303 ], before [0 0 ] — PASS
golem plic harts: 144 cycles; hart 0 [2 2147483659 2 100 0 ] hart 1 [2 2147483659 3 101 1 ] hart 2 [2 2147483659 5 102 2 ] hart 3 [2 2147483659 6 103 3 ]; pending 0 — PASS
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
