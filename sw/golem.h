/* The golem SoC's memory map and MMIO registers, as software sees them. The hardware
   side is src/Rv/Golem/Map.wiz and src/Rv/Doom.wiz (the machine's MMIO decode); keep
   the two in step. See DESIGN.md. */
#ifndef GOLEM_H
#define GOLEM_H
#include <stdint.h>

#define GOLEM_CLOCK_HZ 100000000u          /* the pipelined core's rate */

/* 0x00000000: 16 KB on-chip RAM, the boot ROM (the core's m0 … m3, wb = 12) */
#define RAM_BASE       0x00000000u
#define RAM_BYTES      0x4000u

/* 0x40000000: 256 MB DDR3, through wiz-ddr3's 8 KB write-back cache */
#define DDR_BASE       0x40000000u
#define DDR_BYTES      0x10000000u
#define WAD_LEN_ADDR   0x47fffff0u          /* the boot loader's convention (Doom) */
#define WAD_BASE       0x48000000u
#define HEAP_END       0x47f00000u

#define IO(off)        (*(volatile uint32_t *)(0x80000000u + (off)))
#define UART_DATA      IO(0x00)             /* read: the next byte, or -1; write: send */
#define UART_STATUS    IO(0x04)             /* bit 0: the transmitter is idle
                                               bit 1: a received byte is waiting */
#define CYCLES_LO      IO(0x10)             /* the cycle counter (GOLEM_CLOCK_HZ) */
#define CYCLES_HI      IO(0x14)
#define DDR_STATUS     IO(0x40)             /* bit 0: calibration done, bit 1: failed */
#define SND_DATA       IO(0x30)             /* write: one 8-bit unsigned sample */
#define SND_FREE       IO(0x34)             /* read: free places in the FIFO */
#define SND_RATE       11025u
#define SND_FIFO       4096u

#define PERF_INSTR     IO(0x50)             /* the performance counters */
#define PERF_BUS       IO(0x54)
#define PERF_MEM       IO(0x58)
#define PERF_LONG      IO(0x5c)
#define PERF_FETCH     IO(0x60)
#define CACHE_HITS     IO(0x64)
#define CACHE_MISSES   IO(0x68)
#define PERF_FBW       IO(0x6c)
#define PERF_REFRESH   IO(0x70)
#define PERF_ODD       IO(0x74)
#define PERF_SUM       IO(0x78)
#define PERF_UNDER     IO(0x7c)
#define PERF_OLED      IO(0x80)             /* pins 11..7: PMODEN VCCEN RES DC CS; pc */

/* 0x81000000: 96 x 64 RGB 565, row-major, halfword stores */
#define OLED_FB        ((volatile uint16_t *)0x81000000u)
#define OLED_W         96
#define OLED_H         64
#define RGB(r, g, b)   ((uint16_t)(((r) << 11) | ((g) << 5) | (b)))

static inline uint64_t golem_cycles(void) {
  uint32_t hi, lo;
  do { hi = CYCLES_HI; lo = CYCLES_LO; } while (hi != CYCLES_HI);
  return ((uint64_t)hi << 32) | lo;
}

static inline void golem_putc(char c) { UART_DATA = (uint8_t)c; }
static inline void golem_puts(const char *s) { while (*s) golem_putc(*s++); }

#endif
