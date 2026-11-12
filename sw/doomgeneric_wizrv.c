/* doomgeneric's platform layer for the wiz-rv Arty machine (hw.h):
   - the 320 x 200 frame, downscaled to the PmodOLEDrgb's 96 x 64 (RGB565), each OLED
     pixel the average of a block of the frame;
   - time from the cycle counter;
   - keys from the UART (optional: without them Doom plays its demo loop);
   - sound: sw/sound_wizrv.c. */
#include <stdio.h>
#include "doomgeneric.h"
#include "doomkeys.h"
#include "hw.h"

static inline uint16_t rgb565(uint32_t r, uint32_t g, uint32_t b) {
  return (uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
}

void DG_Init(void) {}

/* OLED pixel (x, y) covers frame columns [x*320/96, (x+1)*320/96) and rows
   [y*200/64, (y+1)*200/64): average 2 x 2 samples of that block */
static uint32_t sw_w;   /* framebuffer writes made by DG_DrawFrame */
/* every 5 s: the performance counters' increments (cycles at 50 MHz) */
static void perf_report(void) {
  static uint64_t last; static uint32_t frames, l_i, l_b, l_m, l_l, l_f, l_h, l_x, l_w;
  frames++;
  uint64_t now = hw_cycles();
  if (now - last < 5ull * HW_CLOCK_HZ) return;
  uint32_t i = PERF_INSTR, b = PERF_BUS, m = PERF_MEM, l = PERF_LONG, f = PERF_FETCH, h = CACHE_HITS, x = CACHE_MISSES;
  uint32_t cyc = (uint32_t)(now - last);
  uint32_t w = PERF_FBW;
  printf("perf: %u frames, cycles %u, instr %u (CPI x100 %u), bus %u, M %u, long %u, F %u, cache hits %u misses %u, fb writes %u (drawn %u)\n",
         (unsigned)frames, (unsigned)cyc, (unsigned)(i - l_i), (unsigned)(i - l_i ? (uint64_t)cyc * 100 / (i - l_i) : 0),
         (unsigned)(b - l_b), (unsigned)(m - l_m), (unsigned)(l - l_l), (unsigned)(f - l_f), (unsigned)(h - l_h), (unsigned)(x - l_x), (unsigned)(w - l_w), (unsigned)sw_w);
  l_w = w; sw_w = 0;
  last = now; frames = 0; l_i = i; l_b = b; l_m = m; l_l = l; l_f = f; l_h = h; l_x = x;
}

void DG_DrawFrame(void) {
  perf_report();
  const uint32_t *fb = DG_ScreenBuffer;
  for (int y = 0; y < OLED_H; y++) {
    int r0 = y * DOOMGENERIC_RESY / OLED_H, r1 = ((y + 1) * DOOMGENERIC_RESY / OLED_H + r0) / 2;
    for (int x = 0; x < OLED_W; x++) {
      int c0 = x * DOOMGENERIC_RESX / OLED_W, c1 = ((x + 1) * DOOMGENERIC_RESX / OLED_W + c0) / 2;
      uint32_t p[4] = { fb[r0 * DOOMGENERIC_RESX + c0], fb[r0 * DOOMGENERIC_RESX + c1],
                        fb[r1 * DOOMGENERIC_RESX + c0], fb[r1 * DOOMGENERIC_RESX + c1] };
      uint32_t r = 0, g = 0, b = 0;
      for (int k = 0; k < 4; k++) { r += (p[k] >> 16) & 255; g += (p[k] >> 8) & 255; b += p[k] & 255; }
      OLED_FB[y * OLED_W + x] = rgb565(r / 4, g / 4, b / 4);
      sw_w++;
    }
  }
}

uint32_t DG_GetTicksMs(void) { return (uint32_t)(hw_cycles() / (HW_CLOCK_HZ / 1000u)); }

void DG_SleepMs(uint32_t ms) {
  uint64_t end = hw_cycles() + (uint64_t)ms * (HW_CLOCK_HZ / 1000u);
  while (hw_cycles() < end) {}
}

void DG_SetWindowTitle(const char *title) { (void)title; }

/* Keys: from the UART only (w a s d: arrows, f: fire, space: use, enter, escape, y, n,
   digits); a key is held for 150 ms. With nothing typed Doom plays its demos. */
static unsigned char uart_key;
static uint32_t uart_until;
static int told;

static unsigned char from_uart(int c) {
  switch (c) {
  case 'w': return KEY_UPARROW;   case 's': return KEY_DOWNARROW;
  case 'a': return KEY_LEFTARROW; case 'd': return KEY_RIGHTARROW;
  case 'f': return KEY_FIRE;      case ' ': return KEY_USE;
  case '\r': case '\n': return KEY_ENTER;
  case 27: return KEY_ESCAPE;
  default: return (c >= '0' && c <= '9') || c == 'y' || c == 'n' ? (unsigned char)c : 0;
  }
}

int DG_GetKey(int *pressed, unsigned char *key) {
  uint32_t now = DG_GetTicksMs();
  if (!told) {
    int c = (int)UART_DATA;
    unsigned char k = c < 0 ? 0 : from_uart(c);
    if (k) { uart_key = k; uart_until = now + 150; *pressed = 1; *key = k; told = 1; return 1; }
    return 0;
  }
  if (now >= uart_until) { told = 0; *pressed = 0; *key = uart_key; return 1; }
  return 0;
}

int main(int argc, char **argv) {
  static char *args[] = { "doom", "-iwad", "doom1.wad", 0 };
  (void)argc; (void)argv;
  printf("wiz-rv Doom: WAD %u bytes\n", (unsigned)*(volatile uint32_t *)WAD_LEN_ADDR);
  doomgeneric_Create(3, args);
  for (;;) doomgeneric_Tick();
}
