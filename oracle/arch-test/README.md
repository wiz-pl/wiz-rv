# The riscv-arch-test suite on the Wiz core

This is the opt-in, bounded part of the RISC-V verification.  The hand-written
fixtures (`oracle/fixtures`) and the lockstep checks in `tests/` exercise one
instruction or one short program; this directory runs the official generated
programs, which check each instruction across many operands, registers and
corners, and compares the test's **signature** with a reference.

## What is vendored, and from where

| suite | source | tests | reference |
|---|---|---|---|
| `I` | [riscv-arch-test] tag `2.0`, `riscv-test-suite/rv32i_m/I` | 38 | the suite's `references/*.reference_output` |
| `M` | tag `2.0`, `riscv-test-suite/rv32i_m/M` | 8 | the suite's `references/*.reference_output` |
| `Zicsr` | [riscv-arch-test] commit `1c3e9f2` (2026), `tests/rv32i/Zicsr` | 6 | `expected/*.sig`, produced by Spike (`oracle/arch-test/arch_test.py reference`) |

[riscv-arch-test]: https://github.com/riscv-non-isa/riscv-arch-test

The 2.0 release has no Zicsr tests; the 2026 suite has no static reference
signatures, so the six Zicsr signatures come from Spike running the same source
with the same minimal environment.  They are checked against `rv32_ref.py` too
(`reference --backend py`), and both agree.

Files:
* `suite/env/{arch_test.h,encoding.h}` — the 2.0 suite environment, verbatim.
* `suite/rv32i_m/{I,M}/{src,references}` — the 2.0 tests and their references.
* `suite/rv32i_m/Zicsr/src` — the six 2026 Zicsr tests.
* `env/model_test.h` — the model hooks for the 2.0 tests.  `RVMODEL_HALT` is
  `EBREAK` (the core stops; the harness reads that as the end of the test); the
  `SPIKE_HALT` build writes `tohost` instead so Spike exits.
* `env/zicsr/riscv_arch_test.h` — a minimal environment for the 2026 tests.
  They normally need a UDB-generated `rvtest_config.h`, trap handlers and PMP
  setup; those are not part of this machine.  The other six macros they use
  (`RVTEST_BEGIN`, `RVTEST_SIGUPD`, `RVTEST_TESTDATA_LOAD_INT`,
  `RVTEST_SIG_SETUP`, …) are implemented here.
