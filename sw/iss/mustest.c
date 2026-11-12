/* Renders a MUS lump with the music synthesizer (sw/mus_synth.c) to an 8-bit WAV at
   11025 Hz, on the host:   mustest LUMP.mus OUT.wav SECONDS
   (extract a lump: python3 scripts/wadlump.py wad/doom1.wad D_E1M1 > e1m1.mus) */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define SND_RATE 11025u
#include "../mus_synth.c"
static void put32(FILE *f, uint32_t v) { for (int i = 0; i < 4; i++) fputc(v >> (8 * i), f); }
int main(int argc, char **argv) {
  if (argc < 4) { fprintf(stderr, "mustest LUMP OUT.wav SECONDS\n"); return 1; }
  FILE *f = fopen(argv[1], "rb"); static uint8_t buf[1 << 20]; size_t n = fread(buf, 1, sizeof buf, f); fclose(f);
  notes_init(); for (int i = 0; i < MUSV; i++) vo[i].chan = -1;
  uint32_t len = buf[4] | (buf[5] << 8), start = buf[6] | (buf[7] << 8);
  if (n < 16 || memcmp(buf, "MUS\x1a", 4)) { fprintf(stderr, "not MUS\n"); return 1; }
  mus = buf; mus_score = buf + start; mus_end = mus_score + len; mus_loop = 1; mus_reset(); mus_on = 1;
  uint32_t ns = (uint32_t)(atof(argv[3]) * SND_RATE);
  FILE *o = fopen(argv[2], "wb");
  fwrite("RIFF", 1, 4, o); put32(o, 36 + ns); fwrite("WAVEfmt ", 1, 8, o); put32(o, 16);
  put32(o, 1 | (1 << 16)); put32(o, SND_RATE); put32(o, SND_RATE); put32(o, 1 | (8 << 16));
  fwrite("data", 1, 4, o); put32(o, ns);
  int peak = 0, clip = 0; uint32_t notes = 0, last = 0;
  for (uint32_t i = 0; i < ns; i++) {
    int s = mus_sample() + 128;
    if (vage != last) { notes += vage - last; last = vage; }
    if (abs(s - 128) > peak) peak = abs(s - 128);
    if (s < 0 || s > 255) clip++;
    fputc(s < 0 ? 0 : s > 255 ? 255 : s, o);
  }
  fclose(o);
  fprintf(stderr, "%u samples, %u notes started, peak %d, clipped %d\n", ns, notes, peak, clip);
  return 0;
}
