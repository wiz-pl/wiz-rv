/* A small instruction-set simulator of the wiz-rv Arty machine (sw/hw.h), for running
   the Doom port on the host: RV32IM as src/Rv/Isa.wiz specifies it (traps stop the
   machine), 16 KB on-chip RAM at 0, 256 MB DDR at 0x40000000, the I/O registers
   (UART on stdout / from a key script, a cycle counter, the audio FIFO, written to a
   WAV file, the OLED framebuffer, written out as PPM images).

   iss PROGRAM.bin WAD [-n INSTRUCTIONS] [-frames DIR] [-wav FILE] [-keys "TIME:KEY,..."]
   The program is loaded at 0x40000000 and started there; the WAD at 0x48000000. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint8_t bram[16384];
static uint8_t *ddr;
static const uint32_t DDR_SIZE = 256u << 20;
static uint16_t oled[96 * 64];
static uint32_t x[32], pc;
static uint64_t cycles, instret;
static const char *frames;
static int nframe;
static const char *keys;        /* "ms:c,ms:c,..." */
static int lenient;             /* -lenient: do misaligned accesses (and report where) */
static uint32_t mis_pc[64]; static int mis_n; static uint64_t mis_total;
static void misaligned(void) {
  mis_total++;
  for (int i = 0; i < mis_n; i++) if (mis_pc[i] == pc) return;
  if (mis_n < 64) mis_pc[mis_n++] = pc;
}

static uint8_t *byte_at(uint32_t a) {
  if ((a >> 30) == 1) return &ddr[a & (DDR_SIZE - 1)];
  if (a >> 31) return 0;
  return &bram[a & 16383];
}

static int key_at(uint32_t ms) {   /* the key typed at this time, if any (once) */
  static const char *p;
  static long next = -1;
  if (!keys) return -1;
  if (!p) p = keys;
  if (next < 0 && *p) next = strtol(p, (char **)&p, 10);
  if (next >= 0 && ms >= (uint32_t)next && *p == ':') {
    int c = p[1] == '\\' ? (p[2] == 'n' ? '\r' : p[2] == 'e' ? 27 : p[2]) : p[1];
    p += p[1] == '\\' ? 3 : 2;
    if (*p == ',') p++;
    next = -1;
    return c;
  }
  return -1;
}

static void dump_frame(void) {
  if (!frames) return;
  char name[512];
  snprintf(name, sizeof name, "%s/frame%05d.ppm", frames, nframe++);
  FILE *f = fopen(name, "wb");
  if (!f) return;
  fprintf(f, "P6\n96 64\n255\n");
  for (int i = 0; i < 96 * 64; i++) {
    uint16_t p = oled[i];
    fputc(((p >> 11) & 31) << 3, f); fputc(((p >> 5) & 63) << 2, f); fputc((p & 31) << 3, f);
  }
  fclose(f);
}

static uint64_t snd_written;
static FILE *wav;
static uint32_t wav_n;

static uint32_t io_read(uint32_t a) {
  uint32_t ms = (uint32_t)(cycles / 50000);
  switch (a & 0xff) {
  case 0x00: { int c = key_at(ms); return c < 0 ? 0xffffffffu : (uint32_t)c; }
  case 0x10: return (uint32_t)cycles;
  case 0x14: return (uint32_t)(cycles >> 32);
  case 0x34: {             /* free places: 4096 minus what is written and not yet played */
    uint64_t played = cycles * 11025 / 50000000;
    if (snd_written < played) snd_written = played;   /* an underrun: silence was played */
    uint64_t used = snd_written - played;
    return used >= 4096 ? 0 : (uint32_t)(4096 - used);
  }
  default: return 0;
  }
}

static void io_write(uint32_t a, uint32_t v, int size) {
  if ((a >> 24) == 0x81) {
    uint32_t i = (a & 0xffffff) >> 1;
    if (i < 96 * 64 && size == 2) {
      oled[i] = (uint16_t)v;
      if (i == 96 * 64 - 1) dump_frame();   /* the last pixel: a frame is done */
    }
  } else if ((a & 0xff) == 0x30) {
    snd_written++;
    if (wav) { fputc(v & 0xff, wav); wav_n++; }
  } else if ((a & 0xff) == 0) {
    putchar(v & 0xff);
    fflush(stdout);
  }
}

