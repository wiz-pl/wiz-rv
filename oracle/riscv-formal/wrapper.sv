// The RVFI wrapper that riscv-formal expects: a module named `rvfi_wrapper`
// with `clock`, `reset` and the standard `RVFI_OUTPUTS` port list.
//
// It instantiates the generated `rvfi` module (oracle/rtl/rvfi_shim.v.in, filled
// in by oracle/scripts/mkrvfi.py), which observes the emitted Wiz core and
// produces one beat per retired instruction.  `RVFI_OUTPUTS` and `RVFI_CONN`
// come from riscv-formal's checks/rvfi_macros.vh, which genchecks.py reads
// before this file.
//
// This file is copied into riscv-formal/cores/wiz-rv/ by run-rvfi.sh; it is not
// part of the Wiz core.
module rvfi_wrapper (
  input clock,
  input reset,
  `RVFI_OUTPUTS
);
  rvfi u (
    .clk  (clock),
    .rst  (reset),
    `RVFI_CONN
  );
endmodule
