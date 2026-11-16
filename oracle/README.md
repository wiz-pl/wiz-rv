# The independent oracle for the RV core

This directory is verification infrastructure. It does not change `src/Rv/*.wiz`
or the Wiz HDL library; it drives the existing cores and compares them with
implementations written outside Wiz.

Four implementations of the same RV32I/RV32IM machine are compared on one trace
at a time:

| backend | what it is | always available? |
|---|---|---|
| `isa` | `Rv.Isa`, Wiz's executable specification (`src/Rv/Isa.wiz`), on values | yes (built with `wiz`) |
| `core` | the multi-cycle core `Rv.Core.core`, projected to an architectural state at its E phase | yes (built with `wiz`) |
| `py` | `scripts/rv32_ref.py`, an independent RV32I/M interpreter written from the ISA manual | yes (Python 3) |
| `sail` | `sail_riscv_sim` from [riscv/sail-riscv](https://github.com/riscv/sail-riscv), configured to `rv32i` or `rv32im` | external |
| `spike` | the Spike RISC-V ISS (`--isa=rv32i` or `rv32im`) | external |

`isa` vs `py`, `core` vs `py`, `isa` vs `sail`, `core` vs `sail`, `isa` vs `spike`
and `core` vs `spike` are separate comparisons. All of them are architectural
traces: per instruction, the PC, the trap cause, **all 32 registers**, and the
256 bytes of data memory at `0x2000`. The Wiz sides also emit the rest of the
trap state (`tval`, `epc`) on a `T` line, and the Python reference agrees with it;
Sail/Spike have no such line, so that field is skipped for them.

## What was run (2026-11-14, agent `rv-oracle`)

Worktree `/workspace/wt/rv-oracle`, branch `agent/rv-oracle`, based on the
`wiz-rv` master `9ee43c8` (two `wiz-toolchain` commits on top of `origin/master`
`a4149a5`). The Wiz core was not modified.

```
wiz 0.1.0-dev (071a033a433f93bf9bb54325560506c444a19787)
sail-riscv 0.12                          /nix/store/fxp0v4v6l7smii055kcx1skh58dpy8pk-sail-riscv-0.12
Spike 1.1.1-dev (nixpkgs 1.1.0-unstable-2026-10-20)
                                         /nix/store/bg193gb5vvsgmz8rk0h7bab50igxmp1g-spike-1.1.0-unstable-2026-10-20
```

Build and run (the Wiz builds are ordinary builds; on the shared machine put them
under `light`/`heavy` as the project rules say):

```sh
# the two trace generators (one build each)
light wiz build oracle/wiz/isa_trace.wiz  -I oracle/wiz -I src -o oracle/.build/isa_trace
light wiz build oracle/wiz/core_trace.wiz -I oracle/wiz -I src -o oracle/.build/core_trace

# no external tools: isa/core vs the Python reference (the CI-able test)
oracle/scripts/run-oracle.sh selftest

# with Sail and Spike from nixpkgs (this is how the recorded run was made)
nix shell nixpkgs#sail-riscv nixpkgs#spike -c oracle/scripts/run-oracle.sh run
```

`run-oracle.sh --nix run` is the same `nix shell` invocation. The recorded run
used the store paths directly (`--sail … --spike …`) because the shell was
already resolved.

The rvfi wrapper is additionally checked without riscv-formal: `emit_core`
emits the core with each fixture's program, `mkrvfi.py` wraps it, and Icarus
13.0 simulates the wrapper. The rvfi beats (the post-state of each instruction)
were compared with the Python reference:

```
$ nix shell nixpkgs#iverilog -c oracle/scripts/run-oracle.sh rvfi --fixture alu
PASS alu py-post vs rvfi: 32 beats
```

and likewise 40 beats for `branch` and `mixed`, 32 for `mem` and `shift` — all
five pass, and `iverilog -g2005 -Wall` is clean.

The riscv-formal checks were then run against the pinned revision (see below):

```sh
nix shell nixpkgs#yosys nixpkgs#sby nixpkgs#boolector nixpkgs#iverilog -c \
  oracle/scripts/run-rvfi.sh --all-insns
```

**37/37 `insn_*_ch0` checks pass** (every base-I instruction). `causal_mem_ch0`
passes on the `mixed` fixture, and `reg_ch0`, `pc_fwd_ch0`, `pc_bwd_ch0`,
`causal_ch0`, `unique_ch0`, `liveness_ch0` pass on the all-`lw` core. There were
no assertion failures. The formal run used riscv-formal
`c992aa61fdfe0846c5ed90324c596202a1c69b76` (2026-07-16, fetched read-only,
nothing vendored), yosys 0.70+post, sby 0.70, boolector 3.2.4 and Icarus 13.0.
The 37-check sweep was run under `light` (2 GB cap, the same nix-store `sby`
binaries); the heavy queue was saturated, so a full `heavy` re-run is not claimed.
The exact `nix shell … -c … --sby` command was also run standalone for
`insn_add` and passes.

A `PREUNSAT` (the harness's check cycle not at a retirement, or not at a store
for `causal_mem`) is reported as a failure, not a pass; the two config files used
to align those cycles are `riscv-formal/checks-consistency.cfg` and
`checks-causal-mem.cfg`. Details: `riscv-formal/README.md`.

Recorded result:

```
31 passed, 0 failed, 2 skipped
```

The two skips are Spike on the `alu` and `branch` fixtures: they contain `AUIPC`,
whose result depends on the ELF's load address, and Spike cannot load at 0 (its
boot ROM occupies `[0, 0x1000)`), so those fixtures are Sail/Python-only. A skip
is **not** a pass. Per fixture (states compared / instruction steps):

