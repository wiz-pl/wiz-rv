/* A small C program for the lockstep (tests/lockstep.wiz): compiled by the RV32IM
   toolchain for the on-chip RAM, it uses newlib's string functions on misaligned
   buffers, multiplication and division, and prints its results on the output port. */
#include <stdint.h>
#include <string.h>

#define OUT (*(volatile uint32_t *)0x80000000u)

static void putc_(char c) { OUT = (uint8_t)c; }
static void puts_(const char *s) { while (*s) putc_(*s++); }
static void putu(uint32_t v) {
  char b[12]; int n = 0;
  do { b[n++] = '0' + v % 10; v /= 10; } while (v);
  while (n) putc_(b[--n]);
}

static char buf[64];

int main(void) {
  strcpy(buf + 1, "wiz-rv");             /* misaligned destination */
  strncpy(buf + 9, buf + 1, 7);
  puts_(buf + 9); putc_(' ');
  putu(strlen(buf + 1)); putc_(' ');
  putu(strcmp(buf + 1, "wiz-rv") == 0); putc_(' ');
  memmove(buf + 3, buf + 1, 6); buf[9] = 0;
  puts_(buf + 3); putc_(' ');
  volatile int32_t a = -123456789, b = 1000;
  putu((uint32_t)(a / b)); putc_(' ');
  putu((uint32_t)(a % b)); putc_(' ');
  putu((uint32_t)((int64_t)a * b >> 32)); putc_('\n');
  return 0;
}
