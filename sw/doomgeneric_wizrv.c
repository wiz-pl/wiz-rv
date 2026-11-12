/* doomgeneric's platform layer for the wiz-rv Arty machine (hw.h):
   - the 320 x 200 frame, downscaled to the PmodOLEDrgb's 96 x 64 (RGB565), each OLED
     pixel the average of a block of the frame;
   - time from the cycle counter;
   - keys from the thumbstick (directions: arrows, its button: fire), the board's
     buttons (BTN1: use, BTN2: enter, BTN3: escape) and the UART (w a s d, space: use,
     f: fire, enter, escape, y, n, digits). */
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
void DG_DrawFrame(void) {
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
    }
  }
}

uint32_t DG_GetTicksMs(void) { return (uint32_t)(hw_cycles() / (HW_CLOCK_HZ / 1000u)); }

void DG_SleepMs(uint32_t ms) {
  uint64_t end = hw_cycles() + (uint64_t)ms * (HW_CLOCK_HZ / 1000u);
  while (hw_cycles() < end) {}
}

void DG_SetWindowTitle(const char *title) { (void)title; }

/* Keys: the held state of each source is compared with what Doom was last told; a
   change becomes one event. UART keys are "pressed" for a few frames. */
enum { K_UP, K_DOWN, K_LEFT, K_RIGHT, K_FIRE, K_USE, K_ENTER, K_ESC, K_UART, K_N };
static const unsigned char keycode[K_N] = { KEY_UPARROW, KEY_DOWNARROW, KEY_LEFTARROW, KEY_RIGHTARROW,
  KEY_FIRE, KEY_USE, KEY_ENTER, KEY_ESCAPE, 0 };
static int told[K_N];
static unsigned char uart_key;
static uint32_t uart_until;

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
  int held[K_N];
  int x = (int)JOY_X - 2048, y = (int)JOY_Y - 2048;
  uint32_t btn = JOY_BUTTONS;
  held[K_UP] = y < -700; held[K_DOWN] = y > 700;
  held[K_LEFT] = x < -700; held[K_RIGHT] = x > 700;
  held[K_FIRE] = btn & 1; held[K_USE] = (btn >> 5) & 1;
  held[K_ENTER] = (btn >> 6) & 1; held[K_ESC] = (btn >> 7) & 1;
  uint32_t now = DG_GetTicksMs();
  if (!told[K_UART]) {
    int c = (int)UART_DATA;
    unsigned char k = c < 0 ? 0 : from_uart(c);
    if (k) { uart_key = k; uart_until = now + 150; }
  }
  held[K_UART] = uart_key && now < uart_until;
  for (int i = 0; i < K_N; i++) {
    if (held[i] != told[i]) {
      told[i] = held[i];
      *pressed = held[i];
      *key = i == K_UART ? uart_key : keycode[i];
      return 1;
    }
  }
  return 0;
}

int main(int argc, char **argv) {
  static char *args[] = { "doom", "-iwad", "doom1.wad", 0 };
  (void)argc; (void)argv;
  printf("wiz-rv Doom: WAD %u bytes\n", (unsigned)*(volatile uint32_t *)WAD_LEN_ADDR);
  doomgeneric_Create(3, args);
  for (;;) doomgeneric_Tick();
}