| fixture | steps | isa-py | isa-sail | isa-spike | core-py | core-sail | core-spike |
|---|---|---|---|---|---|---|---|
| `alu`    | 32 | pass | pass | skip (AUIPC) | pass | pass | skip |
| `branch` | 40 | pass | pass | skip (AUIPC) | pass | pass | skip |
| `mem`    | 32 | pass | pass | pass | pass | pass | pass |
| `mixed`  | 40 | pass | pass | pass | pass | pass | pass |
| `shift`  | 32 | pass | pass | pass | pass | pass | pass |

The `selftest` command additionally perturbs one register in a copy of the
reference trace and requires the comparator to report it, so "the comparator
works" is itself checked.

### Trap fixtures (agent `rv-trap`, 2026-11-14)

The traps and their state are compared by a second set of fixtures. `selftest`
(no external tools) is **33 passed, 0 failed, 0 skipped**: 11 fixtures × (isa,
core, perturbed-comparator check). `run --backends isa,core,py` is **33 passed,
0 failed, 0 skipped**: 11 fixtures × isa-py, isa-core, core-py. The six trap
fixtures each have 7 states (the initial state, the trapping instruction's
pre-state, and five stutters of the stopped state), and the `T` line's
`tval`/`epc` agree between `isa`, `core` and `py` (e.g. `trap_load`: cause 5,
tval 2, epc 4). With Sail in the backend list (`run --backends isa,core,py,sail`,
sail-riscv 0.12) the result is **43 passed, 0 failed, 6 skipped**: Sail agrees on
the five non-trap fixtures and is `SKIP`ped on each trap fixture, because it
enters a trap handler where the Wiz machine stops. Spike was not available here. The emitted core still builds and the rvfi wrapper still simulates:
`rvfi --fixture alu` is 1 passed (32 beats) with Icarus 13.0; the riscv-formal
sweep was not re-run for this change.

## The M extension (2026-11-14, agent `rv-muldiv`)

Worktree `/workspace/wt/rv-muldiv`, branch `agent/rv-muldiv`, based on
`agent/rv-oracle` `2a874fd`. The cores are unchanged; this adds M support to the
harness:

* `mkfixtures.py` encodes `mul`, `mulh`, `mulhsu`, `mulhu`, `div`, `divu`, `rem`,
  `remu` and writes eight `rv32im` fixtures (`INT_MIN`/`INT_MAX`/±1 patterns,
  divide-by-zero, `INT_MIN / -1`, signed truncation, unsigned large operands).
* `rv32_ref.py` enables its M decoder from the fixture cfg; `OracleTrace.wiz`
  turns the cfg into `Cfg.mk 5 mbits m`, and `core_trace.wiz`/`emit_core.wiz`
  pass the same flag to `Rv.Core.core`/`board`.
