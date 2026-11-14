#!/usr/bin/env python3
"""An independent RV32I reference interpreter and trace generator.

This is the *always-available* oracle: it is written from the RISC-V unprivileged
ISA manual (RV32I, v2.1) and from the machine description in wiz-rv/README.md, not
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
        self.words = [int(l, 16) for l in lines[2:]]
        self.mx = self.cfg == "rv32im"
        self.path = path


class Machine:
    def __init__(self, fx):
        self.cfg = fx.cfg
        self.rbits = 5
        self.mbits = fx.mbits
        self.mx = (fx.cfg == "rv32im")
        self.pc = 0
        self.regs = [0] * (1 << self.rbits)
        self.mem = bytearray(1 << self.mbits)
        for i, w in enumerate(fx.words):
            self.mem[4 * i:4 * i + 4] = w.to_bytes(4, "little")
        self.trap = TRAP_NONE
        self.out = []
        self.inp = list(getattr(fx, "input", []))

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

    def stop(self, code):
        self.trap = code

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
        nxt = (self.pc + 4) & MASK32
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
            if target % 4 != 0:
                self.stop(TRAP_JUMP)
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
                self.stop(TRAP_ILLEGAL)
        elif op == 0x17:                                 # AUIPC
            if ok_reg(rd):
                self.write(rd, (self.pc + imm_u) & MASK32, nxt)
            else:
                self.stop(TRAP_ILLEGAL)
        elif op == 0x6F:                                 # JAL
            if ok_reg(rd):
                jump(rd, nxt, (self.pc + imm_j) & MASK32)
            else:
                self.stop(TRAP_ILLEGAL)
        elif op == 0x67:                                 # JALR
            if f3 == 0 and ok2(rd, r1):
                t = ((a + imm_i) & MASK32) & ~1
                jump(rd, nxt, t)
            else:
                self.stop(TRAP_ILLEGAL)
        elif op == 0x63:                                 # BRANCH
            if f3 in (2, 3) or not ok2(r1, r2):
                self.stop(TRAP_ILLEGAL)
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
                self.stop(TRAP_ILLEGAL)
            else:
                ad = (a + imm_i) & MASK32
                size = 1 << (f3 & 3)
                if ad % size != 0:
                    self.stop(TRAP_LOAD)
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
                self.stop(TRAP_ILLEGAL)
            else:
                ad = (a + imm_s) & MASK32
                size = 1 << f3
                if ad % size != 0:
                    self.stop(TRAP_STORE)
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
                self.stop(TRAP_ILLEGAL)
        elif op == 0x33:                                 # OP
            ok_op = f7 == 0 or (f7 == 0x20 and f3 in (0, 5))
            if ok_op and ok3(rd, r1, r2):
                self.write(rd, alu(f3, f7 == 0x20, a, b), nxt)
            elif self.mx and f7 == 1 and ok3(rd, r1, r2):
                self.write(rd, muldiv(f3, a, b), nxt)
            else:
                self.stop(TRAP_ILLEGAL)
        elif op == 0x0F:                                 # FENCE (a no-op here)
            self.write(0, 0, nxt)
        elif op == 0x73:                                 # SYSTEM
            if w == 0x00000073:
                self.stop(TRAP_ECALL)
            elif w == 0x00100073:
                self.stop(TRAP_EBREAK)
            else:
                self.stop(TRAP_ILLEGAL)
        else:
            self.stop(TRAP_ILLEGAL)

    def step(self):
        if self.trap == 0:
            self.exec_one(self.fetch())

    # -- trace -----------------------------------------------------------------

    def state_line(self, fx, k):
        regs = [self.reg(i) for i in range(32)]
        mem = [self.mem[(fx.mbase + i) % (1 << self.mbits)] for i in range(fx.mcount)]
        fields = [f"S {k} {self.pc:08x} {self.trap:08x}"]
        fields += [f"{r:08x}" for r in regs]
        fields += [f"{b:02x}" for b in mem]
        return " ".join(fields)


def muldiv(f3, a, b):
    """The M extension: MUL, MULH, MULHSU, MULHU, DIV, DIVU, REM, REMU.

    Signed division truncates toward zero and the remainder takes the dividend's
    sign.  Division by zero returns all ones (the dividend for REM/REMU) and
    INT_MIN / -1 returns INT_MIN (remainder 0), as the ISA specifies.
    """
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
        if k < fx.steps:
            m.step()
    return lines


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
