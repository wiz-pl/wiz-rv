/* Link a vendored arch test at address 0 for the Wiz core.
 *
 * The core's on-chip memory starts at 0 and wraps at 2^mbits; a flat image from
 * `objcopy -O binary` is loaded there.  Sections are contiguous so the image (and the
 * signature region at `begin_signature` … `end_signature`) is one range.
 */
OUTPUT_ARCH("riscv")
ENTRY(rvtest_entry_point)
SECTIONS
{
  . = 0x0;
  .text : { *(.text.init) *(.text) *(.text.*) *(.rodata) *(.rodata.*) }
  .data : { *(.data) *(.data.*) *(.sdata) *(.sdata.*) *(.bss) *(.bss.*) *(COMMON) }
  _end = .;
}
