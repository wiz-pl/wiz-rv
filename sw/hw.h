/* The wiz-rv Arty machine, as software sees it (README.md, "Doom"). */
#ifndef WIZRV_HW_H
#define WIZRV_HW_H
#include <stdint.h>

#define HW_CLOCK_HZ   50000000u            /* the core's rate: 100 MHz at half rate */

#define BOOT_ROM_BASE 0x00000000u          /* 16 KB on-chip RAM: the boot loader, Prog.boot */
#define BOOT_ROM_SIZE 0x00004000u
#define DDR_BASE      0x40000000u          /* 256 MB, through the 8 KB write-back cache */
#define DDR_SIZE      0x10000000u
#define WAD_LEN_ADDR  0x47fffff0u          /* the boot loader leaves the WAD's length here */
#define WAD_BASE      0x48000000u          /* and the WAD itself here */
#define HEAP_END      0x47f00000u          /* malloc grows from _end to here (syscalls.c) */

#define IO_BASE       0x80000000u
#define IO(off)       (*(volatile uint32_t *)(IO_BASE + (off)))
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

/* The map is the software/hardware contract (src/Rv/Doom.wiz, sw/README.md): the
   boot ROM is the 16 KB on-chip RAM, DDR is 256 MB from 0x40000000, the heap stops
   one megabyte below the WAD (whose length sits in the last 16 bytes of that gap),
   and every region is aligned. A change here is a change to the SoC. */
_Static_assert((BOOT_ROM_SIZE & (BOOT_ROM_SIZE - 1)) == 0, "boot ROM is a power of two");
_Static_assert(BOOT_ROM_SIZE <= DDR_BASE, "boot ROM below DDR");
_Static_assert(HEAP_END <= WAD_LEN_ADDR, "heap below the WAD length");
_Static_assert(WAD_LEN_ADDR + 16 <= WAD_BASE, "WAD length page ends at the WAD");
_Static_assert(WAD_BASE + 4 * 1024 * 1024 <= DDR_BASE + DDR_SIZE, "a 4 MB WAD fits in DDR");
_Static_assert((WAD_BASE & 0xfff) == 0 && (WAD_LEN_ADDR & 3) == 0, "WAD alignment");
_Static_assert(0x81000000u + OLED_W * OLED_H * 2 <= 0x82000000u, "96 x 64 RGB565 fits one frame");
_Static_assert((IO_BASE & 0xfff) == 0, "I/O page aligned");

static inline uint64_t hw_cycles(void) {
  uint32_t hi, lo;
  do { hi = CYCLES_HI; lo = CYCLES_LO; } while (hi != CYCLES_HI);
  return ((uint64_t)hi << 32) | lo;
}
#endif
