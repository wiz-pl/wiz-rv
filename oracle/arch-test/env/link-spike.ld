/* Link a vendored arch test at Spike's default DRAM base.
 *
 * Only used to produce a reference signature with Spike (`+signature=`).  See
 * model_test.h: the `SPIKE_HALT` build exits through tohost.
 */
OUTPUT_ARCH("riscv")
ENTRY(rvtest_entry_point)
SECTIONS
{
  . = 0x80000000;
  .text : { *(.text.init) *(.text) *(.text.*) *(.rodata) *(.rodata.*) }
  .data : { *(.data) *(.data.*) *(.sdata) *(.sdata.*) *(.bss) *(.bss.*) *(COMMON) }
  . = ALIGN(8);
  .tohost : { *(.tohost) }
  _end = .;
}
