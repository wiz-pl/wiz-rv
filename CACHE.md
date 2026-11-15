# The L1 data cache: model, RTL, checks and integration

Status: 2026-11-15, branch `agent/rv-cache` (from `agent/golem-board` `16993b2`).
No push, no board.

This note is the write-up of an L1 data cache for golem: a pure model, an RTL with the
two write policies, the checks that hold them, the golem simulation with the cache in
it, and the area and timing numbers. The production board image still uses wiz-ddr3's
write-back cache (`Ddr3.Cache`) in front of the controller; this work is the model and
the validated RTL that a later board image can use, and the evidence for the multicore
cache decisions (`wiz-notes/golem-multicore-decisions.md`, M11).

```
core ── CReq/CResp ──▶ L1 (Rv.CacheRtl) ── PortIn/PortOut ──▶ controller / memory
       (32-bit, one request at a time)      (128-bit line)
```

| file | what |
|---|---|
| `src/Rv/Cache.wiz` | the model: lines (valid, dirty, tag, words), `CM.access`, `CM.flat`, `CM.run` |
| `src/Rv/CacheCheck.wiz` | the checks' definitions: exhaustive sequences, random operations |
| `src/Rv/CacheRtl.wiz` | the RTL: the same cache as a circuit, both policies, a behavioural line memory, a random check |
| `src/Rv/Golem/CacheSim.wiz` | the golem simulation with the cache (`Golem.golemCacheSim`, plus a debug output) |
| `proofs/CacheProof.wiz` | the kernel-checked three-access exhaustive claim and a RAW/eviction fixture |
| `tests/cache.wiz` | the model checks and the RTL differential check |
| `tests/golem_cache.wiz` | the core → bus → cache → memory integration |
| `app/cache.wiz`, `scripts/cache-area.sh` | the area and timing flow |
| `scripts/cache-proofs.sh` | the kernel proof |

## 1. The model

`CM.Cfg` fixes a geometry and a policy: `aw` word address bits, `ib` index bits, `wb`
word offset bits (`2^wb` words a line), `dw` data bits a word, `wbMode` (write-back or
write-through), `alloc` (a store miss fills a line or writes the word through). The
model is word-addressed; the RTL's byte strobes are a `strb` mask, one bit a byte.

A line is `valid`, `dirty`, `tag` and its words; the state has the lines and a flat
backing memory. `CM.access` is one complete access and returns the new state, whether it
was a hit, the word read, the bus transactions it performed, and whether it evicted a
dirty line:

* **hit, read**: the line's word; no transaction.
* **hit, write**: merge the bytes into the line; write-back marks it dirty, write-through
  keeps it clean and writes the word to memory.
* **miss, read**: if the victim is dirty, write the victim line back; fill the new line
  from memory; return its word.
* **miss, write, allocate**: as a read miss, then merge the store into the line; a
  write-back line becomes dirty, a write-through line is written through.
* **miss, write, no-allocate**: write the word to memory, leave the resident line alone.

`CM.flat` is the backing memory with every dirty line written back: the memory the core
must see. `CM.run` applies an operation sequence and compares every read with the same
operation on a flat memory and every final memory with it; `CM.runRef` is that flat
reference. `CM.Txn` records the write-backs, fills and write-through words (the model's
bus trace).

The RTL follows the same state machine as wiz-ddr3's cache (states: idle, compare,
writeback, fill, wait, reread, write-through); `wbMode=false` adds the write-through
state and `alloc=false` the no-allocate path. The data and tag RAMs are 512 lines of 16
bytes (8 KB), the same geometry as the production cache; `PortIn`/`PortOut` are the
controller's native 128-bit line port, `CReq`/`CResp` the core's 32-bit port.

## 2. What is checked

The task asks for hit/miss, read-after-write, eviction, and memory consistency. The
checks and the theorem below are about exactly those:

| check | how | result |
|---|---|---|
| hit/miss | every access returns its data from a flat memory; `CM.seqOk` also requires `hits + misses` to count every access | PASS |
| read-after-write | the flat reference is updated by every store; every later read must equal it; the fixture stores, evicts and reads the first word back | PASS |
| eviction | a miss to a valid dirty line writes the victim to memory before reusing the line; `CM.Res.evicted` and the RTL `evictions` counter count it | PASS (17 and 8 in the two write-back runs) |
| memory consistency | after every access `CM.flat` equals the flat reference, and the final memory is compared word for word (or by checksum in the RTL run) | PASS |

**Exhaustive model check.** `CacheCheck.wiz` has an alphabet of two tags at each of two
indices (addresses 0, 4, 8, 12 with two words a line), a write and a read of each, byte
strobes, and enumerates every sequence of four accesses for the four policies
(write-back/write-through × allocate/no-allocate): 4 × 4096 sequences. Every read and
every final memory is compared with a flat memory; a write-through line must be clean.
`tests/cache.wiz` runs it (`CM.exhaustive`).

