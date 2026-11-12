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

### L5. No `\r` in string literals, and the error lands elsewhere (papercut)

```
def s : String := "a\r\nb"   -- error: expected unknown escape sequence \r, term
```

Alone the message points at the literal. Inside a large expression (a program as a
`List.append` of lists, one argument per line) it was reported as "type mismatch
expected: List Asm, inferred: List Asm → List Asm" at the enclosing application and
"expected 'def', …" at the start of the next line, a screen away from the literal.
Here: the assembler's string data turns `\n` into CR LF.

### L6. Recursion on the tail of a nested pattern is not structural (papercut)

```
def pairs : List Nat → List Nat
  | .cons a (.cons b rest) => .cons (a + b) (pairs rest)
  | _ => .nil
-- error: recursive call of pairs on rest, which is not structurally smaller
```

`rest` is a sub-term of the argument two constructors down. Lean accepts this. Here:
a position counter or an `Option` accumulator, one element per call (`Asm.pack`,
`Hex.bytesGo`, `Hex.wordsGo`).

### L7. One global namespace: two packages that define the same name cannot be imported together (gap)

```
-- A/M.wiz: def Foo : Nat := 1          B/N.wiz: def Foo : Nat := 2
import A.M
import B.N        -- error: 'Foo' is declared by both module A.M and module B.N
```

Composing the Doom board top needs wiz-ddr3's controller and this project's core in
one file. Both had a `St` (the controller's state, the core's), a `Tx` (two UART
transmitters), and `Bit`/`B8` (the same definitions, `HwTy.bit` and `HwTy.bits 8`,
still a clash). Here: renamed (`CoreSt`, `UTx`, `W1`, `W8`). Wanted: module-qualified
names, or at least identical re-definitions accepted, or an import that hides or
renames.

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

### H4. A memory at values grows a closure per cycle, written or not (slow; routed to the memories owner)

`HwTy.El (HwTy.mem aw dw)` is a function, and `Hw.memWrite` at values is
`fun b => memUpd we (a == b) d (m b)` whatever `we` is, so a memory that is part of a
circuit's state is a chain of one closure per cycle, and a read walks all of it: a run
of n cycles is O(n^2). Minimal:

```
import Hdl.Core
def zeros : HwTy.El (HwTy.mem 4 8) := fun (a : BitVec 4) => BitVec.ofNat 8 0
-- never writes; reads cell 0
def c : Circuit (HwTy.bits 1) (HwTy.bits 8) := Circuit.mk (HwTy.mem 4 8) zeros (fun m x =>
  Hw.pair (Hw.memWrite m (Hw.lit 1 0) (Hw.lit 4 0) (Hw.lit 8 0)) (Hw.memRead m (Hw.lit 4 0)))
```

