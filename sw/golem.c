/* A tiny C hello for golem: prints a banner and the cycle counter, then draws three
   rows of colour into the OLED framebuffer. Built for the on-chip RAM with the RV32IM
   toolchain (nix/riscv.nix) and tests/ctest's start-up code:

     riscv32-none-elf-gcc -march=rv32im -mabi=ilp32 -mstrict-align -O2 \
       -nostdlib -T sw/ctest/link.ld sw/ctest/crt0.S sw/golem.c -o golem.elf
     .grail/bin/bin2wiz golem.elf ...          (or objcopy -O binary, then bin2wiz)

   It is not part of the simulation (the boot ROM, src/Rv/Golem/Prog.wiz, is); it is the
   `hello` that a loaded program can be. */
#include "golem.h"

static void row(unsigned y, uint16_t c) {
  for (unsigned x = 0; x < OLED_W; x++) OLED_FB[y * OLED_W + x] = c;
}

int main(void) {
  golem_puts("golem C hello\n");
  golem_puts("cycles: ");
  {
    uint64_t c = golem_cycles();
    char b[24]; int n = 0;
    do { b[n++] = '0' + (char)(c % 10); c /= 10; } while (c);
    while (n) golem_putc(b[--n]);
  }
  golem_putc('\n');

  row(0, RGB(31, 0, 0));
  row(1, RGB(0, 63, 0));
  row(2, RGB(0, 0, 31));
  golem_puts("framebuffer: 3 rows\n");
  return 0;
}
