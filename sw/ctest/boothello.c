/* The boot flow's C payload for the executable lockstep (tests/boot.wiz): a
   freestanding program at 0x40000000 (sw/ctest/benchcrt0.S + sw/link.ld) that the
   boot loader carries into DDR over the UART and that prints one word. It is kept
   tiny on purpose: the lockstep evaluates every instruction of the load in the
   kernel, so the larger benchmark (sw/ctest/bench.c) runs in sw/iss/iss.c and on
   the board instead. */
#include <stdint.h>

#define OUT (*(volatile uint32_t *)0x80000000u)

int main(void) {
  const char *s = "c ok\n";
  while (*s) OUT = (uint8_t)*s++;
  return 0;
}
