/* A deterministic RV32IM benchmark for the wiz-rv machine, run on the host by
   sw/iss/iss.c (scripts/iss-bench.sh) and, unchanged, by the board's boot loader.

   It is built with the platform's own runtime -- sw/crt0.S, sw/link.ld and
   sw/syscalls.c -- so the same image that the ISS runs is the one sw/rvload can put
   in DDR. It prints one line per part and a final PASS/FAIL line:

     bench: alu ok 8ce1d5a4 812 cycles
     ...
     bench: PASS 121644 instructions 334118 cycles

   Instructions and cycles are the ISS's model of the multi-cycle core (2 cycles
   per instruction, plus loads/stores, shifts and the divider); the board's
   pipelined core has different costs. This is a software/ISS harness, not a
   hardware performance measurement.

   The bench_asm_* kernels live in sw/bench/kernels.S: the harness is C *and*
   assembly on purpose (the C compiler cannot be trusted to emit the load/store
   loop we want to measure). */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "hw.h"

#define N 1024
static uint32_t a[N], b[N];
static char text[128], copy[128];

/* sw/bench/kernels.S */
extern uint32_t bench_asm_sum(const uint32_t *p, int n);
extern void bench_asm_copy(uint32_t *d, const uint32_t *s, int n);

static int failures;
static uint64_t t_mark;
static uint32_t i_mark;

static void mark(void) {
  t_mark = hw_cycles();
  i_mark = PERF_INSTR;
}
static uint32_t mark_cycles(void) { return (uint32_t)(hw_cycles() - t_mark); }
static uint32_t mark_instrs(void) { return PERF_INSTR - i_mark; }

static void report(const char *name, int ok, uint32_t value) {
  if (!ok) failures++;
  printf("bench: %s %s %08x %u cycles %u instructions\n",
         name, ok ? "ok" : "FAIL", (unsigned)value,
         (unsigned)mark_cycles(), (unsigned)mark_instrs());
}

static uint32_t lcg(uint32_t *s) {
  *s = *s * 1664525u + 1013904223u;
  return *s;
}

/* ALU: shifts by amounts, xor/and/add and a data-dependent branch */
static void bench_alu(void) {
  uint32_t x = 1, acc = 0;
  mark();
  for (int i = 0; i < 8192; i++) {
    x = lcg(&x);
    acc += (x >> 3) ^ (x << 7);
    acc = (x & 1) ? acc ^ 0x9e3779b9u : acc + 13;
  }
  report("alu", acc == 0x618b1400u, acc);
}

/* memory: word copy in assembly, then byte and halfword loads */
static void bench_mem(void) {
  uint32_t x = 0x12345678u, sum = 0;
  for (int i = 0; i < N; i++) a[i] = lcg(&x);
  memset(b, 0, sizeof b);
  mark();
  bench_asm_copy(b, a, N);
  for (int i = 0; i < N; i++) sum += b[i];
  for (int i = 0; i < 4 * N; i++) sum += ((const uint8_t *)b)[i];
  for (int i = 0; i < 2 * N; i++) sum += ((const uint16_t *)b)[i];
  int ok = memcmp(a, b, sizeof a) == 0;
  report("mem", ok, sum);
}

/* the assembly kernel on its own: a 1024-word load/add loop */
static void bench_asm(void) {
  uint32_t x = 0x0badf00du;
  uint32_t want = 0;
  for (int i = 0; i < N; i++) { a[i] = lcg(&x); want += a[i]; }
  mark();
  uint32_t got = bench_asm_sum(a, N);
  report("asm", got == want, got);
}

/* M: multiplies and the 32-cycle restoring divider */
static void bench_md(void) {
  uint32_t x = 7, acc = 0;
  mark();
  for (uint32_t i = 1; i <= 256; i++) {
    x = lcg(&x);
    acc ^= x * i;
    acc += x / i;
    acc ^= x % i;
  }
  report("muldiv", acc == 0x5f609bd4u, acc);
}

/* a selection sort of 128 words (branches and loads/stores) */
static void bench_sort(void) {
  uint32_t x = 0xdeadbeefu, sum = 0;
  enum { M = 128 };
  static uint32_t v[M];
  for (int i = 0; i < M; i++) v[i] = lcg(&x);
  mark();
  for (int i = 0; i < M; i++)
    for (int j = i + 1; j < M; j++)
      if (v[j] < v[i]) { uint32_t t = v[i]; v[i] = v[j]; v[j] = t; }
  int sorted = 1;
  for (int i = 1; i < M; i++) if (v[i - 1] > v[i]) sorted = 0;
  for (int i = 0; i < M; i++) sum = sum * 33u + v[i];
  report("sort", sorted, sum);
}

/* newlib's string functions on buffers that are not word aligned (the core traps
   on a misaligned word access; nix/riscv.nix builds newlib with -mstrict-align) */
static void bench_str(void) {
  int ok;
  mark();
  memset(text, 0, sizeof text);
  memset(copy, 0, sizeof copy);
  memcpy(text + 1, "wiz-rv benchmark", 17);
  memmove(text + 3, text + 1, 17);
  strcpy(copy + 1, text + 3);
  ok = strlen(copy + 1) == 16 && strcmp(copy + 1, "wiz-rv benchmark") == 0;
  memset(copy + 20, 'x', 8);
  copy[28] = 0;
  ok = ok && strlen(copy + 20) == 8 && memcmp(copy + 20, "xxxxxxxx", 8) == 0;
  report("str", ok, (uint32_t)strlen(copy + 1));
}

/* CRC-32/IEEE (bitwise) over 4096 bytes */
static void bench_crc(void) {
  static uint8_t buf[4096];
  uint32_t x = 0xcafebabeu, crc = 0xffffffffu;
  for (unsigned i = 0; i < sizeof buf; i++) buf[i] = (uint8_t)(lcg(&x) >> 24);
  mark();
  for (unsigned i = 0; i < sizeof buf; i++) {
    crc ^= buf[i];
    for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1)));
  }
  crc ^= 0xffffffffu;
  report("crc", crc == 0x5409eedbu, crc);
}

int main(void) {
  uint64_t t0 = hw_cycles();
  uint32_t i0 = PERF_INSTR;
  printf("bench: start\n");
  bench_alu();
  bench_mem();
  bench_asm();
  bench_md();
  bench_sort();
  bench_str();
  bench_crc();
  uint32_t cycles = (uint32_t)(hw_cycles() - t0);
  uint32_t instrs = PERF_INSTR - i0;
  printf("bench: %s %u instructions %u cycles\n",
         failures ? "FAIL" : "PASS", (unsigned)instrs, (unsigned)cycles);
  return failures ? 1 : 0;
}
