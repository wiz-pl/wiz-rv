#!/usr/bin/env python3
"""Generate the oracle fixtures (oracle/fixtures/*.hex).

The fixtures are plain data so that the Wiz, Python, Sail and Spike sides all read
the same file.  A fixture is:

    <name>
    <cfg> <mbits> <steps> <mem_base> <mem_count>
    <instruction word as 8 hex digits, little-endian, at address 0>
    ...

`cfg` is `rv32i` (the Wiz side uses `Cfg.mk 5 mbits false`; the core trace uses
`ab = 5, wb = mbits - 2`).  `steps` is the number of instructions compared.  The
memory compared is `[mem_base, mem_base + mem_count)`; it is 0x2000 .. 0x21ff so
that it does not overlap the program image at 0 (and, for Spike, lies outside the
boot ROM at [0, 0x1000)).

This script is a tiny assembler, not part of the trusted oracle: it only turns the
programs below into words.  Run it from the repository root:

    python3 oracle/scripts/mkfixtures.py
"""
import os

# RISC-V register numbers
x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11 = range(12)
x12, x13, x14, x15, x16, x17, x18, x19, x20, x21, x22, x23 = range(12, 24)
x24, x25, x26, x27, x28, x29, x30, x31 = range(24, 32)


def r(fn, opcode, rd=0, rs1=0, rs2=0, f3=0):
    return ((fn & 0x7F) << 25) | ((rs2 & 0x1F) << 20) | ((rs1 & 0x1F) << 15) \
        | ((f3 & 7) << 12) | ((rd & 0x1F) << 7) | (opcode & 0x7F)


def i(imm, rs1, f3, rd, opcode):
    return ((imm & 0xFFF) << 20) | ((rs1 & 0x1F) << 15) | ((f3 & 7) << 12) \
        | ((rd & 0x1F) << 7) | (opcode & 0x7F)


def s(imm, rs2, rs1, f3, opcode):
    v = imm & 0xFFF
    return ((v >> 5) << 25) | ((rs2 & 0x1F) << 20) | ((rs1 & 0x1F) << 15) \
        | ((f3 & 7) << 12) | ((v & 0x1F) << 7) | (opcode & 0x7F)


def b(imm, rs2, rs1, f3):
    v = imm & 0x1FFF
    return (((v >> 12) & 1) << 31) | (((v >> 5) & 0x3F) << 25) \
        | ((rs2 & 0x1F) << 20) | ((rs1 & 0x1F) << 15) | ((f3 & 7) << 12) \
        | (((v >> 1) & 0xF) << 8) | (((v >> 11) & 1) << 7) | 0x63


def u(imm20, rd, opcode):
    return ((imm20 & 0xFFFFF) << 12) | ((rd & 0x1F) << 7) | (opcode & 0x7F)


def j(imm, rd):
    v = imm & 0x1FFFFF
    return (((v >> 20) & 1) << 31) | (((v >> 1) & 0x3FF) << 21) \
        | (((v >> 11) & 1) << 20) | (((v >> 12) & 0xFF) << 12) | ((rd & 0x1F) << 7) | 0x6F


def addi(rd, rs1, imm): return i(imm, rs1, 0, rd, 0x13)
def slti(rd, rs1, imm): return i(imm, rs1, 2, rd, 0x13)
def sltiu(rd, rs1, imm): return i(imm, rs1, 3, rd, 0x13)
def xori(rd, rs1, imm): return i(imm, rs1, 4, rd, 0x13)
def ori(rd, rs1, imm): return i(imm, rs1, 6, rd, 0x13)
def andi(rd, rs1, imm): return i(imm, rs1, 7, rd, 0x13)
def slli(rd, rs1, sh): return i(sh, rs1, 1, rd, 0x13)
def srli(rd, rs1, sh): return i(sh, rs1, 5, rd, 0x13)
def srai(rd, rs1, sh): return i(sh | 0x400, rs1, 5, rd, 0x13)


