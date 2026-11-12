/* The music synthesizer for sound_wizrv.c (and sw/iss/mustest.c, on the host): MUS score
   events drive MUSV voices; mus_sample gives one signed sample at SND_RATE. No Doom
   headers: it needs SND_RATE, <stdint.h>, <string.h>. */
/* music: MUS (a MIDI-like score: 16 channels, 15 the percussion; events at 140 Hz) */
#define MUSV 6
typedef struct {
  int chan, note;        /* chan -1: free */
  uint32_t phase, step;  /* a square wave: the top bit of phase */
  int amp, env;          /* env: 0 … 4096, decays; amp: the velocity times the volume */
  int rel;               /* released: decaying fast */
  int noise;             /* percussion: noise instead of the square */
  uint32_t age;
} voice_t;
static voice_t vo[MUSV];
static const uint8_t *mus, *mus_score, *mus_end, *mus_p;
static int mus_on, mus_loop, mus_paused, mus_volume = 100;
static int chvol[16], chvel[16];
static uint32_t mus_wait;        /* samples to the next events, 24.8 fixed point */
static uint32_t notestep[128];   /* phase steps for 11025 Hz */
static uint32_t lfsr = 1, vage;

static void notes_init(void) {
  /* 440 Hz at note 69; each semitone a factor 2^(1/12), in 16.16 */
  static const uint32_t semi[12] = { 65536, 69433, 73562, 77936, 82570, 87480, 92682, 98193,
    104032, 110218, 116772, 123715 };
  for (int n = 0; n < 128; n++) {
    int o = n / 12 - 5, k = n % 12;   /* note 60 (C4): 261.63 Hz */
    uint64_t f = (uint64_t)26163 * semi[k];                  /* Hz × 100 × 65536 */
    f = o >= 0 ? f << o : f >> -o;
    notestep[n] = (uint32_t)((f << 16) / (100ull * SND_RATE));  /* (f / 100 / 65536) × 2^32 / rate */
  }
}

static void mus_reset(void) {
  for (int i = 0; i < MUSV; i++) vo[i].chan = -1;
  for (int c = 0; c < 16; c++) { chvol[c] = 100; chvel[c] = 100; }
  mus_p = mus_score; mus_wait = 0;
}

static void note_off(int c, int n) {
  for (int i = 0; i < MUSV; i++) if (vo[i].chan == c && vo[i].note == n) vo[i].rel = 1;
}

static void note_on(int c, int n, int vel) {
  int best = 0;   /* a free voice, else a released one, else the oldest */
  for (int i = 0; i < MUSV; i++) {
    int si = vo[i].chan < 0 ? 0 : vo[i].rel ? 1 : 2, sb = vo[best].chan < 0 ? 0 : vo[best].rel ? 1 : 2;
    if (si < sb || (si == sb && vo[i].age < vo[best].age)) best = i;
  }
  voice_t *v = &vo[best];
  v->chan = c; v->note = n; v->rel = 0; v->env = 4096; v->age = ++vage;
  v->noise = c == 15;
  v->step = notestep[n & 127]; v->phase = 0;
  v->amp = vel * chvol[c] / 127;   /* 0 … 127 */
}

/* the events up to the next delay */
static void mus_events(void) {
  for (;;) {
    if (mus_p >= mus_end) { if (mus_loop) mus_reset(); else { mus_on = 0; return; } }
    uint8_t e = *mus_p++;
    int c = e & 15, t = (e >> 4) & 7;
    switch (t) {
      case 0: note_off(c, *mus_p++ & 127); break;
      case 1: { uint8_t n = *mus_p++; if (n & 128) chvel[c] = *mus_p++ & 127; note_on(c, n & 127, chvel[c]); break; }
      case 2: mus_p++; break;                       /* pitch bend: ignored */
      case 3: { uint8_t k = *mus_p++; if (k == 10 || k == 11) for (int i = 0; i < MUSV; i++) if (vo[i].chan == c) vo[i].rel = 1; break; }
      case 4: { uint8_t k = *mus_p++, v = *mus_p++; if (k == 3) chvol[c] = v & 127; break; }
      case 5: break;
      case 6: if (mus_loop) { mus_reset(); continue; } mus_on = 0; return;
      default: break;
    }
    if (e & 128) {    /* a delay in ticks (140 Hz), 7 bits a byte */
      uint32_t d = 0; uint8_t b;
      do { b = *mus_p++; d = (d << 7) | (b & 127); } while (b & 128);
      mus_wait += d * (SND_RATE * 256 / 140);
      if (mus_wait >= 256) return;
    }
  }
}

static int mus_sample(void) {
  if (!mus_on || mus_paused) return 0;
  while (mus_wait < 256 && mus_on) mus_events();
  if (mus_wait >= 256) mus_wait -= 256;
  int acc = 0;
  for (int i = 0; i < MUSV; i++) {
    voice_t *v = &vo[i];
    if (v->chan < 0) continue;
    int s;
    if (v->noise) { lfsr = (lfsr >> 1) ^ (-(lfsr & 1) & 0xd0000001u); s = (lfsr & 1) ? 1 : -1; }
    else { v->phase += v->step; s = (v->phase >> 31) ? 1 : -1; }
    acc += s * v->amp * v->env;
    /* decay: notes to about a third in 0.5 s, released or percussion in about 40 ms */
    v->env -= v->rel || v->noise ? (v->env >> 6) + 1 : (v->env >> 12) + (v->env > 1400);
    if (v->env <= 0) v->chan = -1;
  }
  /* 6 voices at full velocity and volume: ±144 (mix1 clips); a typical score peaks about ±70 */
  return acc / (127 * 4096 / 24) * mus_volume / 127;
}

