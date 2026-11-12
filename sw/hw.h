/* The wiz-rv Arty machine, as software sees it (README.md, "Doom"). */
#ifndef WIZRV_HW_H
#define WIZRV_HW_H
#include <stdint.h>

#define HW_CLOCK_HZ   50000000u            /* the core's rate: 100 MHz at half rate */

#define DDR_BASE      0x40000000u          /* 256 MB, through the 8 KB write-back cache */
#define WAD_LEN_ADDR  0x47fffff0u          /* the boot loader leaves the WAD's length here */
#define WAD_BASE      0x48000000u          /* and the WAD itself here */
#define HEAP_END      0x47f00000u

#define IO(off)       (*(volatile uint32_t *)(0x80000000u + (off)))
#define UART_DATA     IO(0x00)             /* read: the next byte, or -1; write: send a byte */
#define CYCLES_LO     IO(0x10)             /* a free-running cycle counter (HW_CLOCK_HZ) */
#define CYCLES_HI     IO(0x14)
#define JOY_X         IO(0x20)             /* the thumbstick (XADC), 12 bits, centre ~2048 */
#define JOY_Y         IO(0x24)
#define JOY_BUTTONS   IO(0x28)             /* bit 0: the stick's button, bits 4..7: BTN0..BTN3 */

#define OLED_FB       ((volatile uint16_t *)0x81000000u)   /* 96 x 64 RGB565, row-major */
#define OLED_W        96
#define OLED_H        64

static inline uint64_t hw_cycles(void) {
  uint32_t hi, lo;
  do { hi = CYCLES_HI; lo = CYCLES_LO; } while (hi != CYCLES_HI);
  return ((uint64_t)hi << 32) | lo;
}
#endif