def rr(f3, rd, rs1, rs2, fn=0): return r(fn, 0x33, rd, rs1, rs2, f3)
def add(rd, rs1, rs2): return rr(0, rd, rs1, rs2)
def sub(rd, rs1, rs2): return rr(0, rd, rs1, rs2, 0x20)
def sll(rd, rs1, rs2): return rr(1, rd, rs1, rs2)
def slt(rd, rs1, rs2): return rr(2, rd, rs1, rs2)
def sltu(rd, rs1, rs2): return rr(3, rd, rs1, rs2)
def xor(rd, rs1, rs2): return rr(4, rd, rs1, rs2)
def srl(rd, rs1, rs2): return rr(5, rd, rs1, rs2)
def sra(rd, rs1, rs2): return rr(5, rd, rs1, rs2, 0x20)
def orr(rd, rs1, rs2): return rr(6, rd, rs1, rs2)
def andr(rd, rs1, rs2): return rr(7, rd, rs1, rs2)


# The M extension: OP with funct7 = 0000001 and funct3 0..7.
def mr(f3, rd, rs1, rs2): return rr(f3, rd, rs1, rs2, 0x01)
def mul(rd, rs1, rs2): return mr(0, rd, rs1, rs2)
def mulh(rd, rs1, rs2): return mr(1, rd, rs1, rs2)
def mulhsu(rd, rs1, rs2): return mr(2, rd, rs1, rs2)
def mulhu(rd, rs1, rs2): return mr(3, rd, rs1, rs2)
def div(rd, rs1, rs2): return mr(4, rd, rs1, rs2)
def divu(rd, rs1, rs2): return mr(5, rd, rs1, rs2)
def rem(rd, rs1, rs2): return mr(6, rd, rs1, rs2)
def remu(rd, rs1, rs2): return mr(7, rd, rs1, rs2)


def li(rd, val):
    """Load a 32-bit constant: LUI + ADDI, or a single ADDI when it fits."""
    val &= 0xFFFFFFFF
    if val >= 0xFFFFF800:                       # -2048 … -1
        return [addi(rd, x0, val - 0x100000000)]
    if val < 0x800:
        return [addi(rd, x0, val)]
    hi = (val >> 12) & 0xFFFFF
    lo = val & 0xFFF
    if lo & 0x800:
        hi = (hi + 1) & 0xFFFFF
        lo -= 0x1000
    out = [lui(rd, hi)]
    if lo:
        out.append(addi(rd, rd, lo))
    return out


def lui(rd, imm20): return u(imm20, rd, 0x37)
def auipc(rd, imm20): return u(imm20, rd, 0x17)
def jal(rd, imm): return j(imm, rd)
def jalr(rd, rs1, imm): return i(imm, rs1, 0, rd, 0x67)


def beq(rs1, rs2, imm): return b(imm, rs2, rs1, 0)
def bne(rs1, rs2, imm): return b(imm, rs2, rs1, 1)
def blt(rs1, rs2, imm): return b(imm, rs2, rs1, 4)
def bge(rs1, rs2, imm): return b(imm, rs2, rs1, 5)
def bltu(rs1, rs2, imm): return b(imm, rs2, rs1, 6)
def bgeu(rs1, rs2, imm): return b(imm, rs2, rs1, 7)


def lb(rd, rs1, imm): return i(imm, rs1, 0, rd, 0x03)
def lh(rd, rs1, imm): return i(imm, rs1, 1, rd, 0x03)
def lw(rd, rs1, imm): return i(imm, rs1, 2, rd, 0x03)
def lbu(rd, rs1, imm): return i(imm, rs1, 4, rd, 0x03)
def lhu(rd, rs1, imm): return i(imm, rs1, 5, rd, 0x03)
def sb(rs2, rs1, imm): return s(imm, rs2, rs1, 0, 0x23)
def sh(rs2, rs1, imm): return s(imm, rs2, rs1, 1, 0x23)
def sw(rs2, rs1, imm): return s(imm, rs2, rs1, 2, 0x23)


