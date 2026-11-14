# riscv-formal and the rvfi wrapper

`riscv-formal` checks an RTL core one instruction at a time against
per-instruction `rvfi` (RISC-V Formal Interface) properties with SymbiYosys. The
wrapper in `../rtl/rvfi_shim.v.in` gives the Wiz core that interface without
touching the core.

**Status: wrapper tested, checkers not run.** The wrapper was generated from an
emitted core, linted with `iverilog -g2005 -Wall` (clean), and simulated with
Icarus; its rvfi beats matched the independent Python reference on all five
fixtures (32 or 40 beats each). The riscv-formal `insn_ch*`/`rvfi_mem` checkers
themselves were **not** run: `sby` and `yosys` were not available, and no
riscv-formal revision is pinned or claimed here. The check flow below is what to
run, not a result.

## How the wrapper works

The multi-cycle core (`Rv.Core.core`) has no `rvfi` port, no reset port and no
single retirement cycle: an ALU result is written in E, a load in M, a shift in S,
a product in X and a quotient in V. The wrapper therefore:

1. latches `pc`, the instruction word (`q0..q3`) and the operands (`x1`, `x2`)
   when `ph = E`;
2. emits one `rvfi_valid` beat when the instruction has completed and the core
   is in F, D or H (so the register write, the store and the trap code are final);
3. reads `rvfi_rd_wdata` from the core's register file `rfa[rd]` at that beat,
   and `rvfi_mem_rdata` from the byte lanes `m0..m3` at the access word.

It reads those signals through hierarchical references to the emitted flat
Verilog. `oracle/scripts/mkrvfi.py` checks that every name it needs is still in
the emitted file and fails with a diffable message if a `CoreSt` field was
renamed.

Reset: the core resets from Verilog `initial` values, not from a reset input.
`rst` is accepted for the interface and ignored. Start the formal run from that
initial state (a BMC from time 0 does) and do not expect `rst` to clear the core.

## Generate and lint

```sh
# in a checkout of wiz-rv:
wiz build app/rv.wiz -I src -I ../wiz-ddr3/src -o oracle/.build/rvgen
oracle/.build/rvgen gen                 # writes build/rv32im_arty.v and build/rv32e_hx1k.v
oracle/scripts/run-rvfi.sh --verilog build/rv32im_arty.v

# or, if `grail` resolves the package's ../wiz-ddr3 dependency:
grail run rv gen
oracle/scripts/run-rvfi.sh --verilog build/rv32im_arty.v
```

`run-rvfi.sh` always generates `build/rvfi.v`. If `iverilog` is on PATH it lints
`build/rv32im_arty.v` + `build/rvfi.v`; otherwise it skips with the `nix shell`
line. The wrapper is for the standalone core designs (`rv32im_arty`,
`rv32e_hx1k`), not `doom_top`/`doom_sys` (those have bus and IO ports; a Doom
wrapper would need to tie them and is out of scope here).

## Run the checkers

```sh
export RISCV_FORMAL_REV=<the commit you are testing>
nix shell nixpkgs#yosys nixpkgs#sby nixpkgs#iverilog -c \
  oracle/scripts/run-rvfi.sh --verilog build/rv32im_arty.v --sby
```

The script clones `https://github.com/YosysHQ/riscv-formal` at `RISCV_FORMAL_REV`
into `oracle/.build/riscv-formal` (override with `--riscv-formal DIR`), copies
the generated wrapper to `dut/rvfi_wrapper.v` and the core to `dut/core.v`, runs
`make -C checks`, and then `sby -f checks/<check>/<check>.sby` for
`insn_ch0`, `insn_ch1`, `insn_ch2` and `rvfi_mem` when those checks exist in the
revision. Failures print riscv-formal's counterexample trace; keep the trace and
the exact revision in the report.

What the checks mean here: each `insn_ch*` proves that the decoded instruction's
architectural effect (rd, pc, memory) matches the RISC-V specification for that
instruction class, with all other state free. That is independent of both the
Wiz proof (`HwTy.El`) and the trace comparison in `../README.md`; it is the
strongest of the three because it is a proof over all inputs, not a test.

## What is not covered

* No checker for traps/interrupts/CSRs is configured; the core has no privileged
  architecture.
* The M extension would need `rvfi_muldiv` and a configuration with `M`; the
  wrapper exposes the multiplier's result but this has not been run.
* The pipelined core (`Rv.Pipe`) retires at R, not at the multi-cycle E/M/S/X/V
  completion points; it needs a separate wrapper (latent `rr` stage) and has not
  been written.
