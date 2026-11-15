/* The model hooks for the vendored RISC-V arch-test v2.0 sources.
 *
 * The suite's own targets are simulators with a tohost/fromhost HTIF channel; this
 * machine has neither.  The core build therefore stops the machine with EBREAK on
 * `RVMODEL_HALT`, which the arch-test harness reads as the end of the test.  The
 * `SPIKE_HALT` build (used only to make Spike's reference signature) writes to
 * `tohost` instead, because Spike exits on that store.  Both builds have the same
 * code and data before the halt sequence, so their signatures are comparable.
 *
 * No CSRs are touched here: the vendored I and M tests do not define
 * `rvtest_mtrap_routine`, so `RVTEST_CODE_BEGIN`/`_END` do not install a trap
 * handler.
 */
#ifndef _COMPLIANCE_MODEL_H
#define _COMPLIANCE_MODEL_H

#define RVMODEL_DATA_SECTION

#ifdef SPIKE_HALT
#define RVMODEL_HALT \
  li t0, 1;          \
  la t1, tohost;     \
  sw t0, 0(t1);      \
  1: j 1b
#else
#define RVMODEL_HALT ebreak
#endif

#define RVMODEL_BOOT

#define RVMODEL_DATA_BEGIN \
  .align 4; .global begin_signature; begin_signature:
#define RVMODEL_DATA_END \
  .align 4; .global end_signature; end_signature:

#define RVMODEL_IO_INIT
#define RVMODEL_IO_WRITE_STR(_R, _STR)
#define RVMODEL_IO_CHECK()
#define RVMODEL_IO_ASSERT_GPR_EQ(_S, _R, _I)
#define RVMODEL_IO_ASSERT_SFPR_EQ(_F, _R, _I)
#define RVMODEL_IO_ASSERT_DFPR_EQ(_D, _R, _I)

#endif

#ifdef SPIKE_HALT
  .data
  .align 3
  .globl tohost
tohost: .dword 0
  .globl fromhost
fromhost: .dword 0
#endif
