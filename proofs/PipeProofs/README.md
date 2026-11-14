# Pipelined-core proofs, at retirement

Kernel-checked single-instruction claims for the RV32E pipelined core
(`src/Rv/Pipe.wiz`): from a state with the instruction word in D and E, M, R empty, the
core is after one cycle fetching the specification's next PC, and after three has the
instruction in R with the specification's PC and value for `rd`. The PC, both copies of
the register file, both copies of on-chip memory, and the bubbles' leftovers (`ea`,
`eb`, `mres`, `rval`) are symbolic. `Base.wiz` has the statement and the glue;
`scripts/pipe-proofs.sh` checks every file here (`wiz check -I src -I proofs`).

Two spellings of the claim:

* `Qp.Claim` — the direct one (one `rfl` of the six observed values). A whole-record
  `rfl` costs the checker one evaluation of the three cycles per observed value, so
  these files are about 20 minutes each and need up to 5 GB (FINDINGS.md H10).
* `Qp.ClaimG` — the same proposition with `Qp.obs`'s constructor unfolded, D's word and
  hit as separate arguments, and the pair hypothesis split. Each observed value is one
  field proof; `Qp.Obs.eq6`/`Qp.glueG` assemble the six along the hypothesis without
  re-evaluating a step. These files are seconds to a minute once `Base.wiz` is cached.

| instruction | file | claim | notes |
|---|---|---|---|
| XOR | `Xor.wiz` | `Qp.Claim`, full | one `rfl`, ~20 min / 5 GB |
| OR | `Or.wiz` | `Qp.Claim`, full | one `rfl` |
| AND | `And.wiz` | `Qp.Claim`, full | one `rfl` |
| LUI | `Lui.wiz` | `Qp.Claim`, full | one `rfl` |
| AUIPC | `Auipc.wiz` | `Qp.Claim`, full | one `rfl` |
| XORI | `Xori.wiz` | `Qp.ClaimG`, full | field by field |
| ORI | `Ori.wiz` | `Qp.ClaimG`, full | field by field |
| ANDI | `Andi.wiz` | `Qp.ClaimG`, full | field by field |
| ADD | `Add.wiz` | `Qp.ClaimG`, full | `BitVec.adc` + `adc_zero` |
| ADDI | `Addi.wiz` | `Qp.ClaimG`, full | `BitVec.adc` + `adc_zero` |
| SUB | `Sub.wiz` | `Qp.ClaimG`, full | `BitVec.adc` + `adc_one` |
| SLLI x9, x2, 5 | `Slli.wiz` | `Qp.ClaimG`, full | `BitVec.shlStage` chain (lib/BitVecShift) |
| SRLI x9, x2, 9 | `Srli.wiz` | `Qp.ClaimG`, full | stage chain + `BitVec.and_zero_left` |

Not tractable in the current observation (see FINDINGS.md H10):

* SLL/SRL/SRA: the 32-way split on a symbolic shamt.
* SRAI: the ones fill `Hw.and 1 b` does not reduce in this RTL (the complement-form
  branch `agent/rtl-proof-hooks` is the fix).
* SLT/SLTU: the ALU carry-out comparison bridge (H2 remainder).
* Branches/jumps: `Qp.Obs` compares `val` unconditionally (`we = 0`), and a taken
  branch's next fetch is pc+4 for one cycle (the redirect is registered).
* Loads/stores: `Qp.Obs` does not observe memory, and the memory read-after-write laws
  are H4.

## Running

```sh
JOBS=2 WIZ=/path/to/wiz sh scripts/pipe-proofs.sh    # all instruction files
WIZ=/path/to/wiz sh scripts/pipe-proofs.sh            # WIZ defaults to wiz
```

`Base.wiz` is skipped by the script (it is the shared statement); check it once with
`wiz check -I src -I proofs proofs/PipeProofs/Base.wiz`.
