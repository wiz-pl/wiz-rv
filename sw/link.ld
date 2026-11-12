/* Doom in DDR: code and data from 0x40000000, the stack below 0x44000000, the heap
   from the end of .bss up to HEAP_END (hw.h). */
OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0x40000000;
  .text : { *(.text.start) *(.text .text.*) }
  .rodata : { *(.rodata .rodata.* .srodata .srodata.*) }
  .data : { *(.data .data.* .sdata .sdata.*) }
  . = ALIGN(16);
  __bss_start = .;
  .bss : { *(.sbss .sbss.* .bss .bss.* COMMON) }
  . = ALIGN(16);
  __bss_end = .;
  _end = .;
  __stack_top = 0x44000000;
}