**Kernel proof.** `proofs/CacheProof.wiz` states the same property for every sequence of
**three** accesses and all four policies, and proves it by `rfl`: `CacheP.all3_ok`. Three
is enough for the interesting shape: a store, a store to the other tag of the same
index (a dirty eviction and write-back), then a read of the first address (a miss and a
fill, or a hit). The file also has a concrete read-after-write/eviction fixture
(`CacheP.raw_ok_true`). `scripts/cache-proofs.sh` checks it (a few seconds).

**Random model check.** 1200 generated accesses (an LFSR, the same one the RTL uses)
for each policy, in a window with two tags at each index so that a write-back run
evicts; every read and the final memory are compared with the flat reference.

**RTL differential check.** `RC.Tb` runs the RTL with a behavioural 128-bit line memory
and a flat reference memory, 400 cycles per policy. Every completed read is compared
with the reference; every read/write updates it; the final memory is compared word for
word with the model's `CM.flat` (4096 words). The write-back runs report 17 and 8 dirty
evictions; the write-through runs report 0, as they must (their lines are clean). The
two independent checks — RTL against the flat reference, model against the flat
reference, and RTL against the model's final memory — are what "validated" means here.

**Golem integration.** `Golem.golemCacheSim` is `GolemSim`'s slim machine, bus and
arbiter with the cache and its line memory in place of `GBus.ramStep`. The program stores
`0x12345678` at DDR[0], reads it back, stores `0x0abcdef1` at DDR word 2048 (line 512,
the same index as line 0, so the store evicts line 0 and must write it back), reads
DDR[0] again, and copies both reads to the on-chip RAM. `tests/golem_cache.wiz` checks
the trap and the two RAM words:

```
golem cache: trap 2, ram64 305419896, ram65 305419896, hits 6, misses 2, evictions 1 — PASS
```

This is a real core → bus adapter → arbiter → cache → memory path; the eviction counter
of 1 is the write-back of line 0. The board image (`Golem.golem`) still uses wiz-ddr3's
cache; swapping the RTL in is one interface unchanged by this work (see §5).

## 3. Assumptions

* **No coherence.** One master owns the cache. A second master's stores are not observed
  until the line is evicted (write-back) or it is the same line and the second master's
  store went through the same cache. There is no snooping, no directory, no
  invalidation port, and no `fence.i`. This is the M2 decision: AMP with uncached shared
  memory/MMIO for communication until a workload needs more.
* **One outstanding request**, 32 bits, held until `ready`/`rvalid` (the core's bus
  adapter already does this). The backside is one 128-bit line at a time.
* **No atomics.** LR/SC and the A extension are not modelled; the RTL is not atomic with
  another master.
* **No MMIO / uncached regions.** The golem decode sends only DDR to the cache; the UART,
  timer, framebuffer and sound are on the core's I/O port, not this bus. A future L1
  would need an uncached window or a bypass.
* **No speculation, no prefetch, no write combining, no store buffer** in the cache. A
  store completes in the cycle its line (write-back hit), or when the controller accepts
  its write-through; the core's store buffer is outside this model.
* **Direct-mapped, no replacement policy.** 512 lines of 16 bytes; the victim is the
  line at the address's index.
* **No ECC, no parity, no TLB/virtual memory, no line locking, no performance
  counters** in the model (the RTL has hit/miss/eviction counters).
* **Word-addressed model, byte strobes.** The model's addresses are word addresses and
  its memory is a list; the RTL uses the 28-bit byte address and 4-byte words. `dw` may
  be less than 32 in the model for a small check; the RTL is 32.
* **The behavioural line memory is 16 KB** (1024 lines) in the tests, a window of the
  256 MB DDR, not the whole device. Full DDR timing and refresh are the controller's
  (`Ddr3.Ctrl`/`Model`), not this cache's.

## 4. Area and timing

Area is yosys `synth_xilinx -flatten -abc9 -arch xc7` on the cache alone (`app/cache.wiz`
writes the Verilog; `scripts/cache-area.sh synth`):

| design | LUT1–6 | FF | block RAM |
|---|---|---|---|
| write-back, allocate | 654 | 195 | 2 RAMB36E1 + 1 RAMB18E1 |
| write-through, allocate | 657 | 195 | 2 RAMB36E1 + 1 RAMB18E1 |
| write-back, no-allocate | 660 | 195 | 2 RAMB36E1 + 1 RAMB18E1 |

(The data RAM is 512 × 128 bits, the tag RAM 512 × 17 bits; the rest is the state
machine and the byte merge/mask. The three variants are within 1 % of each other: the
write-through state and the no-allocate path are a few LUTs.)