FENCE = 0x0FF0000F
SPIN = jal(x0, 0)

DATA = 0x2000  # the fixtures keep data here (Spike's boot ROM is [0, 0x1000))


def alu():
    """Every RV32I ALU form, with both operands' signs exercised."""
    return [
        addi(x1, x0, 5),        # x1 = 5
        addi(x2, x0, -3),       # x2 = -3
        add(x3, x1, x2),        # 2
        sub(x4, x1, x2),        # 8
        andr(x5, x1, x2),       # 5 & -3
        orr(x6, x1, x2),
        xor(x7, x1, x2),
        slt(x8, x1, x2),        # 0 (5 > -3 signed)
        sltu(x9, x1, x2),       # 1 (5 < 0xfffffffd unsigned)
        addi(x10, x0, 31),
        sll(x11, x1, x10),      # 5 << 31
        srl(x12, x2, x10),      # logical
        sra(x13, x2, x10),      # arithmetic
        slli(x14, x1, 4),
        srli(x15, x2, 4),
        srai(x16, x2, 4),
        slti(x17, x2, 0),       # 1
        sltiu(x18, x2, 0),      # 0
        xori(x19, x1, -1),
        ori(x20, x1, 0x0f0),
        andi(x21, x1, 0x0f0),
        lui(x22, 0x12345),
        auipc(x23, 1),
        addi(x0, x0, 0),        # a write to x0 must be ignored
        addi(x24, x1, 0),       # a write of the same value
        FENCE,
        SPIN,
    ]


def branch():
    """Taken/not-taken forms of every branch, and a short loop."""
    return [
        addi(x1, x0, 0),        # sum
        addi(x2, x0, 0),        # i
        addi(x3, x0, 10),
        # loop: i += 1; sum += i; if i < 10 goto loop
        addi(x2, x2, 1),
        add(x1, x1, x2),
        blt(x2, x3, -8),
        # taken / not-taken pairs (each skip is 8 bytes over one instruction)
        beq(x1, x1, 8),         # taken
        addi(x4, x0, 1),        # skipped
        addi(x5, x0, 2),
        bne(x1, x5, 8),         # taken
        addi(x6, x0, 3),        # skipped
        addi(x7, x0, 4),
        bge(x1, x5, 8),         # taken
        addi(x8, x0, 5),        # skipped
        addi(x9, x0, 6),
        bltu(x5, x1, 8),        # taken (2 < 55)
        addi(x10, x0, 7),       # skipped
        addi(x11, x0, 8),
        bgeu(x1, x5, 8),        # taken
        addi(x12, x0, 9),       # skipped
        addi(x13, x0, 10),
        # a not-taken branch falls through
        beq(x1, x5, 8),
        addi(x14, x0, 11),
        # jal writes its link; jalr jumps through a register
        jal(x15, 8),
        addi(x16, x0, 12),      # skipped by the jal
        addi(x17, x0, 13),
        auipc(x18, 0),
        addi(x18, x18, 16),
        jalr(x19, x18, 0),      # -> the instruction after the next 4
        addi(x20, x0, 14),      # skipped
        addi(x21, x0, 15),
        SPIN,
    ]


def mem():
    """Byte/half/word loads and stores, sign and zero extension, overlap."""
    return [
        lui(x1, 2),             # x1 = 0x2000 (DATA)
        lui(x2, 0x12345),
        addi(x2, x2, 0x678),
        sw(x2, x1, 0),
        lw(x3, x1, 0),
        lb(x4, x1, 0),          # 0x78, sign-extended
        lbu(x5, x1, 0),
        lb(x6, x1, 3),          # 0x12
        lh(x7, x1, 2),          # 0x1234
        lhu(x8, x1, 2),
        lh(x9, x1, 0),          # 0x5678
        addi(x10, x0, -1),
        sw(x10, x1, 8),         # 0xffffffff
        lw(x11, x1, 8),
        sb(x11, x1, 4),         # writes 0xff
        lbu(x12, x1, 4),
        sh(x11, x1, 6),         # writes 0xffff
        lhu(x13, x1, 6),
        lw(x14, x1, 4),         # the merged word
        addi(x15, x0, 0x55),
        sb(x15, x1, 0),         # overwrite the low byte
        lw(x16, x1, 0),
        sw(x3, x1, 12),
        lw(x17, x1, 12),
        SPIN,
    ]


