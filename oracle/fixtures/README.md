# Oracle fixtures

Each `*.hex` file is a program and the parameters of the trace comparison:

```
<name>
<cfg> <mbits> <steps> <mem_base> <mem_count>
<instruction word, 8 hex digits, little-endian at address 0>
...
```

`cfg` is `rv32i`; the Wiz side uses `Cfg.mk 5 mbits false`, the core uses
`ab = 5, wb = mbits - 2`, and the Python/Sail/Spike sides use the same 16 KB
address space. `steps` is the number of instructions traced, `mem_base` and
`mem_count` select the compared data bytes (`0x2000 … 0x20ff`).

The files are generated (and can be regenerated) by `../scripts/mkfixtures.py`,
which is a tiny assembler only; the programs themselves are the fixtures. They
use base-I encodings only and avoid traps, misaligned accesses, ECALL/EBREAK,
CSRs, the M extension and the I/O port, because those are either Wiz-specific
choices or outside the configured Sail/Spike models.

`alu` and `branch` contain AUIPC, so Spike (which must load the ELF at
`0x80000000`) is skipped for them; the harness says so rather than hiding it.
