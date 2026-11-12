  .section .text.start
  .globl _start
_start:
  li sp, 0x3ff0
  call main
  ebreak