static int32_t sx(uint32_t v, int bits) { return (int32_t)(v << (32 - bits)) >> (32 - bits); }

/* one instruction; 0 to go on, else the trap code (Isa.wiz) */
static int step(void) {
  uint8_t *ip = byte_at(pc);
  if (!ip || (pc & 3)) return 4;
  uint32_t w; memcpy(&w, ip, 4);
  uint32_t op = w & 127, rd = (w >> 7) & 31, f3 = (w >> 12) & 7, r1 = (w >> 15) & 31, r2 = (w >> 20) & 31, f7 = w >> 25;
  uint32_t a = x[r1], b = x[r2], npc = pc + 4, v = 0;
  int wr = 0;
  int32_t iI = sx(w >> 20, 12), iS = sx(((w >> 25) << 5) | ((w >> 7) & 31), 12);
  int32_t iB = sx(((w >> 31) << 12) | (((w >> 7) & 1) << 11) | (((w >> 25) & 63) << 5) | (((w >> 8) & 15) << 1), 13);
  int32_t iJ = sx(((w >> 31) << 20) | (((w >> 12) & 255) << 12) | (((w >> 20) & 1) << 11) | (((w >> 21) & 1023) << 1), 21);
  cycles += 2;
  switch (op) {
  case 0x37: v = w & 0xfffff000u; wr = 1; break;
  case 0x17: v = pc + (w & 0xfffff000u); wr = 1; break;
  case 0x6f: v = npc; wr = 1; npc = pc + iJ; if (npc & 3) return 4; break;
  case 0x67: if (f3) return 3; v = npc; wr = 1; npc = (a + iI) & ~1u; if (npc & 3) return 4; break;
  case 0x63: {
    int t;
    switch (f3) {
    case 0: t = a == b; break; case 1: t = a != b; break;
    case 4: t = (int32_t)a < (int32_t)b; break; case 5: t = (int32_t)a >= (int32_t)b; break;
    case 6: t = a < b; break; case 7: t = a >= b; break;
    default: return 3;
    }
    if (t) { npc = pc + iB; if (npc & 3) return 4; }
    break;
  }
  case 0x03: {
    uint32_t ad = a + iI, size = 1u << (f3 & 3);
    if (f3 == 3 || f3 > 5) return 3;
    if (ad & (size - 1)) { if (!lenient) return 5; misaligned(); }
    cycles += 1;
    if (ad >> 31) v = io_read(ad);
    else {
      uint8_t *p = byte_at(ad); uint32_t t = 0; memcpy(&t, p, size);
      v = f3 == 0 ? (uint32_t)sx(t, 8) : f3 == 1 ? (uint32_t)sx(t, 16) : t;
    }
    wr = 1;
    break;
  }
  case 0x23: {
    uint32_t ad = a + iS, size = 1u << (f3 & 3);
    if (f3 > 2) return 3;
    if (ad & (size - 1)) { if (!lenient) return 6; misaligned(); }
    cycles += 1;
    if (ad >> 31) io_write(ad, b, size);
    else memcpy(byte_at(ad), &b, size);
    break;
  }
  case 0x13: case 0x33: {
    uint32_t c = op == 0x13 ? (uint32_t)iI : b;
    int alt = op == 0x33 ? f7 == 32 : (f3 == 5 && f7 == 32);
    wr = 1;
    if (op == 0x33 && f7 == 1) {
      int64_t sa = (int32_t)a, sb = (int32_t)b; uint64_t ua = a, ub = b;
      cycles += f3 >= 4 ? 32 : 1;
      switch (f3) {
      case 0: v = a * b; break;
      case 1: v = (uint32_t)((sa * sb) >> 32); break;
      case 2: v = (uint32_t)((sa * (int64_t)ub) >> 32); break;
      case 3: v = (uint32_t)((ua * ub) >> 32); break;
      case 4: v = b == 0 ? 0xffffffffu : (a == 0x80000000u && b == 0xffffffffu) ? a : (uint32_t)((int32_t)a / (int32_t)b); break;
      case 5: v = b == 0 ? 0xffffffffu : a / b; break;
      case 6: v = b == 0 ? a : (a == 0x80000000u && b == 0xffffffffu) ? 0 : (uint32_t)((int32_t)a % (int32_t)b); break;
      case 7: v = b == 0 ? a : a % b; break;
      }
      break;
    }
    switch (f3) {
    case 0: v = alt && op == 0x33 ? a - c : a + c; break;
    case 1: v = a << (c & 31); cycles += (c & 31) + 1; break;
    case 2: v = (int32_t)a < (int32_t)c; break;
    case 3: v = a < c; break;
    case 4: v = a ^ c; break;
    case 5: v = alt ? (uint32_t)((int32_t)a >> (c & 31)) : a >> (c & 31); cycles += (c & 31) + 1; break;
    case 6: v = a | c; break;
    case 7: v = a & c; break;
    }
    break;
  }
  case 0x0f: break;
  case 0x73: return w == 0x73 ? 1 : w == 0x100073 ? 2 : 3;
  default: return 3;
  }
  if (wr && rd) x[rd] = v;
  pc = npc;
  instret++;
  return 0;
}

