#!/usr/bin/env python3
"""An independent RV32IM/Zicsr reference interpreter and trace generator.

This is the *always-available* oracle: it is written from the RISC-V unprivileged
ISA manual (RV32I v2.1, the M extension, and the bounded Zicsr subset in
`wiz-rv/README.md`) and from the machine description in wiz-rv/README.md, not
from `src/Rv/Isa.wiz`.  It produces the same trace format as the Wiz side:

    S <step> <pc> <trap> <x0> … <x31> <mem bytes>
    # …                       (comments)

The Wiz machine's documented choices are followed where the ISA leaves a choice:
misaligned loads/stores and jump targets stop the machine with a trap code instead
of trapping into a handler; ECALL/EBREAK/illegal instructions likewise stop; a
store to an address with bit 31 set writes the output port; a load from such an
address takes a byte from the input port.  The fixtures in `oracle/fixtures` avoid
those Wiz-specific cases; they are here so that a fixture that does exercise them
has a defined reference.
Zicsr is the same bounded subset as the machine: `mscratch` (0x340) and the six
CSR instructions; any other CSR number is an illegal instruction.  The M extension
is enabled by a `rv32im` fixture cfg.  `signature()` returns the final signature
region, which `oracle/arch-test` uses as one of its references.

Usage:
    python3 rv32_ref.py FIXTURE [FIXTURE …]
    python3 rv32_ref.py --check FIXTURE TRACE      # compare one trace file
"""
import sys

MASK32 = 0xFFFFFFFF
MASK5 = 0x1F

TRAP_NONE = 0
TRAP_ECALL = 1
TRAP_EBREAK = 2
TRAP_ILLEGAL = 3
TRAP_JUMP = 4
TRAP_LOAD = 5
TRAP_STORE = 6


def sx(value, bits):
    """Two's-complement sign extension of `value` from `bits` to 32 bits."""
    value &= (1 << bits) - 1
    if value & (1 << (bits - 1)):
        return (value - (1 << bits)) & MASK32
    return value


def s32(x):
    x &= MASK32
    return x - (1 << 32) if x & 0x80000000 else x


def u(h, lo, n):
    return (h >> lo) & ((1 << n) - 1)