The full golem SoC with the cache (the production `Ddr3.Cache` in the board flow; same
8 KB geometry and state machine) synthesises to 5063 LUTs, 3815 FFs, 4 DSP48E1, 23
RAMB36E1, 4 RAMB18E1 and 12 RAM32M. `scripts/cache-area.sh soc` places and routes it for
both Arty devices, with the board's XDC (the A7-100T has the same CSG324 pinout, per
`Hdl.Arty`):

| part | LUT | FF | RAMB36 | utilisation (LUT / FF / RAMB36) | Fmax |
|---|---|---|---|---|---|
| XC7A35T (Arty A7-35T) | 5063 | 3815 | 23 | 24.3 % / 9.2 % / 46 % | **107.30 MHz** (100 MHz target, PASS) |
| XC7A100T (Arty A7-100T) | 5063 | 3815 | 23 | 8.0 % / 3.0 % / 17 % | **108.30 MHz** (100 MHz target, PASS) |

The cache's marginal cost is about 13 % of the SoC's LUTs and 11 % of its block RAMs.
The standalone cache is 3.1 % of an A7-35T's LUTs and 1.0 % of an A7-100T's. All
variants fit both parts with the rest of golem; the 100T leaves much more room for a
second hart (the M8 open question).

A cache-only place-and-route is not run: the top-level cache has about 400 I/O bits
(the core port and the controller port), more than the CSG324's 210 user I/O, so a
standalone P&R needs a pin-constrained wrapper. The full-SoC numbers above bound the
cache's timing in the system; the cache's paths are part of that closure.

## 5. Tests and fixtures

```sh
grail build                       # checks the library and builds the drivers
grail test cache                  # tests/cache.wiz and tests/golem_cache.wiz (about 2 min)
scripts/cache-proofs.sh           # proofs/CacheProof.wiz (kernel-checked)
scripts/cache-area.sh all         # cache Verilog, yosys area, golem P&R on a35t + a100t
```

Fixtures:

* `tests/cache.expected` — the model/RTL report line.
* `tests/golem_cache.expected` — the golem integration line.
* `scripts/cache-area.sh` — `gen`, `synth`, `soc`, `report`; it finds yosys and
  nextpnr-xilinx on PATH or in the Nix store (as `scripts/golem-board.sh` does).
* `build/cache_wb.v`, `cache_wt.v`, `cache_wb_na.v`, `cache.xdc` — the emitted designs.

## 6. What remains

* **Coherence and multicore.** A second hart needs at least invalidation on a shared
  write or an uncached shared region; M2 says no hardware coherence yet. The cache has
  no port for it.
* **Atomics, fences, LR/SC** with another master: the A extension and the memory model
  (M3) are outside this model.
* **Uncached / MMIO windows** and a bypass path, if the cache is moved in front of the
  core's whole bus rather than only DDR.
* **Associativity and replacement** (the current cache is direct-mapped), line locking,
  prefetch, write combining, a store buffer.
* **A formal refinement of the RTL against the model**: the random differential check is
  not a proof; a per-state simulation relation, or a BFS over the reachable RTL states
  for a small geometry, is the next step.
* **Cache-only P&R** with a pin-constrained wrapper, and a board image that uses this
  RTL instead of `Ddr3.Cache` (the interface is the same; the board flow's `Golem.step`
  calls `C.step` directly).
* **Performance counters and a workload** (hit rate, CPI with/without) on the board;
  the Doom numbers in `README.md` (CPI 1.8, about half the cycles in a bus access) are
  the baseline.
* **The core's own L1** (`Core.wiz`/`Pipe.wiz`: unified, write-through, no allocation)
  is a second cache in the DDR path; this model is the cache in front of the controller.
  A future split (L1 in the core, L2 here) needs the two policies reconciled.

## 7. Findings

These are recorded in `FINDINGS.md` too:

* **A 512-line behavioural memory aliases line 512 to line 0.** The first golem
  integration read the evicting line's word back instead of line 0; the memory window
  must cover every line the test uses (1024 lines for a 2048-word window).
* **The test counter was the pre-edge value** (`ops`/`bad`), so the model ran one fewer
  operation than the RTL and reported a false failure at the end of a run.
* **`A.sw`'s immediate is 12-bit signed**: `A.sw 7 8192 11` assembles as offset 0. The
  eviction test uses a second base register (`lui x12, 0x40002`) instead.
* **One global namespace**: importing both `Rv.Golem.Mini` and `Ddr3.Model` clashes on
  `MSt`; `CacheRtl` avoids `Ddr3.Tb`/`Ddr3.Model` by keeping its own last/zeros helpers.
* **Auto-share picks an ill-kinded instance** when a test `let`-binds a `Circuit`/state
  and projects it; the integration test exposes the RAM words as debug outputs instead
  (`Golem.golemCacheSimDbg`), and the proof/test functions use `let ω`.
* **The address window was biased** to two tags at 16 indices so the RTL random check
  actually evicts; with a uniform 12-bit window the runs had no evictions at all.
