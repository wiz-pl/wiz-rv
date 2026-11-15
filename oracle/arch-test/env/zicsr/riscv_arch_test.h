/* Minimal riscv-arch-test environment for the vendored rv32i/Zicsr sources.
 *
 * The 2026 suite's generated Zicsr tests include "riscv_arch_test.h" and expect a
 * UDB-generated `rvtest_config.h`, trap handlers, PMP setup, and so on.  This machine
 * has none of that: it is a machine-mode RV32I core that stops on a trap, with one
 * writable CSR, `mscratch` (0x340), which is exactly the "test CSR" the suite's
 * generated tests use through RVTEST_TEST_CSR.  The tests only read and write that
 * CSR, so the macros below are the subset they need.
 *
 * Layout: `begin_signature` is `SIGUPD_COUNT` words of 0xdeadbeef and is the initial
 * x2; every RVTEST_SIGUPD stores one word and advances x2.  `rvtest_data_begin` is the
 * initial x3 and RVTEST_TESTDATA_LOAD_INT walks the .word data that follows
 * RVTEST_DATA_BEGIN.  The reference signatures in expected/ were produced by Spike
 * from the same source and the same layout (see oracle/arch-test/README.md).
 */
#ifndef _WIZ_RISCV_ARCH_TEST_H
#define _WIZ_RISCV_ARCH_TEST_H

#define XLEN 32
#define REGWIDTH 4
#define SIG_STRIDE 4
#define SREG sw
#define LREG lw
#define LI(reg, val) li reg, val
#define LA(reg, val) la reg, val

#ifndef SIGUPD_COUNT
#error "SIGUPD_COUNT must be defined by the test"
#endif

/* mscratch: the writable machine CSR that RVTEST_TEST_CSR names for this target. */
#define RVTEST_TEST_CSR 0x340

.macro RVTEST_BEGIN
  .section .text.init
  .globl rvtest_entry_point
rvtest_entry_point:
  .option push
  .option norelax
  la x2, begin_signature
  la x3, rvtest_data_begin
  .option pop
.endm

.macro RVTEST_CODE_END
  .p2align 2
  .globl rvtest_code_end
rvtest_code_end:
#ifdef SPIKE_HALT
  li t0, 1
  la t1, tohost
  sw t0, 0(t1)
1: j 1b
#else
  ebreak
#endif
.endm

.macro RVTEST_DATA_BEGIN
  .data
  .p2align 4
  .globl rvtest_data_begin
rvtest_data_begin:
.endm

.macro RVTEST_DATA_END
  .globl rvtest_data_end
rvtest_data_end:
.endm

.macro RVTEST_SIG_SETUP
  .data
  .p2align 4
  .globl begin_signature
begin_signature:
  .fill SIGUPD_COUNT, 4, 0xdeadbeef
  .globl end_signature
end_signature:
.endm

#define RVTEST_TESTDATA_LOAD_INT(_P, _R) \
  LREG _R, 0(_P);                        \
  addi _P, _P, SIG_STRIDE

#define RVTEST_SIGUPD(_SIG, _LINK, _TEMP, _R, _INST, _STR) \
  SREG _R, 0(_SIG);                                        \
  addi _SIG, _SIG, SIG_STRIDE

#endif

#ifdef SPIKE_HALT
  .data
  .align 3
  .globl tohost
tohost: .dword 0
  .globl fromhost
fromhost: .dword 0
#endif
