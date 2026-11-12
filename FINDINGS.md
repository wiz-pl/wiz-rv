# Findings

What building a RISC-V core in Wiz's HDL showed about Wiz, its HDL library and grail.
Each entry says what happened, a minimal reproducer where there is one, and what this
project does instead. Severity: **bug** (wrong behaviour), **gap** (something a
hardware project needs and had to build or work around), **slow** (with timings;
rough: one run each on a shared machine), **papercut** (works, but costs time).

Toolchain: wiz master 50cd3e7 (2026-11-12) + PR #166 (agent/cohesion-hw-mem, memories)
+ PR #199 (agent/hdl-sim-perf, the fast simulator), merged locally (one trivial conflict
in Tests/ElabFix.lean); see README.md, "Toolchain".

## Language and elaborator

### L1. A missing import is reported as "no field 'beq' in a value of type Type" (papercut)

```
def f (a b : String) : Bool := String.beq a b     -- without `import Text`
-- error: no field 'beq' in a value of type Type
```

`String.beq` lives in lib/Text.wiz. The message treats `String.beq` as a field access
on the type `String`. Worse, every later definition that mentions a name from the same
file fails with "unknown identifier 'Asm'" / "no field 'lookup' in a value of type
Type" (the namespace prefix is taken for a value), so one missing import gave 13
errors, none of them at the cause. Wanted: "unknown identifier 'String.beq'", ideally
with "(defined in Text; add `import Text`)".

### L2. `if c then .nil else .cons …` in a `let` without a type does not elaborate (papercut)

```
let ω here := if b then .nil else .cons "x" .nil;   -- error: .cons needs an expected
                                                     --  inductive type, but the expected
                                                     --  type is ?m4 …
```

Writing `let ω here : List String := …` works. (Related to icestick-cpu C6.)

### L3. Accumulator parameters before the colon must be passed unchanged (papercut)

`def go (cyc : Nat) … : Nat → … | .succ fuel, … => go (cyc + 1) …` is rejected with
"recursive call of go must pass the parameter cyc unchanged". Lean has the same rule for
its fixed prefix; here every simulation loop has accumulators, so they all go after the
colon and every clause names them.

## The HDL library

### H1. Memories (#166) and the fast simulator (#199) do not compose (bug, between PRs)

With both branches merged, `import Hdl.Sim` fails:

```
lib/Hdl/Sim.wiz:89:3: error: missing case for constructor memRead
```

(`FastSim.node` matches every `NetOp` but the one #166 adds), followed by six
"unknown identifier 'FastSim'" / "no field 'simFast'" errors. So there was no fast
simulation of a circuit with memories. Reported to main; fixed upstream by #228
(agent/hdl-sim-mem: memories in `Netlist.simFast`), which this project's toolchain now
includes.

### H2. Proofs: what `rfl` sees, and the shape it forces on the circuit (gap)

`src/Rv/Proofs.wiz` proves, by `rfl` plus one generic lemma, that from the decode
phase two cycles of the core (RV32E, at values, every register, the PC, the memory and
the core's leftover registers symbolic) give the specification's PC and rd for XOR, OR,
AND, XORI, ORI, ANDI, LUI and AUIPC. As in icestick-uart C2, this needed the circuit
written for the kernel's evaluation:

* An AND of a control signal (known once the instruction is) and a data-dependent bit
  must be a multiplexer, `gate c x = mux c x 0`: `Hw.and 0 x` with a symbolic `x` is
  `UIntN.land 0 x` and stuck, so with `jump = jal | jalr | (branch & taken)` the next
  PC of an XOR did not reduce. The core uses `gate` in eleven places.
* The adder is one 34-bit addition with the carry in through a low bit (`{a,1} +
  {b',sub}`, shared by add, sub, the comparisons and address computation). Its result
  is `slice 1 32 (…)`, which is not `BitVec.add a b` for a symbolic `a` by evaluation,
  so ADD, ADDI, SUB, SLT, the loads and stores and the branches are not provable this
  way. Wanted: rewriting with bit-vector lemmas (or a bit-blasting decision procedure
  for the 34-bit identity); the alternative, a circuit with separate adder and
  subtractor so that `rfl` sees `BitVec.add`, costs logic cells on an HX1K.
* JAL and JALR check their target's alignment (bit 1 of `pc + imm`), which is symbolic:
  stuck for the same reason.
* Memory reads of the symbolic memory at the symbolic PC cannot be evaluated, so the
  claim takes the hypothesis "memory at PC holds the instruction" and a generic lemma
  (`Pf.ok`) moves it into the execute cycle with `Eq.congrArg`. There is no rewriting
  tactic: the lemma is stated with the execute cycle as an explicit function of the
  four read bytes (`Pf.G`).

### H3. A generic lemma about the core takes minutes to check (slow)

`Pf.ok` (the glue above, for a symbolic instruction word) takes about 150 s in `wiz
check` (one run): the conversion check unfolds two cycles of the core with an unknown
instruction on both sides. Each instruction's `rfl` on the execute cycle takes about
5 s. The same glue written for one fixed instruction took 110 s.

## Compiler and run time

### S1. A program that imports the core takes 12 to 15 minutes to compile (slow)

`grail test` of a `-- test: run` file importing `Rv.Lockstep` (the core, the
specification, the lockstep loop) took 16:58 wall (heavy, 1013 s CPU): the IR step
about 8 minutes, the C step about 6, then the run. A 25-line `wiz build` of a loop that
only runs `coreStep` took 15:48 (845 s CPU) before the link. The IR is 35 000 lines,
14 400 of them `St.unpack` (the derived bundle's unpack for a 20-field state: field k
is `Hw.snd` applied k times, with the type codes rebuilt in every one; main reports
this is about n^2.7 in the number of fields, and an agent is making `deriving Bundle`
emit a chain of lets). `decode` (22 fields) is 2 300 lines, `St.pack` 1 900.

### S2. The compiled value simulation is slower than the kernel's evaluator (slow)

The same lockstep run of `Prog.sum` (76 cycles): under `#eval` in `wiz check` it is
part of a 23 s check of six programs (about 1 100 cycles in all); compiled
(`-- test: run`) it did not finish in grail's 300 s test limit. Main's diagnosis:
closed top-level constants rebuilt every cycle (#207, closed-constants) and the boxed
value simulation (use `simFast`, #228). The tests run under `-- test: check` (by
`#eval`) meanwhile.

## grail

### R1. `grail test --update` records a failed check as the expected output and passes (bug)

When the test file or a module it imports does not check, `grail test X --update`
prints `✓ tests/X.wiz (updated)`, `1 passed`, and writes the *error message* into
`tests/X.expected`. The next `grail test` then passes as long as the error stays the
same. Seen with a type error in `src/Rv/Lockstep.wiz`:

```
- link test-…: skipped (check src/Rv/Lockstep.wiz failed)
  ✓ tests/lockstep.wiz (updated)
1 passed, 0 failed (0 recorded passes)
```

Wanted: a failed check is a failure, with or without `--update`.

## Assembler, in passing

`Int.subNatNat m n` is `m - n`. (This project's own bug: branch offsets came out
negated; the specification ran the wrong program happily. A lockstep against a second
implementation would not have caught it either, since both run the same image: what
caught it was a program whose output was known.)