def shift():
    """The shifter's edge cases: 0, 1, 31, and a register amount > 31."""
    return [
        lui(x1, 0x80000),       # 0x80000000
        addi(x1, x1, 0x7ff),    # 0x800007ff (sign bit set)
        addi(x2, x0, 0),
        addi(x3, x0, 1),
        addi(x4, x0, 31),
        addi(x5, x0, 32),
        addi(x6, x0, 63),
        slli(x7, x1, 0),
        srli(x8, x1, 0),
        srai(x9, x1, 0),
        slli(x10, x1, 1),
        srli(x11, x1, 1),
        srai(x12, x1, 1),
        slli(x13, x1, 31),
        srli(x14, x1, 31),
        srai(x15, x1, 31),
        sll(x16, x1, x2),
        sll(x17, x1, x3),
        srl(x18, x1, x4),
        sra(x19, x1, x4),
        sll(x20, x1, x5),       # shamt = 0 (low 5 bits)
        srl(x21, x1, x6),       # shamt = 31
        SPIN,
    ]


def mixed_program():
    """A little of everything, including a store inside a loop."""
    return [
        lui(x1, 2),
        addi(x2, x0, 0),
        addi(x3, x0, 6),
        # i*i without M: (i<<2)*i is not needed; use repeated addition: x6 = 0
        addi(x6, x0, 0),
        # inner: x6 += i, repeated i times is quadratic; use i*i = sum of first i odds
        # simpler: store 3*i+1
        slli(x4, x2, 1),        # 2i
        add(x4, x4, x2),        # 3i
        addi(x4, x4, 1),        # 3i+1
        slli(x5, x2, 2),
        add(x5, x1, x5),
        sw(x4, x5, 0),
        addi(x2, x2, 1),
        blt(x2, x3, -28),
        lw(x7, x1, 0),
        lw(x8, x1, 12),
        lw(x9, x1, 20),
        SPIN,
    ]


# The M fixtures share a prelude of constants in registers x6 … x18.  The
# instruction under test writes x3, so each result is visible in the pre-state of
# the next instruction (the trace compares every step).
def mprelude():
    prog = []
    prog += li(x6, 1)                 # 1
    prog += li(x7, 0xFFFFFFFF)        # -1
    prog += li(x8, 0x7FFFFFFF)        # INT_MAX
    prog += li(x9, 0x80000000)        # INT_MIN
    prog += li(x10, 0x12345678)
    prog += li(x11, 0x9ABCDEF0)
    prog += li(x12, 0xDEADBEEF)
    prog += li(x13, 0x0BADF00D)
    prog += li(x14, 0xFFFF)           # 0x0000ffff
    prog += li(x15, 0x10000)          # 0x00010000
    prog += li(x16, 0xFFFFFFF9)       # -7
    prog += li(x17, 2)
    prog += li(x18, 7)
    return prog


# Operand pairs: zero and same-register aliasing, small signed values, signed
# 32-bit edges, and two patterns that exercise both halves of the product.
MUL_PAIRS = [
    (x0, x0), (x6, x0), (x0, x6), (x6, x6),
    (x7, x6), (x6, x7), (x7, x7),
    (x8, x6), (x9, x7), (x9, x8),           # INT_MAX*1, INT_MIN*-1, INT_MIN*INT_MAX
    (x10, x11), (x12, x13), (x14, x14), (x15, x15),
]
DIV_PAIRS = [
    (x0, x0), (x6, x0), (x0, x6), (x6, x6), (x7, x6), (x6, x7), (x7, x7),
    (x9, x7), (x9, x6), (x6, x9), (x7, x9), (x9, x9),  # INT_MIN/-1, /1, 1/INT_MIN
    (x8, x7), (x16, x17), (x18, x7),                   # INT_MAX/-1, -7/2, 7/-1
    (x10, x11), (x12, x13), (x13, x6), (x13, x17),     # large unsigned, /2
]