* `oracle/sail/rv32im.json` is `rv32i.json` with `M.supported = true`; Spike is
  invoked with `--isa=rv32im` for an `rv32im` fixture.

Recorded with wiz `0.1.0-dev (071a033a…)`, sail-riscv 0.12, Spike 1.1.1-dev,
Icarus 13.0 (all under `light`):

```
oracle.py selftest      39 passed, 0 failed, 0 skipped   (13 fixtures × isa/core vs py)
oracle.py run           87 passed, 0 failed, 2 skipped   (the two base-I Spike AUIPC skips)
oracle.py run --fixtures mul,mulh,mulhsu,mulhu,div,divu,rem,remu
                        56 passed, 0 failed, 0 skipped
oracle.py rvfi --fixture mul   1 passed (34 beats)
oracle.py rvfi --fixture div   1 passed (39 beats)
```

The eight M fixtures have seven differential comparisons each (the table omits
`isa` vs `core`, which is also run and passes):

| fixture | steps | isa-py | isa-sail | isa-spike | core-py | core-sail | core-spike |
|---|---|---|---|---|---|---|---|
| `mul`    | 34 | pass | pass | pass | pass | pass | pass |
| `mulh`   | 34 | pass | pass | pass | pass | pass | pass |
| `mulhsu` | 34 | pass | pass | pass | pass | pass | pass |
| `mulhu`  | 34 | pass | pass | pass | pass | pass | pass |
| `div`    | 39 | pass | pass | pass | pass | pass | pass |
| `divu`   | 39 | pass | pass | pass | pass | pass | pass |
| `rem`    | 39 | pass | pass | pass | pass | pass | pass |
| `remu`   | 39 | pass | pass | pass | pass | pass | pass |

The division fixtures take 34 cycles per instruction in the core, so the core
trace's fuel was raised to `80 × steps + 600`; the trace is still one line per E
phase, one line per instruction.

The riscv-formal side is in `riscv-formal/README.md`: the pinned revision has no
check literally named `rvfi_muldiv`, so `run-rvfi.sh --muldiv` runs the eight
`insn_{mul,mulh,mulhsu,mulhu,div,divu,rem,remu}_ch0` checks generated from
`isa rv32im` (`oracle/riscv-formal/checks-muldiv.cfg`). Recorded: **8/8 PASS**,
and `--all-insns` **45/45 PASS** (37 base-I + 8 M), no skips.

## Fixtures

`fixtures/*.hex` are plain text (generated by `scripts/mkfixtures.py`):

```
<name>
<cfg> <mbits> <steps> <mem_base> <mem_count>
<instruction word, 8 hex digits, little-endian at address 0>
...
```