The core has six memories (four byte lanes, two register file copies). Compiled, a
loop of `coreStep` (after #207): 100 cycles 0.04 s, 1 000 cycles 0.53 s, 4 000 cycles
3.7 s (one run each), although the program stops after 76 cycles. Long runs here use
the netlist in `Circuit.simFast` (#228) instead.

### H5. One clock: no PLL, no clock divider, no multicycle paths (gap)

On the Arty (xc7a35t, nextpnr-xilinx via artix-target's flow) the RV32IM board design
reached 79 MHz against the 100 MHz oscillator: the execute path (register read data,
the 34-bit adder, the result multiplexer, the register file's write port) is 12.6 ns,
9.1 of it routing. The usual fixes are a slower clock from an MMCM/PLL or a multicycle
constraint; the HDL has a single implicit clock and no way to instantiate a primitive
(MMCME2, PLLE2, BUFG), and the XDC emitter knows no timing exceptions. Here: the whole
design runs at half rate under a clock enable (`Circuit.half` in src/Rv/Board.wiz:
`Circuit.withEnable` and a toggle flip-flop), so every register-to-register path has
two periods, and the UART divider is computed for 50 MHz. The timing report still
checks those paths against 10 ns. Wanted: black-box instances of vendor primitives (a
PLL, at least), more than one clock domain, or `set_multicycle_path` from the enable.

### H6. Checking a half-rate design's timing: what the open flow gives (gap)

The Doom board top runs the core under a half-rate clock enable (H5) next to wiz-ddr3's
full-rate cache, controller and PHY. nextpnr reports one critical path per clock (58.4
MHz here, the core's 2-cycle execute path). Its `set_multicycle_path` (this openXC7
build: by destination cell only, `-to [get_cells -filter {NAME =~ …}]`) changed the
reported Fmax in proportion to the multiplier rather than relaxing the tagged paths,
so it could not separate the classes. What was done instead:

* the full-rate part alone, with the core replaced by a register stub (`stubTop`):
  115 MHz, so every path inside it meets 10 ns;
* the boundary built from registers in both directions (`busStep`, `Edge`), so that a
  crossing path is a register, a few LUTs and a register;
* the crossings measured on nextpnr's SDF (scripts/sdfcross.py): worst 6.0 ns into the
  half-rate part, 6.8 ns out of it, within three cells; every path of the design is at
  most 17.1 ns, under the 20 ns of the 2-cycle paths.

Caveats: nextpnr's SDF gives each LUT of a fractured pair all of the pair's inputs, so
a deeper search follows false arcs between unrelated logic; and the half-rate cells are
found from their enable's connection to the toggle, which misses flip-flops whose
enable yosys folded into the D logic. Wanted: multicycle constraints that work, or more
than one clock domain in the HDL (H5), so that the tools check this.

### H7. A half-rate block RAM wrote garbage with an enable gated by the phase (bug class, fixed)

Under `Circuit.half` a memory's write port becomes `if (half & we) mem[a] <= d` on the
full-rate clock. The phase gate makes the enable 0 at the off-phase edge in steady state,
but `we`, `a` and `d` come from half-rate logic that is still settling at that edge (paths
up to 17 ns of the 20 ns budget), and the AND sits in the same LUT cone. On the board the
OLED framebuffer gained wrong-colour pixels between Doom frames: a hardware count of
decoded framebuffer writes matched what Doom drew exactly, yet the streamer's per-refresh
pixel checksum changed in about 85 of about 100 write-free refreshes per 5 s. Driving the
write port straight from registers (`Fb.we/wa/wd`: the store registered one gated cycle
earlier) took that to about 5 (perhaps an artefact of the checksum at a refresh boundary).
The library could do this itself: `Circuit.half` could register every memory's write
port, or `Hw.memWrite` could take a flag. The regfile (RAM32M), the L1 arrays and the
sound FIFO still have combinational write ports. Moving them needs forwarding, so it
comes with the single-rate pipeline. Repro: `git show` the commit before this entry, on
the board; perf line "oled: refreshes R, odd K".

Correction (later the same day): registering the write port is not the whole story.
Across builds of the same logic the outcome changed with placement: regfb builds gave a
black panel with K about 5 per 5 s (three placements) or a picture with K about 85 (one
placement, as the unregistered build); an Icarus simulation of the same netlist runs
the OLED init and streams correctly, and yosys maps the RAMs identically. So the
half-rate scheme (H5, H6) is timing-marginal somewhere in the OLED controller or the
streamer's read path as well, and the open flow's reports can't pin it down: nextpnr's
single-clock report gives 55-58 MHz, and scripts/sdfsta.py follows false arcs. Once,
synth_xilinx died on `Assert memory_strings.count(...MEMID...)` in OPT_CLEAN on this
design; the rerun passed (yosys 0.70, intermittent). The fix is the single-rate 100 MHz core with
every RAM port from registers and timing closed (the pipeline branch).

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

Later, with the core grown (M extension, 23-field state, the input and output
bundles) and the linear `deriving Bundle` of agent/bundle-unpack in the library: the
same 25-line loop took 35:00 (1992 s CPU) to compile, and `grail test long`
(tests/long.wiz: the core and the Arty board design in `Circuit.simFast`, compiled)
did not get through the IR step within grail's 30-minute job limit ("timed out after
1800 s … and printed nothing"), on a loaded machine. Reported to bundle-unpack (who
suspects the smaller unpack is now inlined into `coreStep` and blows up a later pass).
So the long runs are not in the test suite yet; the Arty demo's RTL was checked
instead by artix-target in Icarus Verilog (3 M cycles, the banner, the self-test and
the primes decoded from the TX line).

### S2. The compiled value simulation is slower than the kernel's evaluator (slow)

The same lockstep run of `Prog.sum` (76 cycles): under `#eval` in `wiz check` it is
part of a 23 s check of six programs (about 1 100 cycles in all); compiled
(`-- test: run`) it did not finish in grail's 300 s test limit. Cause: closed top-level
constants rebuilt every cycle; with #207 (closed-constants) the compiled loop runs 100
cycles in 0.04 s, and what remains is H4. `wiz build` of that loop still took 15:04
(900 s CPU) after #207, so compile time (S1) is what limits compiled tests.

### L4. A meta-level `if` that picks a signal needs a type ascription (papercut; routed to dogfood-fixes)

```
import Hdl.Core
def f {r : HwTy → Type} [Hw r] (mx : Bool) (x : r HwTy.bit) : r HwTy.bit :=
  let y := if mx then Hw.not x else Hw.lit 1 0;
  Hw.and y x
-- 3:37: error: type mismatch  expected: ?m0 r inst✝ x
--   inferred: ?m1 r inst✝ mx x x✝ (.bits 1)
--   (a variable escapes the scope of the hole being solved)
```

`let y : r HwTy.bit := if mx then …` works. This is how a configuration flag (here
`mx`, the M extension) leaves hardware out, so it comes up for every optional unit.

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

Wanted: a failed check is a failure, with or without `--update`. It happened again
with a job that timed out: `grail test long --update` printed `✓ tests/long.wiz
(updated)` and recorded "error: timed out after 1800.000 s (its process group was
killed), and printed nothing" as the expected output.

## Assembler, in passing

`Int.subNatNat m n` is `m - n`. (This project's own bug: branch offsets came out
negated; the specification ran the wrong program happily. A lockstep against a second
implementation would not have caught it either, since both run the same image: what
caught it was a program whose output was known.)