def mfixture(op, pairs):
    prog = mprelude() + [op(x3, r1, r2) for (r1, r2) in pairs] + [SPIN]
    return ("rv32im", 14, len(prog), DATA, 256, prog)


def trap_ecall():
    """ECALL: the machine stops, cause 1, tval 0, epc the ECALL's address."""
    return [addi(x1, x0, 7), 0x00000073, 0x00100073, SPIN]


def trap_ebreak():
    """EBREAK: cause 2, tval 0."""
    return [addi(x1, x0, 9), 0x00100073, SPIN]


def trap_illegal():
    """An all-ones word is not an RV32I instruction: cause 3, tval the word."""
    return [addi(x1, x0, 1), 0xFFFFFFFF, SPIN]


def trap_load():
    """LW at 2 (x1 = 2): cause 5, tval the effective address 2."""
    return [addi(x1, x0, 2), lw(x2, x1, 0), SPIN]


def trap_store():
    """SW at 2: cause 6, tval the effective address 2."""
    return [addi(x1, x0, 2), sw(x2, x1, 0), SPIN]


def trap_jump():
    """JALR to 2: cause 4, tval the target 2."""
    return [addi(x1, x0, 2), jalr(x0, x1, 0), SPIN]


FIXTURES = {
    "alu": ("rv32i", 14, 32, DATA, 256, alu()),
    "branch": ("rv32i", 14, 40, DATA, 256, branch()),
    "mem": ("rv32i", 14, 32, DATA, 256, mem()),
    "shift": ("rv32i", 14, 32, DATA, 256, shift()),
    "mixed": ("rv32i", 14, 40, DATA, 256, mixed_program()),
    "mul": mfixture(mul, MUL_PAIRS),
    "mulh": mfixture(mulh, MUL_PAIRS),
    "mulhsu": mfixture(mulhsu, MUL_PAIRS),
    "mulhu": mfixture(mulhu, MUL_PAIRS),
    "div": mfixture(div, DIV_PAIRS),
    "divu": mfixture(divu, DIV_PAIRS),
    "rem": mfixture(rem, DIV_PAIRS),
    "remu": mfixture(remu, DIV_PAIRS),
    # traps: the Wiz machine stops (cause/tval/epc); the trace pads with stutters to
    # `steps + 1` states. Sail/Spike are skipped for these (they enter a handler).
    "trap_ecall": ("rv32i", 14, 6, DATA, 256, trap_ecall()),
    "trap_ebreak": ("rv32i", 14, 6, DATA, 256, trap_ebreak()),
    "trap_illegal": ("rv32i", 14, 6, DATA, 256, trap_illegal()),
    "trap_load": ("rv32i", 14, 6, DATA, 256, trap_load()),
    "trap_store": ("rv32i", 14, 6, DATA, 256, trap_store()),
    "trap_jump": ("rv32i", 14, 6, DATA, 256, trap_jump()),
}


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(os.path.dirname(here), "fixtures")
    os.makedirs(out, exist_ok=True)
    for name, (cfg, mbits, steps, mbase, mcount, words) in FIXTURES.items():
        path = os.path.join(out, name + ".hex")
        with open(path, "w") as f:
            f.write(f"{name}\n")
            f.write(f"{cfg} {mbits} {steps} {mbase} {mcount}\n")
            for w in words:
                f.write(f"{w & 0xFFFFFFFF:08x}\n")
        print(f"{path}: {len(words)} words")


if __name__ == "__main__":
    main()