All fixtures are `rv32i|rv32im 14 <steps> 8192 256`: 16 KB of memory, program at
0, and the compared data region `0x2000 … 0x20ff` (outside Spike's boot ROM).
They use only the base-I encodings plus, in the eight `rv32im` fixtures, the M
extension; no `A`/`F`/`D`/`C` and no I/O port. The five
`alu`/`branch`/`mem`/`shift`/`mixed` fixtures and the eight M fixtures have no
traps or misaligned accesses. The six `trap_*` fixtures stop the Wiz machine on
one trap each and are compared between `isa`, `core` and `py`; Sail and Spike are
**skipped** for them, because they enter a trap handler (none is installed) where
the Wiz machine stops, so the harness says `SKIP` rather than pretending they agree.

* `alu` — every ALU form, signed/unsigned compares, shifts by 0/1/31, LUI/AUIPC,
  x0 and same-value writes.
* `branch` — taken/not-taken forms of all six branches, a loop, JAL and JALR.
* `mem` — word/half/byte loads and stores, sign/zero extension, overlapping
  stores and a read-back of the merged word.
* `shift` — shifts by 0, 1, 31 and register amounts ≥ 32 (the low five bits).
* `mixed` — a small loop that stores `3i+1` and reads it back.
* `mul`, `mulh`, `mulhsu`, `mulhu`, `div`, `divu`, `rem`, `remu` — one M
  instruction each over 14 (multiply) or 19 (divide) operand pairs, including
  zero, ±1, `INT_MIN`, `INT_MAX`, divide-by-zero, `INT_MIN / -1` and signed
  truncation. See `fixtures/README.md`.
* `trap_ecall`, `trap_ebreak` — cause 1/2, `tval` 0.
* `trap_illegal` — an all-ones word: cause 3, `tval` the instruction word.
* `trap_load`, `trap_store` — LW/SW at 2: cause 5/6, `tval` the address 2.
* `trap_jump` — JALR to 2: cause 4, `tval` the target 2.

In each trap fixture `epc` is 4 (the second instruction, where the machine stops)
and the trace repeats the stopped state to `steps + 1` lines, as the ISA does.

## The trace format and mismatch reports

`oracle/wiz/OracleTrace.wiz` documents it; a line is

```
S <step> <pc> <cause> <x0> … <x31> <mem byte> …
T <step> <cause> <tval> <epc>          (optional: the Wiz sides and `py`)
```

`<step>` counts instructions and `<pc>`/the registers are the state **before**
instruction `<step>`. `T` is the trap state after that instruction; a backend
without it (Sail, Spike) is not failed on `tval`/`epc`. A mismatch report names the fixture, the step, the pc, the
differing fields, and both values:

```
FAIL alu isa vs py
  alu isa vs py: step 7 (pc 0000001c) differs in 2 field(s)
      x3: 00000002  vs  00000003
      mem[0x2000]: 78  vs  00
  alu isa vs py: … stopping after 10 differing steps
```

`parse_trace`/`compare_traces` in `scripts/oracle.py` are the reference for the
format; `oracle.py diff FIXTURE TRACE` compares a saved trace with the Python
reference.

## The rvfi / riscv-formal shim

`rtl/rvfi_shim.v.in` is an rvfi (RISC-V Formal Interface) wrapper for the emitted
flat Verilog. `scripts/mkrvfi.py` fills in the core module name, the port
instantiation and the byte-lane width, and fails if the internal state names it
depends on (`ph`, `pc`, `q0..q3`, `x1`, `x2`, `rfa`, `m0..m3`, `trap_2`) have
changed.

```sh
light wiz build oracle/wiz/emit_core.wiz -I oracle/wiz -I src -o oracle/.build/emit_core
oracle/scripts/run-rvfi.sh --fixture alu                     # generate + lint the wrapper
oracle/scripts/run-rvfi.sh --instruction add --sby           # one formal check
oracle/scripts/run-rvfi.sh --muldiv                          # the 8 M checks
oracle/scripts/run-rvfi.sh --all-insns                       # all 45 (37 base-I + 8 M)
nix shell nixpkgs#yosys nixpkgs#sby nixpkgs#boolector nixpkgs#iverilog -c \
  oracle/scripts/run-rvfi.sh --all-insns
```

The riscv-formal revision is pinned in `scripts/run-rvfi.sh`:
`c992aa61fdfe0846c5ed90324c596202a1c69b76` (2026-07-16), with yosys 0.70+post,
sby 0.70, boolector 3.2.4 and Icarus 13.0. The clone under
`oracle/.build/riscv-formal` is read-only and checked out at exactly that commit;
nothing is vendored. The formal copy of the core gets combinational debug read
ports (`formal_core.py`) because Yosys cannot resolve the hierarchical memory
references that work in Icarus, and each `insn_*` check runs with a core whose
lane memory is the instruction under test repeated (`formal_insns.py`). The core
source and its simulation Verilog are unchanged.

The wrapper was generated and linted against an emitted core and simulated with
Icarus (see above). The riscv-formal checks are reported separately below; a
`SKIP` (tools absent) is not a pass. `scripts/ci.sh` is the CI/test entry point
and skips cleanly when a build or tool is missing.

## Limits and the next oracle step

* The comparison is over finite traces of base-I/M programs with on-chip memory.
  It covers traps (cause/tval/epc, `isa`/`core`/`py` only) but not the pipeline
  (`Rv.Pipe`), caches/DDR, the bus, the Doom SoC, or the I/O port.
* `Rv.Isa` and the core share one author; `py` and Sail are independent of Wiz's
  code but not of the *machine description* (trap policy, memory map).
* Next: (a) a `PLockstep`-driven pipeline trace in the same format (see §12b of
  `wiz-notes/rv-core-proofs.md`, not part of this branch); (b) drive the fixtures
  from a small random generator (instruction classes and operand corners) instead
  of hand-written programs; (c) the Doom machine's bus/DDR model, which needs a
  different trace projection.