def expand_c(h):
    """Expand a 16-bit (RV32C) instruction to its 32-bit equivalent.

    Returns None for an illegal encoding (the reserved ones and the floating-point
    forms, which this machine does not have). This is the Python side of the same
    table as Rv.expand in src/Rv/Isa.wiz; the oracle compares them through the
    instruction traces.
    """
    def enc_i(op, f3, rd_, rs1, imm):
        return ((imm & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd_ << 7) | op

    def enc_s(op, f3, rs1, rs2_, imm):
        return (((imm >> 5) & 0x7F) << 25) | (rs2_ << 20) | (rs1 << 15) | (f3 << 12) \
            | ((imm & 0x1F) << 7) | op

    def enc_b(f3, rs1, rs2_, imm):
        return (((imm >> 12) & 1) << 31) | (((imm >> 5) & 0x3F) << 25) | (rs2_ << 20) \
            | (rs1 << 15) | (f3 << 12) | (((imm >> 1) & 0xF) << 8) | (((imm >> 11) & 1) << 7) | 0x63

    def enc_u(op, rd_, imm):
        return ((imm & 0xFFFFF000)) | (rd_ << 7) | op

    def enc_j(rd_, imm):
        return (((imm >> 20) & 1) << 31) | (((imm >> 1) & 0x3FF) << 21) | (((imm >> 11) & 1) << 20) \
            | (((imm >> 12) & 0xFF) << 12) | (rd_ << 7) | 0x6F

    def enc_r(op, f3, f7, rd_, rs1, rs2_):
        return (f7 << 25) | (rs2_ << 20) | (rs1 << 15) | (f3 << 12) | (rd_ << 7) | op

    q, f3, b12 = h & 3, u(h, 13, 3), u(h, 12, 1)
    rd, rs2 = u(h, 7, 5), u(h, 2, 5)
    rdp, rs1p = u(h, 2, 3) + 8, u(h, 7, 3) + 8
    imm6 = sx((b12 << 5) | u(h, 2, 5), 6)

    if q == 0:
        if f3 == 0:                                        # C.ADDI4SPN
            nz = u(h, 11, 2) * 16 + u(h, 7, 4) * 64 + u(h, 6, 1) * 4 + u(h, 5, 1) * 8
            return None if nz == 0 else enc_i(0x13, 0, rdp, 2, nz)
        if f3 == 2:                                        # C.LW
            i = u(h, 10, 3) * 8 + u(h, 6, 1) * 4 + u(h, 5, 1) * 64
            return enc_i(0x03, 2, rdp, rs1p, i)
        if f3 == 6:                                        # C.SW
            i = u(h, 10, 3) * 8 + u(h, 6, 1) * 4 + u(h, 5, 1) * 64
            return enc_s(0x23, 2, rs1p, rdp, i)
        return None                                        # C.FLD/C.FLW/C.FSD/C.FSW/reserved

    if q == 1:
        if f3 == 0:                                        # C.ADDI / C.NOP (and hints)
            return enc_i(0x13, 0, rd, rd, imm6)
        if f3 == 1:                                        # C.JAL (RV32)
            v = sx(u(h, 12, 1) * 2048 + u(h, 8, 1) * 1024 + u(h, 10, 2) * 256
                   + u(h, 6, 1) * 128 + u(h, 7, 1) * 64 + u(h, 2, 1) * 32
                   + u(h, 11, 1) * 16 + u(h, 3, 3) * 2, 12)
            return enc_j(1, v)
        if f3 == 2:                                        # C.LI
            return enc_i(0x13, 0, rd, 0, imm6)
        if f3 == 3:
            if rd == 2:                                    # C.ADDI16SP
                v = sx(u(h, 12, 1) * 512 + u(h, 4, 1) * 256 + u(h, 3, 1) * 128
                       + u(h, 5, 1) * 64 + u(h, 2, 1) * 32 + u(h, 6, 1) * 16, 10)
                return None if v == 0 else enc_i(0x13, 0, 2, 2, v)
            if rd == 0:                                    # reserved
                return None
            v = sx((b12 << 17) | (u(h, 2, 5) << 12), 18)  # C.LUI
            return None if v == 0 else enc_u(0x37, rd, v)
        if f3 == 4:
            sub = u(h, 10, 2)
            sh = (b12 << 5) | u(h, 2, 5)
            if sub == 0:                                   # C.SRLI
                return None if b12 == 1 else enc_i(0x13, 5, rs1p, rs1p, sh)
            if sub == 1:                                   # C.SRAI
                return None if b12 == 1 else enc_i(0x13, 5, rs1p, rs1p, 0x400 | sh)
            if sub == 2:                                   # C.ANDI
                return enc_i(0x13, 7, rs1p, rs1p, imm6)
            if b12 == 1:                                   # C.SUBW/C.ADDW: RV64 only
                return None
            g = u(h, 5, 2)
            if g == 0:
                return enc_r(0x33, 0, 0x20, rs1p, rs1p, rdp)   # C.SUB
            if g == 1:
                return enc_r(0x33, 4, 0, rs1p, rs1p, rdp)      # C.XOR
            if g == 2:
                return enc_r(0x33, 6, 0, rs1p, rs1p, rdp)      # C.OR
            return enc_r(0x33, 7, 0, rs1p, rs1p, rdp)          # C.AND
        if f3 == 5:                                        # C.J
            v = sx(u(h, 12, 1) * 2048 + u(h, 8, 1) * 1024 + u(h, 10, 2) * 256
                   + u(h, 6, 1) * 128 + u(h, 7, 1) * 64 + u(h, 2, 1) * 32
                   + u(h, 11, 1) * 16 + u(h, 3, 3) * 2, 12)
            return enc_j(0, v)
        v = sx(u(h, 12, 1) * 256 + u(h, 6, 1) * 128 + u(h, 5, 1) * 64
               + u(h, 2, 1) * 32 + u(h, 11, 1) * 16 + u(h, 10, 1) * 8
               + u(h, 4, 1) * 4 + u(h, 3, 1) * 2, 9)
        return enc_b(0, rs1p, 0, v) if f3 == 6 else enc_b(1, rs1p, 0, v)

    if q == 2:
        if f3 == 0:                                        # C.SLLI
            return None if b12 == 1 else enc_i(0x13, 1, rd, rd, u(h, 2, 5))
        if f3 == 2:                                        # C.LWSP
            if rd == 0:
                return None
            i = u(h, 2, 2) * 64 + b12 * 32 + u(h, 4, 3) * 4
            return enc_i(0x03, 2, rd, 2, i)
        if f3 == 4:
            if b12 == 0:
                if rs2 == 0:                               # C.JR
                    return None if rd == 0 else enc_i(0x67, 0, 0, rd, 0)
                return enc_r(0x33, 0, 0, rd, 0, rs2)       # C.MV (rd = 0 is a hint)
            if rd == 0:
                if rs2 == 0:                               # C.EBREAK
                    return 0x00100073
                return None                                # reserved
            if rs2 == 0:                                   # C.JALR
                return enc_i(0x67, 0, 1, rd, 0)
            return enc_r(0x33, 0, 0, rd, rd, rs2)          # C.ADD
        if f3 == 6:                                        # C.SWSP
            i = u(h, 7, 2) * 64 + u(h, 9, 4) * 4
            return enc_s(0x23, 2, 2, rs2, i)
        return None                                        # C.FLDSP/C.FLWSP/C.FSDSP/C.FSWSP

    return None


class Fixture:
    def __init__(self, path):
        with open(path) as f:
            lines = [l.strip() for l in f.read().splitlines()]
        lines = [l for l in lines if l and not l.startswith("#")]
        self.name = lines[0]
        cfg = lines[1].split()
        self.cfg = cfg[0]
        self.mbits = int(cfg[1])
        self.steps = int(cfg[2])
        self.mbase = int(cfg[3])
        self.mcount = int(cfg[4])
        # a line of 8 hex digits is a 32-bit instruction (two halfwords, low first);
        # 4 digits is a 16-bit (C) instruction. The image is halfwords.
        self.halves = []
        for l in lines[2:]:
            v = int(l, 16)
            if len(l) <= 4:
                self.halves.append(v & 0xFFFF)
            else:
                self.halves.append(v & 0xFFFF)
                self.halves.append((v >> 16) & 0xFFFF)
        self.words = self.halves          # the legacy name (oracle.py)
        self.path = path


class Machine:
    def __init__(self, fx):
        self.cfg = fx.cfg
        self.rbits = 5
        self.mbits = fx.mbits
        self.mx = "m" in fx.cfg or "M" in fx.cfg
        self.pc = 0
        self.regs = [0] * (1 << self.rbits)
        self.mem = bytearray(1 << self.mbits)
        for i, h in enumerate(fx.halves):
            self.mem[2 * i:2 * i + 2] = h.to_bytes(2, "little")
        self.trap = TRAP_NONE
        self.tval = 0
        self.epc = 0
        self.out = []
        self.inp = list(getattr(fx, "input", []))
        self.csr = 0  # mscratch (0x340), the one CSR this machine has

    # -- machine helpers -------------------------------------------------------

    def maddr(self, a):
        a &= MASK32
        # Wiz: DDR is bit 30 set and bit 31 clear; everything else wraps at 2^mbits.
        if (a >> 30) & 1 and not ((a >> 31) & 1):
            return a
        return a % (1 << self.mbits)

    def byte(self, a):
        m = self.maddr(a)
        return self.mem[m] if m < len(self.mem) else 0

    def word(self, a):
        return sum(self.byte((a + i) & MASK32) << (8 * i) for i in range(4))

    def fetch(self):
        return self.word(self.pc)

    def reg(self, i):
        return 0 if i == 0 else self.regs[i]

    def write(self, rd, value, pc):
        if rd != 0:
            self.regs[rd] = value & MASK32
        self.pc = pc & MASK32

    def stop(self, code, tval=0):
        # a stopped machine records the cause, what faulted and the trapping PC
        self.trap = code
        self.tval = tval & MASK32
        self.epc = self.pc

    # -- instruction semantics -------------------------------------------------

    def exec_one(self, w):
        op = w & 0x7F
        rd = (w >> 7) & MASK5
        f3 = (w >> 12) & 0x7
        r1 = (w >> 15) & MASK5
        r2 = (w >> 20) & MASK5
        f7 = (w >> 25) & 0x7F
        a = self.reg(r1)
        b = self.reg(r2)
        nxt = (self.pc + self.ilen) & MASK32
        imm_i = sx(w >> 20, 12)
        imm_s = sx(((w >> 25) << 5) | ((w >> 7) & 0x1F), 12)
        imm_b = sx((((w >> 31) & 1) << 12) | (((w >> 7) & 1) << 11)
                   | (((w >> 25) & 0x3F) << 5) | (((w >> 8) & 0xF) << 1), 13)
        imm_u = w & 0xFFFFF000
        imm_j = sx((((w >> 31) & 1) << 20) | (((w >> 12) & 0xFF) << 12)
                   | (((w >> 20) & 1) << 11) | (((w >> 21) & 0x3FF) << 1), 21)

        def alu(f3_, alt, x, y):
            if f3_ == 0:
                return (x - y) & MASK32 if alt else (x + y) & MASK32
            if f3_ == 1:
                return (x << (y & MASK5)) & MASK32
            if f3_ == 2:
                return 1 if s32(x) < s32(y) else 0
            if f3_ == 3:
                return 1 if x < y else 0
            if f3_ == 4:
                return (x ^ y) & MASK32
            if f3_ == 5:
                if alt:                      # SRA
                    return (s32(x) >> (y & MASK5)) & MASK32
                return (x & MASK32) >> (y & MASK5)
            if f3_ == 6:
                return (x | y) & MASK32
            return (x & y) & MASK32

        def jump(rd_, value, target):
            if target % 2 != 0:
                self.stop(TRAP_JUMP, target)
            else:
                self.write(rd_, value, target)

        def ok_reg(r):
            return r < (1 << self.rbits)

        def ok2(x, y):
            return ok_reg(x) and ok_reg(y)

        def ok3(x, y, z):
            return ok_reg(x) and ok2(y, z)

        if op == 0x37:                                   # LUI
            if ok_reg(rd):
                self.write(rd, imm_u, nxt)
            else:
                self.stop(TRAP_ILLEGAL, self.rawins)
        elif op == 0x17:                                 # AUIPC
            if ok_reg(rd):
                self.write(rd, (self.pc + imm_u) & MASK32, nxt)
            else:
                self.stop(TRAP_ILLEGAL, self.rawins)
        elif op == 0x6F:                                 # JAL
            if ok_reg(rd):
                jump(rd, nxt, (self.pc + imm_j) & MASK32)
            else:
                self.stop(TRAP_ILLEGAL, self.rawins)
        elif op == 0x67:                                 # JALR
            if f3 == 0 and ok2(rd, r1):
                t = ((a + imm_i) & MASK32) & ~1
                jump(rd, nxt, t)
            else:
                self.stop(TRAP_ILLEGAL, self.rawins)
        elif op == 0x63:                                 # BRANCH
            if f3 in (2, 3) or not ok2(r1, r2):
                self.stop(TRAP_ILLEGAL, self.rawins)
            else:
                if f3 == 0:
                    taken = a == b
                elif f3 == 1:
                    taken = a != b
                elif f3 == 4:
                    taken = s32(a) < s32(b)
                elif f3 == 5:
                    taken = not (s32(a) < s32(b))
                elif f3 == 6:
                    taken = a < b
                else:
                    taken = not (a < b)
                if taken:
                    jump(0, 0, (self.pc + imm_b) & MASK32)
                else:
                    self.write(0, 0, nxt)
        elif op == 0x03:                                 # LOAD
            if not (f3 < 3 or f3 in (4, 5)) or not ok2(rd, r1):
                self.stop(TRAP_ILLEGAL, self.rawins)
            else:
                ad = (a + imm_i) & MASK32
                size = 1 << (f3 & 3)
                if ad % size != 0:
                    self.stop(TRAP_LOAD, ad)
                elif (ad >> 31) & 1:
                    v = self.inp.pop(0) if self.inp else MASK32
                    self.write(rd, v, nxt)
                else:
                    if f3 == 0:
                        v = sx(self.byte(ad), 8)
                    elif f3 == 1:
                        v = sx(self.byte(ad) | (self.byte((ad + 1) & MASK32) << 8), 16)
                    else:
                        v = sum(self.byte((ad + i) & MASK32) << (8 * i) for i in range(size))
                    self.write(rd, v, nxt)
        elif op == 0x23:                                 # STORE
            if f3 > 2 or not ok2(r1, r2):
                self.stop(TRAP_ILLEGAL, self.rawins)
            else:
                ad = (a + imm_s) & MASK32
                size = 1 << f3
                if ad % size != 0:
                    self.stop(TRAP_STORE, ad)
                elif (ad >> 31) & 1:
                    self.out.append(b & 0xFF)
                    self.pc = nxt
                else:
                    for i in range(size):
                        self.mem[(self.maddr(ad) + i) % (1 << self.mbits)] = (b >> (8 * i)) & 0xFF
                    self.pc = nxt
        elif op == 0x13:                                 # OP-IMM
            ok_imm = (f7 == 0) if f3 == 1 else ((f7 == 0 or f7 == 0x20) if f3 == 5 else True)
            if ok_imm and ok2(rd, r1):
                self.write(rd, alu(f3, f3 == 5 and f7 == 0x20, a, imm_i), nxt)
            else:
                self.stop(TRAP_ILLEGAL, self.rawins)
        elif op == 0x33:                                 # OP
            ok_op = f7 == 0 or (f7 == 0x20 and f3 in (0, 5))
            if ok_op and ok3(rd, r1, r2):
                self.write(rd, alu(f3, f7 == 0x20, a, b), nxt)
            elif self.mx and f7 == 1 and ok3(rd, r1, r2):
                self.write(rd, muldiv(f3, a, b), nxt)
            else:
                self.stop(TRAP_ILLEGAL, self.rawins)
        elif op == 0x0F:                                 # FENCE (a no-op here)
            self.write(0, 0, nxt)
        elif op == 0x73:                                 # SYSTEM
            if w == 0x00000073:
                self.stop(TRAP_ECALL, 0)
            elif w == 0x00100073:
                self.stop(TRAP_EBREAK, 0)
            elif ((w >> 20) & 0xFFF) == 0x340 and f3 in (1, 2, 3, 5, 6, 7):
                # Zicsr, mscratch: the source is rs1's value, or rs1's field for the
                # immediate forms; the set/clear forms write only a non-zero source.
                src = a if f3 < 4 else r1
                old = self.csr
                if f3 in (1, 5):
                    self.csr = src & MASK32
                elif f3 in (2, 6):
                    if src != 0:
                        self.csr = (self.csr | src) & MASK32
                else:
                    if src != 0:
                        self.csr = self.csr & (~src & MASK32)
                self.write(rd, old, nxt)
            else:
                self.stop(TRAP_ILLEGAL, self.rawins)
        else:
            self.stop(TRAP_ILLEGAL, self.rawins)

    def step(self):
        if self.trap != 0:
            return
        h = self.byte(self.pc) | (self.byte((self.pc + 1) & MASK32) << 8)
        if h & 3 != 3:
            w = expand_c(h)
            self.ilen = 2
            self.rawins = h
            if w is None:
                self.stop(TRAP_ILLEGAL, h)
            else:
                self.exec_one(w)
        else:
            self.ilen = 4
            w = self.word(self.pc)
            self.rawins = w
            self.exec_one(w)

    # -- trace -----------------------------------------------------------------

    def state_line(self, fx, k):
        regs = [self.reg(i) for i in range(32)]
        mem = [self.mem[(fx.mbase + i) % (1 << self.mbits)] for i in range(fx.mcount)]
        fields = [f"S {k} {self.pc:08x} {self.trap:08x}"]
        fields += [f"{r:08x}" for r in regs]
        fields += [f"{b:02x}" for b in mem]
        return " ".join(fields)

    def trap_line(self, k):
        return f"T {k} {self.trap:08x} {self.tval:08x} {self.epc:08x}"


def muldiv(f3, a, b):
    """The M extension (enabled by a `rv32im` fixture cfg)."""
    au, bu = a & MASK32, b & MASK32
    as_, bs = s32(au), s32(bu)
    if f3 == 0:
        return (au * bu) & MASK32
    if f3 == 1:
        p = as_ * bs
        return (p >> 32) & MASK32
    if f3 == 2:
        p = as_ * bu
        return (p >> 32) & MASK32
    if f3 == 3:
        p = au * bu
        return (p >> 32) & MASK32
    if f3 == 4:
        if bu == 0:
            return MASK32
        q = abs(as_) // abs(bs)
        if (as_ < 0) != (bs < 0):
            q = -q
        return q & MASK32
    if f3 == 5:
        return MASK32 if bu == 0 else (au // bu) & MASK32
    if f3 == 6:
        if bu == 0:
            return au
        r = abs(as_) % abs(bs)
        if as_ < 0:
            r = -r
        return r & MASK32
    return au if bu == 0 else (au % bu) & MASK32


def trace(fx):
    m = Machine(fx)
    lines = [f"# rv-oracle-trace v1", f"# fixture {fx.name}", "# trace py",
             f"# cfg {fx.cfg} mbits {fx.mbits} steps {fx.steps} "
             f"mem_base {fx.mbase} mem_count {fx.mcount}"]
    for k in range(fx.steps + 1):
        lines.append(m.state_line(fx, k))
        lines.append(m.trap_line(k))
        if k < fx.steps:
            m.step()
    return lines


def signature(fx):
    """The signature region after `fx.steps` steps (or at the trapping instruction)."""
    m = Machine(fx)
    for _ in range(fx.steps):
        if m.trap != 0:
            break
        m.step()
    return [m.mem[(fx.mbase + i) % (1 << fx.mbits)] for i in range(fx.mcount)]


def main(argv):
    if len(argv) >= 2 and argv[1] == "--check":
        if len(argv) != 4:
            print(__doc__)
            return 2
        from oracle import parse_trace, compare_traces, report
        a = parse_trace(argv[3])
        b = trace(Fixture(argv[2]))
        ok = compare_traces(a, b, report("ref", "trace"), limit=20)
        return 0 if ok else 1
    if len(argv) < 2:
        print(__doc__)
        return 2
    for path in argv[1:]:
        fx = Fixture(path)
        print("\n".join(trace(fx)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
