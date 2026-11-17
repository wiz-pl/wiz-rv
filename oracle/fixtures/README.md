# Oracle fixtures

Each `*.hex` file is a program and the parameters of the trace comparison:

```
<name>
<cfg> <mbits> <steps> <mem_base> <mem_count>
<instruction word, 8 hex digits, little-endian at address 0>
...
```

`cfg` is `rv32i` or `rv32im`. The Wiz side uses `Cfg.mk 5 mbits (cfg = "rv32im")`,
the core uses `ab = 5, wb = mbits - 2` and the same `mx` flag, `py` enables its M
decoder for `rv32im`, and Sail/Spike are given the matching `M` configuration.
`steps` is the number of instructions traced, `mem_base` and `mem_count` select
the compared data bytes (`0x2000 … 0x20ff`).

The files are generated (and can be regenerated) by `../scripts/mkfixtures.py`,
which is a tiny assembler only; the programs themselves are the fixtures. The
base-I and M fixtures avoid traps, misaligned accesses, ECALL/EBREAK, CSRs and the
I/O port, because those are either Wiz-specific choices or outside the configured
Sail/Spike models. The six `trap_*` fixtures deliberately stop the machine on each
trap cause and are compared between `isa`, `core` and `py` only (Sail/Spike enter a
handler, so the harness skips them).

* `alu`, `branch`, `mem`, `shift`, `mixed` — base-I (`rv32i`), as before.
* `mul`, `mulh`, `mulhsu`, `mulhu` — `rv32im`; each defines a prelude of signed
  and unsigned edge constants (0, ±1, `INT_MIN`, `INT_MAX`, `0x12345678`,
  `0x9abcdef0`, `0xdeadbeef`, `0x0badf00d`, `0xffff`, `0x10000`) and applies the
  instruction to 14 operand pairs, including `INT_MIN * -1`, `INT_MIN * INT_MAX`
  and a pair that exercises both halves of the 64-bit product.
* `div`, `divu`, `rem`, `remu` — `rv32im`; the same prelude plus `-7`, `2` and
  `7`, and 19 pairs covering divide-by-zero (divisor x0), `INT_MIN / -1`,
  `INT_MIN / 1`, `1 / INT_MIN`, truncation toward zero (`-7 / 2`, `7 / -2`) and
  unsigned large operands.
* `trap_ecall`, `trap_ebreak`, `trap_illegal`, `trap_load`, `trap_store`,
  `trap_jump` — `rv32i`; one trap each (see `../README.md`).

`alu` and `branch` contain AUIPC, so Spike (which must load the ELF at
`0x80000000`) is skipped for them; the harness says so rather than hiding it.
