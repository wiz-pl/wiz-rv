/* A sound test: a 441 Hz triangle (11025 / 25) at half amplitude, then a second of
   silence, repeated, straight into the FIFO. If the piezo crackles with this, the fault
   is in the hardware path (FIFO, PWM); if not, in Doom's mixing.   nix-build nix/tone.nix */
#include <stdio.h>
#include "hw.h"
int main(void) {
  printf("tone: 441 Hz triangle, 2 s on, 1 s off\n");
  uint32_t t = 0;
  for (;;) {
    while (SND_FREE == 0) {}
    uint32_t p = t % 25, s = t % (3 * SND_RATE);
    int v = p < 13 ? (int)p * 10 : (25 - (int)p) * 10;   /* 0..120 */
    SND_DATA = s < 2 * SND_RATE ? (uint8_t)(68 + v) : 128;
    t++;
  }
}
