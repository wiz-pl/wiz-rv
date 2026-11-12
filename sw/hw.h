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
#define SND_DATA      IO(0x30)             /* write: one 8-bit unsigned sample into the FIFO */
#define SND_FREE      IO(0x34)             /* read: free places in the FIFO */
#define SND_RATE      11025u               /* the FIFO is played at this rate (PWM on JB1) */
#define SND_FIFO      4096u

#define PERF_INSTR    IO(0x50)             /* performance counters (free-running) */
#define PERF_BUS      IO(0x54)             /* cycles waiting for DDR (fetch, load, store) */
#define PERF_MEM      IO(0x58)             /* load cycles (M) */
#define PERF_LONG     IO(0x5c)             /* shift / multiply / divide cycles */
#define PERF_FETCH    IO(0x60)             /* refetch after a store (F) */
#define CACHE_HITS    IO(0x64)
#define CACHE_MISSES  IO(0x68)
#define PERF_FBW      IO(0x6c)             /* framebuffer writes */
#define PERF_REFRESH  IO(0x70)             /* OLED refreshes */
#define PERF_ODD      IO(0x74)             /* refreshes whose pixel checksum changed with no write */
#define PERF_SUM      IO(0x78)             /* the last refresh's checksum */
#define PERF_UNDER    IO(0x7c)             /* sound ticks with the FIFO empty */
#define PERF_OLED     IO(0x80)             /* the OLED controller: pins (11..7: PMODEN VCCEN RES DC CS), program counter */

#define OLED_FB       ((volatile uint16_t *)0x81000000u)   /* 96 x 64 RGB565, row-major */
#define OLED_W        96
#define OLED_H        64

static inline uint64_t hw_cycles(void) {
  uint32_t hi, lo;
  do { hi = CYCLES_HI; lo = CYCLES_LO; } while (hi != CYCLES_HI);
  return ((uint64_t)hi << 32) | lo;
}
#endif
