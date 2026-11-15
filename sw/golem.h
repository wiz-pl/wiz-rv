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

/* The ROM loader's frame (sw/golem-upload sends it; src/Rv/Golem/Loader.wiz reads
   it and DESIGN.md, "The ROM loader", is the long form). On reset the loader prints a
   banner, waits for this frame at 1 Mbaud 8N1, writes the payload to LOAD_BASE, checks
   the CRC32 and jumps to `entry`. All fields are little-endian; the header is 20
   bytes. A length of LOAD_MAX or more, a version other than 1, an unaligned or
   out-of-image entry, or a bad CRC is refused (a diagnostic, no jump).
     +0   "GLDR"                        magic
     +4   u8 version (1), u8 flags (0), u16 reserved (0)
     +8   u32 length                    payload bytes, < LOAD_MAX
     +12  u32 crc32                     payload only: reflected 0xEDB88320,
                                        init/final xor 0xFFFFFFFF (zlib crc32)
     +16  u32 entry                     absolute address in the payload
     +20  payload */
#define LOAD_MAGIC     0x52444c47u          /* "GLDR" in memory, little-endian */
#define LOAD_VERSION   1u
#define LOAD_HEADER    20u
#define LOAD_BASE      0x40000000u          /* the payload's fixed DDR address */
#define LOAD_MAX       0x00100000u          /* 1 MiB: the hard length cap */
#define LOAD_CRC_INIT  0xffffffffu
#define LOAD_CRC_POLY  0xedb88320u

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

/* 0x80001000: the inter-hart mailbox and the boot ABI (four words a hart).
   A message is one 32-bit word: writing IPI_DATA(h) posts it to hart h and raises PLIC
   source 2 + h; reading it takes the word and clears its valid bit. The boot ABI:
   hart 0 writes the entry address to BOOT_ENTRY(h), then writes 1 to MSIP(h) (the
   CLINT doorbell); a parked hart polls MSIP(h), reads BOOT_ENTRY(h) and jumps. */
#define IPI_DATA(h)     IO(0x1000u + 8u * (h))
#define IPI_STATUS(h)   IO(0x1004u + 8u * (h))   /* bit 0: a message is waiting */
#define BOOT_ENTRY(h)   IO(0x1010u + 4u * (h))
#define BOOT_HART0      0u

/* 0x80002000: the PLIC-style external controller. Sources: 1 UART received byte,
   2 hart 0's mailbox, 3 hart 1's mailbox, 4 the spare external input. Contexts:
   0 hart 0 M-mode, 1 hart 1 M-mode. A source is taken when it is pending, enabled for
   the context and its priority is above the context's threshold; a read of the claim
   register returns the source (0: none) and marks it in service, a write completes it. */
#define PLIC_PRIO(s)    IO(0x2000u + 4u * (s))       /* 3 bits, 0: masked */
#define PLIC_PENDING    IO(0x2020)                   /* read: the pending bitmap */
#define PLIC_ENABLE(c)  IO(0x2040u + 4u * (c))
#define PLIC_THRESH(c)  IO(0x2060u + 4u * (c))
#define PLIC_CLAIM(c)   IO(0x2080u + 4u * (c))       /* read claims, write completes */
#define PLIC_UART       1u
#define PLIC_IPI0       2u
#define PLIC_IPI1       3u
#define PLIC_EXT        4u

/* 0x80004000: the CLINT-like timer, at the standard CLINT offsets rebased into the I/O
   window. mtime counts the core's cycles (100 MHz on `golem`; half that on `golemMc`,
   whose machine is at 50 MHz); writing mtime is a bring-up convenience this SoC keeps.
   mtimecmp is a 64-bit word written as two 32-bit halves: write the high half first,
   then the low half (the other order can fire MTIP for a cycle from the old high half). */
#define MSIP(h)         IO(0x4000u + 4u * (h))       /* write 1: release hart h */
#define MTIMECMP(h)     IO(0x8000u + 8u * (h))       /* low word */
#define MTIMECMP_HI(h)  IO(0x8004u + 8u * (h))       /* and the high word */
#define MTIME_LO        IO(0xfff8)
#define MTIME_HI        IO(0xfffc)

/* `mip`/`mie` bits (M-mode). The core has no CSRs yet (DESIGN.md, "Interrupts, timer
   and harts"), so software polls the blocks above or MTIP's source until it does. */
#define MIP_MSIP        (1u << 3)                    /* the CLINT doorbell */
#define MIP_MTIP        (1u << 7)                    /* mtime >= mtimecmp */
#define MIP_MEIP        (1u << 11)                   /* the PLIC's external interrupt */
#define MIE_MSIE        MIP_MSIP
#define MIE_MTIE        MIP_MTIP
#define MIE_MEIE        MIP_MEIP
/* and the `mcause` codes of the same three */
#define CAUSE_MSI       3u
#define CAUSE_MTI       7u
#define CAUSE_MEI       11u

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

/* --- the timer, the mailbox and the external interrupt controller --- */

static inline uint64_t golem_mtime(void) {
  uint32_t hi, lo;
  do { hi = MTIME_HI; lo = MTIME_LO; } while (hi != MTIME_HI);
  return ((uint64_t)hi << 32) | lo;
}

static inline void golem_set_mtimecmp(unsigned hart, uint64_t t) {
  /* the high word first: with the old compare behind mtime, this raises MTIP for a
     cycle at most, where writing the low word first could fire a spurious interrupt */
  MTIMECMP_HI(hart) = (uint32_t)(t >> 32);
  MTIMECMP(hart) = (uint32_t)t;
}

/* the timer interrupt is taken when mtime reaches mtimecmp: arm it `cycles` ahead */
static inline void golem_arm_timer(unsigned hart, uint32_t cycles) {
  golem_set_mtimecmp(hart, golem_mtime() + cycles);
}

/* post a message to hart h (and raise its PLIC source); a received message is taken
   with golem_ipi_recv, which also clears the valid bit */
static inline void golem_ipi_send(unsigned hart, uint32_t msg) { IPI_DATA(hart) = msg; }
static inline int golem_ipi_pending(unsigned hart) { return (int)(IPI_STATUS(hart) & 1u); }
static inline uint32_t golem_ipi_recv(unsigned hart) { return IPI_DATA(hart); }

static inline void golem_plic_enable(unsigned ctx, uint32_t sources) { PLIC_ENABLE(ctx) = sources; }
static inline void golem_plic_priority(unsigned source, uint32_t prio) { PLIC_PRIO(source) = prio; }
static inline uint32_t golem_plic_claim(unsigned ctx) { return PLIC_CLAIM(ctx); }
static inline void golem_plic_complete(unsigned ctx, uint32_t source) { PLIC_CLAIM(ctx) = source; }

/* the boot ABI: hart 0 sets `entry` for hart h and releases it from its park loop */
static inline void golem_release(unsigned hart, uint32_t entry) {
  BOOT_ENTRY(hart) = entry;
  MSIP(hart) = 1u;
}

#endif
