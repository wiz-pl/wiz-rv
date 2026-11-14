# The independent oracle for the RV core

This directory is verification infrastructure. It does not change `src/Rv/*.wiz`
or the Wiz HDL library; it drives the existing cores and compares them with
implementations written outside Wiz.

Five implementations of the same RV32I machine are compared on one trace at a time:

| backend | what it is | always available? |
|---|---|---|
| `isa` | `Rv.Isa`, Wiz's executable specification (`src/Rv/Isa.wiz`), on values | yes (built with `wiz`) |
| `core` | the multi-cycle core `Rv.Core.core`, projected to an architectural state at its E phase | yes (built with `wiz`) |
| `pipe` | the 5-stage pipeline `Rv.Pipe.pipeCore`, projected to the architectural pre-state at retirement (R) | yes (built with `wiz`) |
| `py` | `scripts/rv32_ref.py`, an independent RV32I interpreter written from the ISA manual | yes (Python 3) |
| `sail` | `sail_riscv_sim` from [riscv/sail-riscv](https://github.com/riscv/sail-riscv), configured to `rv32i` | external |
| `spike` | the Spike RISC-V ISS | external |

`isa` vs `py`, `core` vs `py`, `pipe` vs `py`, `isa` vs `sail`, … are separate
comparisons. All of them are architectural traces: per instruction, the PC, the
trap code, **all 32 registers**, and the 256 bytes of data memory at `0x2000`.
The pipeline's sample is also the **pre-state** of the retiring instruction; see
"The pipeline retirement trace" below for the one-word memory detail.

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
# the trace generators (one build each)
light wiz build oracle/wiz/isa_trace.wiz  -I oracle/wiz -I src -o oracle/.build/isa_trace
light wiz build oracle/wiz/core_trace.wiz -I oracle/wiz -I src -o oracle/.build/core_trace
light wiz build oracle/wiz/pipe_trace.wiz -I oracle/wiz -I src -o oracle/.build/pipe_trace

# no external tools: isa/core/pipe vs the Python reference (the CI-able test)
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

## Pipeline extension (2026-11-14, agent `rv-pipeline-oracle`)

Worktree `/workspace/wt/rv-pipeline-oracle`, branch `agent/rv-pipeline-oracle`,
based on `agent/rv-oracle` `2a874fd` (which is based on `wiz-rv` master `9ee43c8`).
The Wiz core is unchanged; this adds the pipeline projection, its fixtures and its
retirement shim.

Tool versions used for the recorded run:

```
wiz/grail 0.1.0-dev (071a033a433f93bf9bb54325560506c444a19787)  [tower, wiz-toolchain]
sail-riscv 0.12        /nix/store/fxp0v4v6l7smii055kcx1skh58dpy8pk-sail-riscv-0.12
Spike 1.1.1-dev        /nix/store/bg193gb5vvsgmz8rk0h7bab50igxmp1g-spike-1.1.0-unstable-2026-10-20
Icarus Verilog 13.0    /nix/store/fvj1mg3g7ihj3sjiyv5khdms6rzhjjm5-iverilog-13.0
python3 3.14 (the interpreter running oracle.py)
```

Commands (each is a single probe, under `light` on the shared machine):

```sh
python3 oracle/scripts/oracle.py build --wiz "$(tower which wiz)"
python3 oracle/scripts/oracle.py selftest
python3 oracle/scripts/oracle.py run \
  --sail /nix/store/fxp0v4v6l7smii055kcx1skh58dpy8pk-sail-riscv-0.12/bin/sail_riscv_sim \
  --spike /nix/store/bg193gb5vvsgmz8rk0h7bab50igxmp1g-spike-1.1.0-unstable-2026-10-20/bin/spike
for f in alu branch hazard mem mixed redirect shift stall; do
  python3 oracle/scripts/oracle.py rvfi --pipe --fixture "$f" \
    --emit-pipe-bin oracle/.build/emit_pipe \
    --iverilog /nix/store/fvj1mg3g7ihj3sjiyv5khdms6rzhjjm5-iverilog-13.0/bin/iverilog
done
```

Recorded results (8 fixtures):

```
selftest                       32 passed, 0 failed, 0 skipped
run (isa,core,pipe,py,sail,spike)
                               87 passed, 0 failed, 3 skipped
rvfi --pipe (8 fixtures)        8 passed, 0 failed, 0 skipped  (33/41 beats each)
```

The three skips are Spike on `alu`, `branch` and `redirect` (AUIPC and Spike's
`0x80000000` load base); those fixtures are Sail/Python-only. A skip is not a
pass. No riscv-formal instruction check is claimed for the pipeline in this
branch; the wrapper is a documented retirement shim (below).

### The pipeline retirement trace

`oracle/wiz/pipe_trace.wiz` drives `Rv.Pipe.pipeCore` at values with `In.idle`
(on-chip memory only) and emits one line per retirement, `rr.v && !rr.miss` —
the same condition as `src/Rv/PLockstep.wiz`. A D- or I-cache miss is replayed,
so it is not a retirement, and a killed instruction never has `rr.v`.

* `pc` is `rr.pc`; registers are `ms.rfa` at R, before its write, so the line is
  the architectural **pre-state** and matches the `isa`/`core` line `step`.
* memory is the on-chip data memory of the **previous** cycle. A store's write is
  registered when the store leaves M and lands at the edge it enters R, so at R
  the memory already contains the retiring store's own bytes. The driver keeps
  the previous cycle's memory (`prev`), which is exactly the pre-state; nothing
  is reconstructed from store data or addresses.
* the trace retires `steps + 1` instructions, so line `steps` is the state after
  the last compared instruction and a fixture may end in `SPIN`.

Typical mismatch report (field by field, the same comparator as the other
backends; illustrative — the recorded run has no mismatch):

```
FAIL hazard pipe vs py
  hazard pipe vs py: step 17 (pc 00000044) differs in 1 field(s)
      x18: 2468a014  vs  2468a013
```

### The pipeline rvfi shim

`oracle/rtl/rvfi_pipe.v.in` + `oracle/scripts/mkrvfi_pipe.py` wrap the emitted
pipeline (from `oracle/wiz/emit_pipe.wiz`) in the rvfi port list. This is a
*documented shim*, not riscv-formal's checker interface, because the pipeline's
R stage carries no instruction word and no next-PC register:

* `rvfi_valid` is the retirement (`rr_v && !rr_miss`), one beat per instruction.
* `rvfi_insn` is the on-chip word at `rr_pc`; `rvfi_pc_rdata` is `rr_pc`;
  `rvfi_rd_addr`/`rvfi_rd_wdata` are the core's `rr_we`/`rr_rd`/`rr_val`.
* `rvfi_pc_wdata` and the memory fields are decoded from the ISA with the
  architectural pre-state values (`R` keeps no next-PC or funct3 register).
  They are useful for the sequence trace, not a substitute for a core port.
* `rvfi_trap` is `rr_trap != 0`; the call does not start `rvfi_muldiv` (no M
  extension in this branch).

The sequence check (`oracle.py rvfi --pipe`) compiles the emitted pipeline +
shim + `rtl/tb_rvfi_pipe.v.in` with Icarus, prints the pre-state at each
retirement, and compares it with the Python trace. It passes on all eight
fixtures (33 beats for the 32-step fixtures, 41 for the 40-step ones), and
`iverilog -g2005 -Wall` is clean. `scripts/run-rvfi.sh --pipe --fixture hazard`
generates and lints the same wrapper; `--sby` there is a clean SKIP with the
explanation (formal pipeline checks are not wired).



## Fixtures

`fixtures/*.hex` are plain text (generated by `scripts/mkfixtures.py`):

```
<name>
<cfg> <mbits> <steps> <mem_base> <mem_count>
<instruction word, 8 hex digits, little-endian at address 0>
...
```

All fixtures are `rv32i 14 32|40 8192 256`: 16 KB of memory, program at 0, and
the compared data region `0x2000 … 0x20ff` (outside Spike's boot ROM). They use
only the RV32I base encodings; no `M`/`A`/`F`/`D`/`C`, no `ECALL`/`EBREAK`, no
traps, and no misaligned accesses. `py` implements the Wiz machine's documented
trap/IO choices as well, but those cases are not compared with Sail/Spike.

* `alu` — every ALU form, signed/unsigned compares, shifts by 0/1/31, LUI/AUIPC,
  x0 and same-value writes.
* `branch` — taken/not-taken forms of all six branches, a loop, JAL and JALR.
* `hazard` — a dependent ALU chain (M→E and R→E forwarding), a store→load, a
  load-use pair, and a branch on the previous instruction's result.
* `mem` — word/half/byte loads and stores, sign/zero extension, overlapping
  stores and a read-back of the merged word.
* `shift` — shifts by 0, 1, 31 and register amounts ≥ 32 (the low five bits).
* `mixed` — a small loop that stores `3i+1` and reads it back.
* `redirect` — a loop with back-to-back branch targets, taken/not-taken branches,
  JAL and JALR (the two instructions after a taken transfer are squashed).
* `stall` — load-use stalls after word, byte and half loads, store→load.

## The trace format and mismatch reports

`oracle/wiz/OracleTrace.wiz` documents it; a line is

```
S <step> <pc> <trap> <x0> … <x31> <mem byte> …
```

`<step>` counts instructions and `<pc>`/the registers are the state **before**
instruction `<step>`. A mismatch report names the fixture, the step, the pc, the
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
oracle/scripts/run-rvfi.sh --all-insns                       # all 37 base-I checks
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

The pipeline has its own shim, `rtl/rvfi_pipe.v.in` + `scripts/mkrvfi_pipe.py`,
described under "The pipeline rvfi shim" above:

```sh
light wiz build oracle/wiz/emit_pipe.wiz -I oracle/wiz -I src -o oracle/.build/emit_pipe
oracle/scripts/run-rvfi.sh --pipe --fixture hazard        # generate + lint
python3 oracle/scripts/oracle.py rvfi --pipe --fixture hazard   # sequence trace
```

It is a documented retirement shim, not a formal checker port; `--sby` is a clean
SKIP for the pipeline in this branch.

## Limits and the next oracle step

* The comparison is over finite traces of base-I programs with on-chip memory.
  `isa`, `core` and `pipe` (and `py`) cover the pipeline at retirement; the M
  extension, caches/DDR, the bus, traps and the I/O port are not in the compared
  traces. The pipeline trace runs with `In.idle`/on-chip memory only.
* The pipeline rvfi shim reports the core's write and trap, but its `pc_wdata`
  and memory fields are decoded from the ISA (R has no next-PC/instruction
  register), so the riscv-formal `insn_*` checks are not run for it. No
  `rvfi_muldiv` in this branch.
* `Rv.Isa` and the cores share one author; `py` and Sail are independent of Wiz's
  code but not of the *machine description* (trap policy, memory map).
* Next: (a) give the pipeline R stage (or a debug port built from E) the
  instruction and next-PC so the real riscv-formal `insn_*` checks can run;
  (b) add M-extension fixtures with a Sail configuration that has `M` and the
  same `rvfi_muldiv` checks; (c) drive the fixtures from a small random
  generator (instruction classes and operand corners) instead of eight
  hand-written programs.
