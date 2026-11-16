# Machine CSRs, traps, interrupts and WFI

The machine-mode subset of the privileged architecture that both cores implement
(`src/Rv/Core.wiz`, the multi-cycle core; `src/Rv/Pipe.wiz`, the 5-stage pipeline) and
the specification models (`src/Rv/Isa.wiz`). M is the only privilege mode.

## The CSRs

| CSR | number | implemented bits (WARL) | reset |
|---|---|---|---|
| `mstatus` | 0x300 | MIE (3), MPIE (7); MPP (12:11) reads 3 | 0x1800 |
| `misa` | 0x301 | reads 0 ("not implemented"), writes ignored | 0 |
| `mie` | 0x304 | MSIE (3), MTIE (7), MEIE (11) | 0 |
| `mtvec` | 0x305 | BASE (31:2), MODE bit 0 (0 direct, 1 vectored); bit 1 reads 0 | 0 |
| `mscratch` | 0x340 | all | 0 |
| `mepc` | 0x341 | 31:2 (bits 1:0 read 0, IALIGN 32) | 0 |
| `mcause` | 0x342 | all | 0 |
| `mtval` | 0x343 | all | 0 |
| `mip` | 0x344 | MSIP/MTIP/MEIP, read-only (the interrupt inputs); writes ignored | — |
| `mvendorid`, `marchid`, `mimpid`, `mconfigptr` | 0xf11 … 0xf15 | read-only 0 | — |
| `mhartid` | 0xf14 | read-only: the hart's number (golem's four-hart SoC), else 0 | — |

A CSR instruction to any other number is illegal, and so is a write (CSRRW, or
CSRRS/CSRRC with rs1 ≠ x0, or their immediates with zimm ≠ 0) to the read-only block
0xc00 … 0xfff. The masks are `Csr.mstatusW`/`mieW`/`mtvecW`/`mepcW` (`Rv.csrWrite`,
`coreCsrWarl`).

## Traps

Exception codes in `mcause` are the standard ones (`Trap.mcause`): ECALL 11, EBREAK 3,
illegal instruction 2, instruction-address misaligned 0, load-address misaligned 4,
store/AMO-address misaligned 6. The internal 3-bit `trap` code (1 … 6, what the boards
show) is unchanged.

Trap entry (`Rv.enterTrap`, `coreTrapMstatus`, `coreVector`): mepc = the PC of the
trapping (or interrupted) instruction, mcause, mtval (the instruction word, the
address or target, or 0), MPIE = MIE, MIE = 0, MPP = M; pc = BASE, or BASE + 4 × cause
for an interrupt in vectored mode. MRET: pc = mepc, MIE = MPIE, MPIE = 1, MPP = M.

### Halting (the one deviation)

While `mtvec` reads 0 an **exception** halts the hart instead of jumping to address 0: the
core stops (`Ph.h`, `Out.trap` the internal code) with mepc/mcause/mtval recorded as the
trap would record them and `mstatus` unchanged (`Rv.stop`). A conformant hart would trap
to address 0. The rule is kept because every test program, the boot ROMs, the oracle
fixtures (`oracle/`, which compare against a halting reference) and the kernel proofs
end with EBREAK on it, and an image at address 0 is the reset code, never a handler. It
affects nothing once software installs a handler. The conformant alternative, if
wanted, is to hardwire the Debug spec's `dcsr.ebreakm = 1` (EBREAK enters debug mode =
halt, every other exception traps to `mtvec` even when it is 0); that changes the
oracle fixtures and the trap proofs, so it is left as a decision.

**Interrupts never halt**: they always go to the vector, `mtvec` = 0 included (the
previous version stopped with an interrupt cause; that was not conformant).

## Interrupts

`mip` = the three inputs (`In.irqM/T/E`; in golem, `Intc.mip` of the hart's own CLINT
bits and PLIC context). An interrupt is taken between instructions when `mstatus.MIE`
and `mip & mie ≠ 0`, highest first MEI, MSI, MTI (`Rv.irqCause`, `coreIrqCode`, the same
order as `Intc.cause`).

* Multi-cycle core: decided in E, before the instruction there executes (`intr`): that
  instruction is not executed and is mepc.
* Pipeline: decided in E (`intrE`) on the instruction there, which then has no effect:
  it travels on as trap code 7 (`Trap.irq`, internal) with the cause in `tval`, and is
  taken at R like an exception, precisely (older instructions complete, younger ones are
  killed, mepc is its PC). A divide already under way is not marked (its divider state
  would be left running); the interrupt waits for it.

## WFI