static long load(const char *path, uint32_t at) {
  FILE *f = fopen(path, "rb");
  if (!f) { perror(path); exit(1); }
  long n = (long)fread(byte_at(at), 1, 64u << 20, f);
  fclose(f);
  return n;
}

int main(int argc, char **argv) {
  if (argc < 3) { fprintf(stderr, "usage: iss PROGRAM.bin WAD [-n N] [-frames DIR] [-keys K]\n"); return 2; }
  uint64_t limit = 2000000000ull;
  for (int i = 3; i + 1 < argc; i += 2) {
    if (!strcmp(argv[i], "-n")) limit = strtoull(argv[i + 1], 0, 10);
    else if (!strcmp(argv[i], "-frames")) frames = argv[i + 1];
    else if (!strcmp(argv[i], "-keys")) keys = argv[i + 1];
    else if (!strcmp(argv[i], "-lenient")) { lenient = 1; i--; }
    else if (!strcmp(argv[i], "-wav")) { wav = fopen(argv[i + 1], "wb"); fseek(wav, 44, SEEK_SET); }
  }
  ddr = calloc(DDR_SIZE, 1);
  load(argv[1], 0x40000000u);
  uint32_t n = (uint32_t)load(argv[2], 0x48000000u);
  memcpy(byte_at(0x47fffff0u), &n, 4);
  pc = 0x40000000u;
  int t = 0;
  while (instret < limit && !(t = step())) {}
  fprintf(stderr, "\n[iss] %s after %llu instructions, %llu cycles (%.1f s at 50 MHz), pc %08x, %d frames\n",
          t ? "trap" : "stopped", (unsigned long long)instret, (unsigned long long)cycles, cycles / 50e6, pc, nframe);
  if (t) {
    fprintf(stderr, "[iss] trap %d\n", t);
    for (int i = 0; i < 32; i++) fprintf(stderr, "x%d=%08x%s", i, x[i], i % 8 == 7 ? "\n" : " ");
  }
  if (mis_total) {
    fprintf(stderr, "[iss] %llu misaligned accesses, at", (unsigned long long)mis_total);
    for (int i = 0; i < mis_n; i++) fprintf(stderr, " %08x", mis_pc[i]);
    fprintf(stderr, "\n");
  }
  if (wav) {                /* the RIFF header: 8-bit unsigned mono at 11025 Hz */
    uint32_t h[11] = { 0x46464952, 36 + wav_n, 0x45564157, 0x20746d66, 16, 0x00010001, 11025, 11025, 0x00080001,
                       0x61746164, wav_n };
    fseek(wav, 0, SEEK_SET); fwrite(h, 4, 11, wav); fclose(wav);
    fprintf(stderr, "[iss] %u samples of sound\n", wav_n);
  }
  return t == 2 ? 0 : t;
}
