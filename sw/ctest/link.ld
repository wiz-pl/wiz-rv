OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0;
  .text : { *(.text.start) *(.text .text.*) }
  .rodata : { *(.rodata .rodata.* .srodata .srodata.*) }
  .data : { *(.data .data.* .sdata .sdata.*) }
  .bss : { *(.sbss .sbss.* .bss .bss.* COMMON) }
}
