/* A small deterministic C benchmark for the boot flow (sw/README.md): built for
   DDR at 0x40000000 by sw/ctest/benchcrt0.S + sw/link.ld, loaded by the boot
   loader (src/Rv/Progs.wiz, `Prog.boot`) over the UART, and run in the executable
   lockstep (tests/boot.wiz). It prints one line on the output port:

     bench: map ok, str ok, sort ok, m ok, crc ded4d69b

   It is freestanding (no newlib: the boot loader has to carry every byte, and the
   lockstep evaluates every instruction; sw/ctest/ctest.c covers newlib) and reads
   no timer or performance counter: the lockstep reports instructions and cycles,
   and sw/iss/iss.c does the same on the host. The workload is a few thousand
   instructions for the same reason (FINDINGS.md S1). */
#include <stdint.h>

#define OUT (*(volatile uint32_t *)0x80000000u)

/* the machine's map (sw/hw.h): 16 KB on-chip RAM at 0, 256 MB DDR at 0x40000000 */
#define RAM_BASE 0x00000000u
#define DDR_BASE 0x40000000u
#define DDR_END  0x50000000u

static void putc_(char c) { OUT = (uint8_t)c; }
static void puts_(const char *s) { while (*s) putc_(*s++); }
static void puthex(uint32_t v) {
  for (int i = 7; i >= 0; i--) putc_("0123456789abcdef"[(v >> (4 * i)) & 15]);
}

/* the compiler may emit calls to these even in freestanding code */
void *memcpy(void *d, const void *s, unsigned n) { char *a = d; const char *b = s; while (n--) *a++ = *b++; return d; }
void *memset(void *d, int c, unsigned n) { char *a = d; while (n--) *a++ = (char)c; return d; }
void *memmove(void *d, const void *s, unsigned n) {
  char *a = d; const char *b = s;
  if (a < b) while (n--) *a++ = *b++;
  else { a += n; b += n; while (n--) *--a = *--b; }
  return d;
}

static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }
static int streq(const char *a, const char *b) {
  while (*a && *a == *b) { a++; b++; }
  return *a == *b;
}
static void scopy(char *d, const char *s) { while ((*d++ = *s++)) {} }

static char str[32];
static uint32_t v[16];

/* a word at `a` survives a write and a read, and the old value comes back */
static int probe(uint32_t a, uint32_t tag) {
  volatile uint32_t *p = (volatile uint32_t *)a;
  uint32_t old = *p;
  *p = tag;
  int ok = *p == tag;
  *p = old;
  return ok;
}

int main(void) {
  int map = probe(RAM_BASE + 0x1000, 0x5a5a1234u) &&
            probe(DDR_BASE + 0x01000000, 0xc3c3abcd) &&
            probe(DDR_END - 4, 0x0f0ff0f0u);
  puts_("bench: map ");
  puts_(map ? "ok" : "FAIL");

  /* string operations on a misaligned buffer (the core traps on misaligned words) */
  scopy(str + 1, "wiz-rv benchmark");
  int s_ok = streq(str + 1, "wiz-rv benchmark") && slen(str + 1) == 16;
  memmove(str + 3, str + 1, 17);
  s_ok = s_ok && streq(str + 3, "wiz-rv benchmark");
  puts_(", str ");
  puts_(s_ok ? "ok" : "FAIL");

  /* a selection sort of 16 words */
  uint32_t x = 0x12345678u;
  for (int i = 0; i < 16; i++) { x = x * 1103515245u + 12345u; v[i] = x >> 8; }
  for (int i = 0; i < 16; i++)
    for (int j = i + 1; j < 16; j++)
      if (v[j] < v[i]) { uint32_t t = v[i]; v[i] = v[j]; v[j] = t; }
  int sorted = 1;
  for (int i = 1; i < 16; i++) if (v[i - 1] > v[i]) sorted = 0;
  puts_(", sort ");
  puts_(sorted ? "ok" : "FAIL");

  /* the M extension: 32-bit multiply, signed divide and remainder, a 64-bit product */
  int32_t a = -123456789, b = 1000;
  uint32_t m = (uint32_t)(a / b) ^ (uint32_t)(a % b) ^ ((uint32_t)((int64_t)a * b >> 32));
  int m_ok = (uint32_t)(a / b) == 4294843840u && (uint32_t)(a % b) == 4294966507u;
  puts_(", m ");
  puts_(m_ok ? "ok" : "FAIL");

  /* CRC-32 (bitwise) over 32 bytes */
  uint32_t crc = 0xffffffffu;
  for (int k = 0; k < 32; k++) {
    crc ^= (uint8_t)(x >> ((k & 3) * 8)) ^ (uint8_t)v[k & 15];
    for (int b8 = 0; b8 < 8; b8++) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1)));
  }
  crc ^= m;
  puts_(", crc ");
  puthex(crc);
  puts_("\n");
  return 0;
}
