/* newlib's system calls on the wiz-rv machine: the console is the UART, the heap is
   DDR after the program, and the one file there is is the WAD the boot loader put in
   DDR ("doom1.wad", read only). */
#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>
#include "hw.h"

extern char _end[];
static char *brk = _end;

void *_sbrk(ptrdiff_t n) {
  char *old = brk;
  if (brk + n > (char *)HEAP_END) { errno = ENOMEM; return (void *)-1; }
  brk += n;
  return old;
}

static void uart_put(char c) { UART_DATA = (uint8_t)c; }

#define WAD_FD 3
static long wad_pos = -1;   /* -1: not open */
static long wad_len(void) { return *(volatile uint32_t *)WAD_LEN_ADDR; }

int _open(const char *path, int flags, int mode) {
  (void)flags; (void)mode;
  const char *base = strrchr(path, '/');
  base = base ? base + 1 : path;
  if (strcmp(base, "doom1.wad") == 0 && wad_len() > 0 && wad_pos < 0) { wad_pos = 0; return WAD_FD; }
  errno = ENOENT;
  return -1;
}
int _close(int fd) { if (fd == WAD_FD) wad_pos = -1; return 0; }

int _read(int fd, char *buf, int n) {
  if (fd == WAD_FD) {
    long left = wad_len() - wad_pos;
    if (n > left) n = left;
    memcpy(buf, (const char *)WAD_BASE + wad_pos, n);
    wad_pos += n;
    return n;
  }
  if (fd == 0) {            /* the UART, without waiting: what has arrived */
    int k = 0;
    while (k < n) { int c = (int)UART_DATA; if (c < 0) break; buf[k++] = (char)c; }
    return k;
  }
  errno = EBADF;
  return -1;
}

int _write(int fd, const char *buf, int n) {
  if (fd == 1 || fd == 2) {
    for (int k = 0; k < n; k++) { if (buf[k] == '\n') uart_put('\r'); uart_put(buf[k]); }
    return n;
  }
  errno = EBADF;
  return -1;
}

int _lseek(int fd, int off, int whence) {
  if (fd != WAD_FD) { errno = ESPIPE; return -1; }
  long p = whence == 0 ? off : whence == 1 ? wad_pos + off : wad_len() + off;
  if (p < 0 || p > wad_len()) { errno = EINVAL; return -1; }
  wad_pos = p;
  return (int)p;
}

int _fstat(int fd, struct stat *st) {
  memset(st, 0, sizeof *st);
  if (fd == WAD_FD) { st->st_mode = S_IFREG; st->st_size = wad_len(); }
  else st->st_mode = S_IFCHR;
  return 0;
}
int _stat(const char *path, struct stat *st) {
  int fd = _open(path, 0, 0);
  if (fd < 0) return -1;
  _fstat(fd, st); _close(fd);
  return 0;
}
int _isatty(int fd) { return fd < 3; }
int _gettimeofday(struct timeval *tv, void *tz) {
  (void)tz;
  uint64_t us = hw_cycles() / (HW_CLOCK_HZ / 1000000u);
  tv->tv_sec = us / 1000000u; tv->tv_usec = us % 1000000u;
  return 0;
}
int _getpid(void) { return 1; }
int _kill(int pid, int sig) { (void)pid; (void)sig; errno = EINVAL; return -1; }
int _unlink(const char *p) { (void)p; errno = EROFS; return -1; }
int _link(const char *a, const char *b) { (void)a; (void)b; errno = EROFS; return -1; }
int mkdir(const char *p, mode_t m) { (void)p; (void)m; errno = EROFS; return -1; }
