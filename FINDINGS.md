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