WFI stalls while no enabled interrupt is pending (`mip & mie = 0`, whatever
`mstatus.MIE`) and then completes as a NOP; it is never itself interrupted, so the
interrupt (if MIE allows it) is taken on the next instruction and mepc = the WFI's PC + 4
(the privileged spec's resume point). With `mie = 0` it stalls for ever, which the spec
allows. In the specification the stall is a step that leaves the state as it is
(`Rv.wfi`); in the cores WFI waits in E (`wait`, `wfiWait`).

## The pipeline's CSR path

A CSR instruction or MRET executes in E only once M is empty (`serial`): every older
instruction has then left M, and the one in R either retires or kills this one, so a CSR
write is never undone by an older trap and is ordered with trap entry at R. The CSR is
read and written in E (through the WARL masks); its old value goes down the pipe as the
result. A trap entry refetches from the vector through the existing restart path
(`fz` 3, `rpc`), as a reset refetches from 0; MRET redirects like a jump to `mepc`.

Previously (8b1177c) the pipeline (a) raised a halt for any trap code left in an invalid
R (every program stopped at cycle 3 with "trap 3", which is why the CSR program and
everything else failed plockstep), (b) took interrupts at R by discarding the instruction
there, which re-executes instructions whose effects had already happened (a store in M,
a CSR write in E, an I/O load), (c) wrote CSRs in E while an older instruction could
still trap, and (d) dropped the first handler instruction (`vDn` 0 on redirect).

## The lockstep checks

`tests/lockstep.wiz` (multi-cycle) and `tests/plockstep.wiz` (pipeline) run, besides the
earlier programs: `Prog.csr` (Zicsr, the WARL masks), `Prog.irq` (ECALL handled and
returned past, the timer interrupt in a loop, WFI waiting for MEIP with MIE off, the
external interrupt once MIE is set, vectored mtvec) and `Prog.irqStress` (the timer
input pulsing during a load/store/branch loop). The CSRs are compared with the
specification at every comparison point.

* Multi-cycle: the specification takes its step in the same cycle as the core's E, and
  is given the same interrupt inputs: interrupt timing is checked exactly. (A WFI's
  stall cycles each count as an "instruction" in the report: E repeats.)
* Pipeline: the specification steps at retirement and is given the interrupt the core
  took (the pending bit of R's trap-7 marker), so it must agree that the interrupt was
  enabled and take it at the same instruction with the same CSR effects; a retiring
  WFI is given `mie` as pending; a CSR read of `mip` is given the value the core read in
  E. What this checks is the architectural effect of every interrupt, not its latency.
  Because CSRs are written in E, they are not compared while a SYSTEM instruction is in
  M or R (they are already ahead), and are compared at every other retirement and at
  the end.

## The trap-entry theorem

Stated for the multi-cycle core, RV32E, 2 KB (the configuration of `src/Rv/Proofs.wiz`),
and proved by `rfl` per instruction word in `src/Rv/TrapProofs/` (Base.wiz, and one file per claim, so
`grail build` checks each claim in its own job):

> Let `a` be any architectural state, and let `b` be `a` with a handler installed
> (`Pf.withH`: running, `mstatus` = 0x1808, `mie` = 0x880, `mtvec` = H = 0x100; the PC,
> registers, memory, `mepc`, `mtval`, `mscratch` and `mcause` stay symbolic). Start the
> core in decode on the word `w` at `b` — its register file, CSR file and `mtval` hold
> `b`'s, its other latches are arbitrary, and the memory at the PC delivers `w`. Then
> after two cycles the core's (pc, mepc, mcause, mstatus, mtval, trap) equal the
> specification's for the same step:
>
> 1. **Exception entry** (`Pf.ecall_enter`, `Pf.ebreak_enter`, `Pf.illegal_enter`):
>    `Rv.exec cfg b w` for ECALL, EBREAK, 0xffffffff: pc = H, mepc = b.pc, mcause =
>    11 / 3 / 2, mtval = 0 / 0 / w, mstatus = 0x1880, still running.
> 2. **MRET** (`Pf.mret_ok`), from inside the handler (`Pf.inH`, mstatus 0x1880):
>    pc = mepc, mstatus = 0x1888, the rest unchanged.
> 3. **Interrupt entry** (`Pf.irq_add`), with MTIP pending (`Pf.withIrq`) and the core's
>    MTIP input high, on ADD x3, x1, x2: `Rv.step cfg b` (given that it fetches the same
>    word): pc = H, mepc = b.pc, mcause = 0x80000007, mtval = 0, mstatus = 0x1880.
> 4. **WFI** (`Pf.wfi_wake`, `Pf.wfi_stall`): with MTIP pending and enabled the WFI
>    completes (pc + 4, no trap entry: the interrupt is the next instruction's); with
>    nothing pending nothing moves and `Rv.step` is the identity.
> 5. **CSR** (`Pf.csrrw_ok`): CSRRW x3, mscratch, x1 gives pc + 4, x3 = the old
>    mscratch, mscratch = x1 (both symbolic).
>
> The halting half (mtvec = 0) is `Pf.TrapClaimAt` in src/Rv/Proofs.wiz, now stated for
> states without a handler (`Pf.noVec`).

Not covered (open): `mstatus`/`mie`/`mtvec` symbolic (trap entry's bit updates are
`Rv.setBit` on numbers in the specification and gates in the core; they meet only at
values — the same bridge as for `BitVec.add`, rv-core-proofs.md §6 item 1); the
interrupt claim does not also state that rd (x3) is untouched; vectored mode; MSI/MEI
priority; and the pipeline (src/Rv/PipeProofs check single instructions from an empty
pipe; a trap-entry claim there is three-plus cycles and the interrupt marker's path
through M and R — the next step, at about 20 minutes of `wiz check` per claim).
