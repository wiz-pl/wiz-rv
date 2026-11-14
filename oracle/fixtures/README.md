# Oracle fixtures

Each `*.hex` file is a program and the parameters of the trace comparison:

```
<name>
<cfg> <mbits> <steps> <mem_base> <mem_count>
<instruction word, 8 hex digits, little-endian at address 0>
...
```

`cfg` is `rv32i`; the Wiz side uses `Cfg.mk 5 mbits false`, the multi-cycle core
uses `ab = 5, wb = mbits - 2`, and the Python/Sail/Spike sides use the same 16 KB
address space. `steps` is the number of instructions traced, `mem_base` and
`mem_count` select the compared data bytes (`0x2000 … 0x20ff`).

The files are generated (and can be regenerated) by `../scripts/mkfixtures.py`,
which is a tiny assembler only; the programs themselves are the fixtures. They
use base-I encodings only and avoid traps, misaligned accesses, ECALL/EBREAK,
CSRs, the M extension and the I/O port, because those are either Wiz-specific
choices or outside the configured Sail/Spike models.

The pipeline trace retires `steps + 1` instructions (line `step` is the pre-state
of instruction `step`), so a fixture may end in `SPIN` (`jal x0, 0`): the spin is
an ordinary instruction and keeps the trace long enough.

* `alu` — every ALU form, signs, shifts, LUI/AUIPC, x0.
* `branch` — all six branches (taken and not taken), a loop, JAL and JALR.
* `hazard` — a dependent ALU chain (M→E and R→E forwarding), a store→load, a
  load-use pair, and a branch on the previous instruction's result.
* `mem` — byte/half/word loads and stores, sign/zero extension, overlap.
* `mixed` — a loop that stores `3i+1` and reads it back.
* `redirect` — a loop with back-to-back targets, taken/not-taken branches, JAL
  and JALR (the two instructions after a taken control transfer are squashed).
* `shift` — shift amounts 0, 1, 31 and ≥ 32 (the low five bits).
* `stall` — load-use stalls after word, byte and half loads, store→load.

`alu`, `branch` and `redirect` contain AUIPC, so Spike (which must load the ELF
at `0x80000000`) is skipped for them; the harness says so rather than hiding it.
