/* Entry for the boot benchmark (sw/ctest/bench.c) in DDR: a stack at 0x44000000,
   .bss zeroed, main, then ebreak (no newlib: the payload has to stay small because
   the boot loader carries it over the UART and the lockstep runs every byte). */
  .section .text.start
  .globl _start
_start:
  la sp, __stack_top
  la t0, __bss_start
  la t1, __bss_end
1:bgeu t0, t1, 2f
  sw zero, 0(t0)
  addi t0, t0, 4
  j 1b
2:li a0, 0
  call main
  ebreak
  j .
