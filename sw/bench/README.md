# sw/bench: the headless software benchmark

A freestanding RV32IM benchmark for the wiz-rv DDR machine. It is built from the
machine's own runtime — `../crt0.S`, `../link.ld` and `../syscalls.c` — and runs
unchanged in the host instruction-set simulator (`../iss/iss.c`) or on the board after
`rvload`. `bench.c` is the harness; `kernels.S` has the assembly kernels.

## Build and run

```sh
nix-build nix/iss.nix  -o build/iss       # build/iss/bin/iss
nix-build nix/bench.nix -o build/bench    # build/bench/bench.bin
./scripts/iss-bench.sh                    # run it, check for "bench: PASS"
```

`./scripts/iss-check.sh` builds all three images (ISS, benchmark, Doom) and runs both
this and the Doom smoke test; `make check` is the same.

The ISS loads `bench.bin` at `0x40000000` and starts there. The program is not
position independent: `link.ld` puts `.text` at `0x40000000`, the stack at
`0x44000000` and the heap from `_end`, so a build for one address will not run at
another.

## What it measures

| part | what it exercises | result |
|---|---|---|
| `alu` | shifts by a variable amount, xor/and/add, a data-dependent branch | `618b1400` |
| `mem` | an assembly word copy and sum, byte and halfword loads | `72434b5d` |
| `asm` | the assembly load/add loop alone | `66002200` |
| `muldiv` | `mul`, the 32-cycle restoring divider (`/` and `%`) | `5f609bd4` |
| `sort` | a selection sort of 128 words, then a checksum | `846b12e0` |
| `str` | newlib `memcpy`/`memmove`/`strcpy`/`strlen`/`strcmp`/`memset` on misaligned buffers | `10` |
| `crc` | CRC-32/IEEE, bitwise, over 4096 bytes | `5409eedb` |

Each line prints the result and the section's cycles and instructions from the
machine's counters (`hw_cycles()` and `PERF_INSTR`, `../hw.h`). The section figures do
not add up to the total: the `report` calls (the `printf`s between sections) and the
harness setup are outside the per-section marks but inside the total. The final line is

```
bench: PASS 516655 instructions 3497381 cycles
```

and the ISS's own summary (including newlib start-up and the final print) is

```
[iss] trap after 534575 instructions, 3539494 cycles (0.1 s at 50 MHz)
```

These are the ISS's model of the multi-cycle core: 2 cycles per instruction, +1 for a
load or store, +amount+1 for a shift, +1 for a multiply and +32 for a divide. They are
**not** measurements of the pipelined core and not board numbers. In particular the
fixed shifts in the CRC loop make its ISS CPI about 10; the pipelined core has a
barrel shifter and does not pay that.

The expected results are constants in `bench.c`. They are properties of the
algorithms, so a compiler change that keeps the program correct keeps them; a failure
means the program (or the ISS) is wrong. Update them only with a recorded reason.

## Fixtures and the board path

`nix/bench.nix` produces `bench.elf` and `bench.bin` (72,972 bytes here). The same
`bench.bin` can be loaded by `rvload PORT bench.bin <small file>`; the boot loader's
third argument is the WAD slot at `0x48000000`, but the benchmark ignores it and the
ISS's WAD argument is optional, so a small file is enough. On the board, the cycle
counts come from the same `0x80000010` counter, but the pipelined core's CPI and the
unmodelled DDR/cache behaviour mean the numbers are not comparable with the ISS's.