* `env/link-core.ld` (address 0 for the core) and `env/link-spike.ld`
  (address `0x80000000`, Spike's DRAM base, for the reference run).

## Changes to the vendored suite

One, and it is a harness gap in the suite, not a test semantic:

* `suite/env/arch_test.h`, `TEST_JALR_OP`: the generated test includes the case
  `rd = x0`, and the macro emitted `LA(x0, 5b)` for it.  Binutils 2.46 rejects
  `la` into `x0` (“illegal operands”); older assemblers accepted it as a no-op.
  The patch emits `nop` when `rd` is `x0`, which is what the accepted encoding
  did.  Without it the whole `jalr-01` test does not assemble.

Nothing else in the suite sources is edited.  The signature comparison includes
the trailing alignment word of the 2.0 signature region (e.g. `add-01` has 584
words: 583 results and the `0x00000000` pad), which is exactly what the suite's
own `+signature` dump compares.

## The machine's Zicsr subset

The core is explicitly “without CSRs” in `README.md`; the Zicsr tests need one
writable CSR.  The implementation adds only what the suite names through
`RVTEST_TEST_CSR`:

* `mscratch` (0x340), and the six CSR instructions (`CSRRW`, `CSRRS`, `CSRRC`,
  `CSRRWI`, `CSRRSI`, `CSRRCI`) with the standard “no write when rs1/uimm is
  zero” rule for the set/clear forms.  Any other CSR number, and the privileged
  `funct3` encodings, remain illegal instructions (cause 3, `mtval` = the word).

It is in both `src/Rv/Isa.wiz` (the specification, `Arch.csr`) and
`src/Rv/Core.wiz` (`CoreSt.csr`, decoded in `Dec.csr`/`Dec.csru`), so the
lockstep checker compares it too.  The pipelined core (`Pipe.wiz`) does not
implement it; its arch-test coverage remains the I/M suite.

**Conflict note.**  Branch `agent/golem-atomics` is editing `src/Rv/Core.wiz`
(atomics: `CoreSt` fields, `Dec`, `coreStep`) and `src/Rv/Isa.wiz`.  This
branch's changes are deliberately additive at the ends of `Arch`, `CoreSt` and
`Dec` and at the end of `coreStep`, so a rebase/merge should be mechanical
(`Arch.mk`, `CoreSt.mk` positional arguments need the new field).

## Commands

The suite is opt-in because it is long (about 15k generated test cases in I/M
alone) and needs a RISC-V toolchain:

```sh
# one-time: build the runner (this is a normal Wiz build; use heavy/light)
wiz build oracle/wiz/arch_run.wiz -I oracle/wiz -I src -o oracle/.build/arch_run

python3 oracle/arch-test/arch_test.py list --suite I,M,Zicsr
python3 oracle/arch-test/arch_test.py run --suite I,M --timeout 240
python3 oracle/arch-test/arch_test.py run --suite Zicsr
python3 oracle/arch-test/arch_test.py crosscheck --suite I,M   # core vs reference vs Spike
python3 oracle/arch-test/arch_test.py reference --suite Zicsr  # check expected/*.sig
python3 oracle/arch-test/arch_test.py selftest                 # the reporter
```

A **clean skip** is exit 0 with `SKIP` lines when `riscv32-none-elf-gcc` or
`oracle/.build/arch_run` is absent; a skipped test is never counted as a pass.
`WIZ_RV_GCC`, `SPIKE` and `DTC` override the tool locations.  The per-test
timeout is `--timeout` (default 180 s) and the fixture's instruction budget is
12× the image's word count + 8192, capped at 400000; a run that does not reach
`EBREAK` is reported as `FUEL`, not as a wrong signature.

## The fixed regression group

`tests/rv/arch-test.wiz` runs a small fixed subset from
`tests/rv/arch-test/*.hex` with the reference signatures in
`tests/rv/arch-test.expected`.  It needs no toolchain, so it can run in CI:

```
grail test 'tests/rv/arch-test'
```

It covers I (ALU, compare, load, store, jump, fence), M (mul, div) and all six
Zicsr instruction forms.  Regenerate it with:

```sh
python3 oracle/arch-test/arch_test.py fixture \
  --tests add-01,lw-align-01,jalr-01,sb-align-01,fence-01,slt-01,mul-01,div-01,\
Zicsr-csrrw-00,Zicsr-csrrs-00,Zicsr-csrrc-00,Zicsr-csrrwi-00,Zicsr-csrrsi-00,Zicsr-csrrci-00
```

The expected file is always the *reference*, never the core's output, so a
regression shows up as a diff rather than being baked into the group.

## Results (2026-11-15)

All numbers are from `arch_test.py run --suite ...` on this worktree.  The full
run is `heavy --mem 4G`; a missing `arch_run`/toolchain is a skip.

| suite | tests | passed | failed | skipped | signature words |
|---|---:|---:|---:|---:|---:|
| `I` | 38 | 38 | 0 | 0 | 12 708 |
| `M` | 8 | 8 | 0 | 0 | 4 708 |
| `Zicsr` | 6 | 6 | 0 | 0 | 1 092 |
| **total** | **52** | **52** | **0** | **0** | **18 508** |

The `crosscheck` command additionally runs Spike on every I/M test and compares
core ↔ official reference ↔ Spike:

```
crosscheck --suite I,M    # 46 passed, 0 failed, 0 skipped
reference --suite Zicsr --backend spike
                          # 6 passed: expected/*.sig == Spike
```

The result is also in `/workspace/wiz-notes/rv-core-proofs.md` §12f.

Triage of the (zero) failures: there were no core bugs to fix.  The one harness
gap found and fixed is the `jalr-01` assembler incompatibility above.  The one
specification change is the bounded Zicsr subset above; it is documented in
`README.md` and `src/Rv/Isa.wiz`.

## Remaining coverage

* No `C` (compressed), `F`/`D`, `A`, or privileged tests.  The core does not
  implement them (the pipelined core's Doom machine uses `I`/`M` only).
* `Zifencei` is not vendored: FENCE.I is a no-op here, and the 2.0 `fence-01`
  test covers fence ordering.
* The fixed regression group deliberately uses small programs; the branch and
  `jal` tests in the full suite unroll to 230 KB–1.75 MB of text (the 2.0
  generator positions branch targets by padding), so their fixtures would be
  large.  They are in the opt-in suite, not in `tests/rv/arch-test`.
* The suite tests the multi-cycle core.  There is no arch-test run of the
  pipelined core (`Pipe.wiz`); its oracle is `oracle/scripts/oracle.py` and
  `tests/plockstep.wiz`.
* `mscratch` only: the Zicsr tests do not test `mstatus`, `mtvec`, `mepc`,
  `mcause`, `mtval`, counters, or the read-only CSR rules.  The machine has no
  privilege modes or trap handler, so those tests are out of scope.
