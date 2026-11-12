/* doomgeneric's sound for the wiz-rv machine: the sound effects (DMX lumps, 8-bit
   unsigned PCM at 11025 Hz, or another rate, resampled) mixed in software into one
   channel and written to the audio FIFO (hw.h: SND_DATA, played by PWM on JB pin 1).
   Each Update fills the FIFO; at a few frames a second it holds about 0.37 s.
   Music: the MUS lump's events drive a small synthesizer (MUSV square-wave voices with
   a decay envelope, percussion as noise bursts), mixed in with the effects. */
#include <stdio.h>
#include <string.h>
#include "doomtype.h"
#include "i_sound.h"
#include "w_wad.h"
#include "z_zone.h"
#include "hw.h"

#define NCH 8

typedef struct {
  const uint8_t *data;   /* NULL: free */
  uint32_t len;          /* samples */
  uint32_t pos, step;    /* 16.16 fixed point */
  int vol;               /* 0 … 127 */
} chan_t;
static chan_t ch[NCH];

static boolean snd_init(boolean use_sfx_prefix) { (void)use_sfx_prefix; memset(ch, 0, sizeof ch); return true; }
static void snd_shutdown(void) {}

static int snd_lump(sfxinfo_t *sfx) {
  char name[9];
  if (sfx->link) sfx = sfx->link;
  snprintf(name, sizeof name, "ds%s", sfx->name);
  return W_GetNumForName(name);
}

static int mus_sample(void);

/* one mixed sample: the sum of the channels, each (s - 128) * vol / 128, clipped */
static uint8_t mix1(void) {
  int acc = mus_sample();
  for (int i = 0; i < NCH; i++) {
    chan_t *c = &ch[i];
    if (!c->data) continue;
    uint32_t k = c->pos >> 16;
    if (k >= c->len) { c->data = NULL; continue; }
    acc += ((int)c->data[k] - 128) * c->vol / 128;
    c->pos += c->step;
  }
  acc += 128;
  return (uint8_t)(acc < 0 ? 0 : acc > 255 ? 255 : acc);
}

static void snd_update(void) {
#ifdef NO_SOUND_OUT
  return;   /* (a build without sound output, for testing: nix-build nix/doom.nix --arg sound false) */
#endif
  uint32_t n = SND_FREE;
  while (n--) SND_DATA = mix1();
}

static void snd_params(int c, int vol, int sep) { (void)sep; if (c >= 0 && c < NCH) ch[c].vol = vol; }

/* a DMX lump: format (3), rate, number of samples (with 16 padding bytes at either end) */
static int snd_start(sfxinfo_t *sfx, int c, int vol, int sep) {
  (void)sep;
  if (c < 0 || c >= NCH) return -1;
  int lump = sfx->lumpnum;
  const uint8_t *d = W_CacheLumpNum(lump, PU_STATIC);
  int size = W_LumpLength(lump);
  if (size < 8 || d[0] != 3 || d[1] != 0) return -1;
  uint32_t rate = d[2] | (d[3] << 8);
  uint32_t n = d[4] | (d[5] << 8) | (d[6] << 16) | ((uint32_t)d[7] << 24);
  if (n > (uint32_t)size - 8) n = size - 8;
  if (n <= 32) return -1;
  ch[c].data = d + 8 + 16;
  ch[c].len = n - 32;
  ch[c].pos = 0;
  ch[c].step = (uint32_t)(((uint64_t)rate << 16) / SND_RATE);
  ch[c].vol = vol;
  return c;
}

static void snd_stop(int c) { if (c >= 0 && c < NCH) ch[c].data = NULL; }
static boolean snd_playing(int c) { return c >= 0 && c < NCH && ch[c].data != NULL; }
static void snd_cache(sfxinfo_t *sounds, int n) { (void)sounds; (void)n; }

static snddevice_t devices[] = { SNDDEVICE_SB, SNDDEVICE_PAS, SNDDEVICE_GUS, SNDDEVICE_WAVEBLASTER,
  SNDDEVICE_SOUNDCANVAS, SNDDEVICE_AWE32 };

sound_module_t DG_sound_module = {
  devices, sizeof devices / sizeof devices[0],
  snd_init, snd_shutdown, snd_lump, snd_update, snd_params, snd_start, snd_stop, snd_playing, snd_cache
};

#include "mus_synth.c"   /* the synthesizer: MUS events, voices, mus_sample */

static boolean mus_init(void) { notes_init(); mus_on = 0; for (int i = 0; i < MUSV; i++) vo[i].chan = -1; return true; }
static void mus_shutdown(void) { mus_on = 0; }
static void mus_vol(int v) { mus_volume = v; }
static void mus_pause(void) { mus_paused = 1; }
static void mus_resume(void) { mus_paused = 0; }
/* a MUS lump: "MUS\x1a", score length, score start (16 bits each), … */
static void *mus_register(void *d, int n) {
  const uint8_t *b = d;
  if (n < 16 || memcmp(b, "MUS\x1a", 4)) return NULL;
  return d;
}
static void mus_unregister(void *h) { if (h == mus) { mus_on = 0; mus = NULL; } }
static void mus_play(void *h, boolean loop) {
  if (!h) return;
  const uint8_t *b = h;
  uint32_t len = b[4] | (b[5] << 8), start = b[6] | (b[7] << 8);
  mus = b; mus_score = b + start; mus_end = mus_score + len;
  mus_loop = loop; mus_reset(); mus_on = 1; mus_paused = 0;
}
static void mus_stop(void) { mus_on = 0; for (int i = 0; i < MUSV; i++) vo[i].chan = -1; }
static boolean mus_playing(void) { return mus_on; }

music_module_t DG_music_module = {
  devices, sizeof devices / sizeof devices[0],
  mus_init, mus_shutdown, mus_vol, mus_pause, mus_resume, mus_register, mus_unregister, mus_play, mus_stop, mus_playing, NULL
};

/* i_sound.c binds these settings (they belong to the SDL module elsewhere) */
int use_libsamplerate = 0;
float libsamplerate_scale = 0.65f;
