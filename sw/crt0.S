/* Entry: a stack, zeroed .bss, main(0, 0), then ebreak with main's result in a0. */
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
  li a1, 0
  call main
  call exit
  .globl _exit
_exit:
  ebreak
  j _exit
