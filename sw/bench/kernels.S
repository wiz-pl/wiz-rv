/* Two leaf kernels for sw/bench/bench.c, in RV32IM assembly so that the instruction
   sequence under measurement is the one written here (no compiler scheduling, no
   inlined memcpy). */
  .text

  .globl bench_asm_sum
  .type  bench_asm_sum, @function
/* uint32_t bench_asm_sum(const uint32_t *p (a0), int n (a1)) */
bench_asm_sum:
  li    t0, 0
1:
  beqz  a1, 2f
  lw    t1, 0(a0)
  add   t0, t0, t1
  addi  a0, a0, 4
  addi  a1, a1, -1
  j     1b
2:
  mv    a0, t0
  ret
  .size bench_asm_sum, .-bench_asm_sum

  .globl bench_asm_copy
  .type  bench_asm_copy, @function
/* void bench_asm_copy(uint32_t *d (a0), const uint32_t *s (a1), int n (a2)) */
bench_asm_copy:
  beqz  a2, 2f
1:
  lw    t0, 0(a1)
  sw    t0, 0(a0)
  addi  a0, a0, 4
  addi  a1, a1, 4
  addi  a2, a2, -1
  bnez  a2, 1b
2:
  ret
  .size bench_asm_copy, .-bench_asm_copy
