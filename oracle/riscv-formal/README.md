# riscv-formal and the rvfi wrapper

`riscv-formal` checks an RTL core one instruction at a time against
per-instruction `rvfi` (RISC-V Formal Interface) properties with SymbiYosys. The
wrapper in `../rtl/rvfi_shim.v.in` gives the Wiz core that interface without
touching the core.

## Pinned revision and tools

The harness fetches riscv-formal read-only by commit; it does not vendor the
source and it does not follow a moving branch:

| item | version / commit |
|---|---|
| riscv-formal | `c992aa61fdfe0846c5ed90324c596202a1c69b76` (2026-07-16, “Merge pull request #57 from Peter-Herrmann/doc_cleanup”) |
| yosys | 0.70+post (nixpkgs `yosys-0.70`) |
| sby | 0.70 (nixpkgs `sby-0.70`) |
| boolector | 3.2.4 (nixpkgs `boolector-3.2.4`) |
| iverilog | 13.0 |

The pin is the `PINNED_REV` constant in `../scripts/run-rvfi.sh`; override it with
`--rev`/`RISCV_FORMAL_REV` only deliberately. The clone lives under
`oracle/.build/riscv-formal` (git-ignored) and is checked out at exactly that
commit (`git rev-parse HEAD` is compared before anything runs).

## How the wrapper works

The multi-cycle core (`Rv.Core.core`) has no `rvfi` port, no reset port and no
single retirement cycle: an ALU result is written in E, a load in M, a shift in S,
a product in X and a quotient in V. The wrapper therefore:

1. latches `pc`, the instruction word (`q0..q3`) and the operands (`x1`, `x2`)
   when `ph = E`;
2. emits one `rvfi_valid` beat when the instruction has completed and the core
   is in F, D or H (so the register write, the store and the trap code are final);
3. reads `rvfi_rd_wdata` from the core's register file `rfa[rd]` at that beat,
   and `rvfi_mem_rdata` from the byte lanes `m0..m3` at the access word.

It reads those signals through hierarchical references to the emitted flat
Verilog. `oracle/scripts/mkrvfi.py` checks that every name it needs is still in
the emitted file and fails with a diffable message if a `CoreSt` field was
renamed. `wrapper.sv` is the module riscv-formal expects: `rvfi_wrapper` with
`clock`, `reset` and `` `RVFI_OUTPUTS ``, instantiating `rvfi` through
`` `RVFI_CONN ``.

Reset: the core resets from Verilog `initial` values, not from a reset input.
`rst` is accepted for the interface and ignored. Start the formal run from that
initial state (a BMC from time 0 does) and do not expect `rst` to clear the core.

## The formal harness transformation

riscv-formal's per-instruction checks constrain the core to retire the instruction
under test at a chosen cycle. The Wiz core is emitted with a fixed program image,
so `run-rvfi.sh --instruction <name>` emits a core whose whole lane memory is that
instruction repeated (`formal_insns.py`), and sets `[depth] insn` to that class's
retirement cycle (3 for ALU/control, 4 for loads). That makes each `insn_*` check
non-vacuous without touching the core source; `--all-insns` does this for every
base-I instruction.

Yosys's Verilog parser does not resolve hierarchical references to a memory
(`dut.cpu_rfa[i]`, `dut.cpu_m0[j]`) the way Icarus does: it treats them as an
undriven wire, so the wrapper would see x. For the formal run only,
`formal_core.py` adds combinational read ports to the *copy* of the emitted core —
`dbg_ph`, `dbg_pc`, `dbg_q0..q3`, `dbg_x1/x2`, `dbg_trap`, `dbg_rd → dbg_rfa`,
`dbg_wa → dbg_mem` — and `mkrvfi.py --formal` uses them. The core's datapath,
memories and initial values are unchanged. `run-rvfi.sh` also emits the formal
core with `FORMAL_MBITS=8` (64 byte addresses per lane, 256 bytes total) instead
of the fixture's 16 KB, which keeps the BMC state small; the repeated-instruction
program fills it.

The `check`/`trig` cycles must coincide with a retirement (and `causal_mem`'s
check cycle with a store). The per-instruction depths are chosen by class;
`checks-consistency.cfg` (all-`lw`, retirements at 4, 7, 10, …) and
`checks-causal-mem.cfg` (`mixed`, the store at cycle 21) record the cycles used.
A cycle mismatch is reported by sby as `PREUNSAT`; `run-rvfi.sh` treats that as
`FAIL <check> (ERROR 16 …)`, never as a pass.

## The M extension ("rvfi muldiv")

At the pinned revision there is no check literally named `rvfi_muldiv`. M is
checked by the same `rvfi_insn_check`: with `isa rv32im`, `genchecks.py` generates
`insn_mul_ch0`, `insn_mulh_ch0`, `insn_mulhsu_ch0`, `insn_mulhu_ch0`,
`insn_div_ch0`, `insn_divu_ch0`, `insn_rem_ch0` and `insn_remu_ch0` from the
Sail-derived models in `insns/isa_rv32im.txt`. `run-rvfi.sh --muldiv` runs exactly
those eight; `--instruction <m-op>` selects `checks-muldiv.cfg` automatically and
emits the core with `mx` set (the `rv32im` fixture cfg). The check cycles follow
the core's phase timing:

| class | phases after E | check cycle |
|---|---|---|
| `mul`, `mulh`, `mulhsu`, `mulhu` | X (product written), D | 4 |
| `div`, `divu`, `rem`, `remu` | 32 × V (one quotient bit per cycle), D | 35 |

With the whole lane memory one repeated instruction, the operands are whatever
the preceding copies leave behind (x2 = x3 = 0). For the divide class that means
the formal checks cover the divide-by-zero result (`0xffffffff` for DIV/DIVU, the
dividend for REM/REMU); the non-zero, signed-edge and overflow cases are covered
by the trace oracle (`oracle.py run`, the `mul`…`remu` fixtures), which compares
`Rv.Isa`, the core, Python, Sail and Spike.

## Generate, lint and run

```sh
# in a checkout of wiz-rv:
light wiz build oracle/wiz/emit_core.wiz -I oracle/wiz -I src -o oracle/.build/emit_core

# generate the checks (and lint the wrapper + core) without running them
oracle/scripts/run-rvfi.sh --instruction add --list

# one instruction check, all 45 instruction checks, the 8 M checks, or a subset
oracle/scripts/run-rvfi.sh --instruction add --sby
oracle/scripts/run-rvfi.sh --all-insns
oracle/scripts/run-rvfi.sh --muldiv
oracle/scripts/run-rvfi.sh --instruction mul --sby
oracle/scripts/run-rvfi.sh --instruction lw --sby --checks 'reg_ch0 pc_fwd_ch0 pc_bwd_ch0'
oracle/scripts/run-rvfi.sh --fixture mixed --cfg oracle/riscv-formal/checks-causal-mem.cfg \
  --sby --checks causal_mem_ch0

# the exact toolchain invocation
nix shell nixpkgs#yosys nixpkgs#sby nixpkgs#boolector nixpkgs#iverilog -c \
  oracle/scripts/run-rvfi.sh --all-insns
```

`--verilog CORE --sby` also runs the checks against a core you emitted yourself,
but that core has a fixed program: most `insn_*` checks are then vacuous or hit
`PREUNSAT` because the instruction under test is not at the check cycle. For the
per-instruction checks use `--instruction` (one check, repeated-instruction
program) or `--all-insns`.

`run-rvfi.sh` writes `cores/wiz-rv/` inside the pinned clone with `core.v`,
`rvfi.v`, `wrapper.sv` and `checks.cfg`, runs
`python3 ../../checks/genchecks.py`, then runs `sby -f <check>.sby` for each
target (a simple job pool, `--jobs N`; it does not need the generated makefile,
so `make` is not a dependency of the minimal nix shell). It reports
`PASS <check>` for every `checks/<check>/status` of `PASS` and `FAIL <check>`
with the failing `assert`/`ERROR` lines from the sby log otherwise. A check that
did not produce a status (killed, timed out) is reported as a failure, never as
a pass. A missing tool is a clean `SKIP` (exit 0); a failing check is exit 1.
Check names come from `genchecks.py`; this revision has no check literally named
`rvfi_mem` — memory is covered by `insn_lw_ch0`/`insn_sw_ch0` and
`causal_mem_ch0`.

`../scripts/ci.sh` is the CI/test entry point: it runs the Python/Sail-free
`selftest` when the Wiz trace binaries are built, then the rvfi wrapper lint and
simulation, and with `--formal` the riscv-formal checks. Missing builds or tools
are `SKIP` with exit 0; a real mismatch is `FAIL` with exit 1.

## Results (2026-11-14, revision `c992aa6`)

The checks were run against the emitted multi-cycle RV32I core (the core source
is unchanged). The per-instruction checks use `--instruction <name>`, which emits
a core whose lane memory is that instruction repeated (one encoding per check,
`formal_insns.py`) and sets the check cycle to the retirement cycle of that class
(3 for ALU/control, 4 for loads). The formal copy of the core gets the
`dbg_ph/pc/q*/x*/trap/rfa/mem` read ports (`formal_core.py`) because yosys cannot
resolve the hierarchical memory references that work in Icarus.

```sh
nix shell nixpkgs#yosys nixpkgs#sby nixpkgs#boolector nixpkgs#iverilog -c \
  oracle/scripts/run-rvfi.sh --all-insns
```

* **37/37 base-I `insn_*_ch0` checks PASS** (every instruction in
  `insns/isa_rv32i.txt`: add…xori). Each is a bounded proof at the retirement
  cycle, not a test vector.
* **8/8 M-extension checks PASS** (2026-11-14, agent `rv-muldiv`):
  `insn_mul_ch0`, `insn_mulh_ch0`, `insn_mulhsu_ch0`, `insn_mulhu_ch0` at cycle 4
  and `insn_div_ch0`, `insn_divu_ch0`, `insn_rem_ch0`, `insn_remu_ch0` at cycle 35,
  each on an `rv32im` core emitted from the repeated-instruction fixture. The
  combined sweep (`--all-insns`) is **45/45 PASS, 0 FAIL, 0 SKIP**.
* **`causal_mem_ch0` PASS** on the `mixed` fixture (a store and a load of the
  same word; check cycle 21, a store retirement) — this is the memory-causality
  check; this riscv-formal revision has no check literally named `rvfi_mem`.
* **`reg_ch0`, `pc_fwd_ch0`, `pc_bwd_ch0`, `causal_ch0`, `unique_ch0`,
  `liveness_ch0` PASS** on the all-`lw` core (`checks-consistency.cfg`, cycles
  aligned with the 3-cycle load retirements).
* No assertion failed. A run that reports `PREUNSAT` means the harness's
  `check`/`trig` cycle did not coincide with a retirement (or, for `causal_mem`,
  with a store); that is a harness cycle-choice error, not a core pass, and is
  reported as `FAIL <check> (ERROR 16 …)`, never as a pass. The
  `checks-consistency.cfg`/`checks-causal-mem.cfg` files record the cycles used.

The 37-check sweep was run under `light` (2 GB cap) with the nix-store `sby`
binaries, because the heavy queue was saturated; the exact `nix shell … -c …
--sby` command was also run standalone for `insn_add` and passes. The clone is
read-only and pinned by commit as above; the counts and log summary are in
`../README.md`.


## What is not covered

* No checker for traps/interrupts/CSRs is configured; the core has no privileged
  architecture.
* The M checks use a fixed program of one repeated instruction, so the formal
  proof sees only the zero-operand (for division: divide-by-zero) path; the
  arithmetic corners are tested by the trace oracle, not proved.
* The pipelined core (`Rv.Pipe`) retires at R, not at the multi-cycle E/M/S/X/V
  completion points; it needs a separate wrapper (latent `rr` stage) and has not
  been written here (see §12b of `wiz-notes/rv-core-proofs.md`).
* The Doom SoC (DDR/cache/bus and the frame loop) is not in this formal harness.
