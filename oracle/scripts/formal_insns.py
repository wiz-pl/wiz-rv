#!/usr/bin/env python3
"""Formal fixtures: one instruction, repeated through the whole lane memory.

riscv-formal's `insn_<name>_ch0` check constrains the core to retire that
instruction at the check cycle and compares its architectural effect.  The Wiz
core is emitted with a fixed program, so the check is only non-vacuous if the
instruction stream consists of the instruction under test.  This script writes a
fixture that repeats one valid encoding through all 64 words of the formal core's
1 KB (FORMAL_MBITS=8), and prints the sby check cycle and the ISA string for that
instruction class:

    3  ALU, LUI/AUIPC, JAL/JALR, branches, shifts (2-cycle retirement)
    4  loads (E, M, D: the write is in M, the beat at the following D)
    4  the multiply half of M (E, X, D: the product is written in X)
    35 the divide half of M (E, 32 V cycles, D: the quotient is written in V)

With every word the instruction under test, its operands are whatever the
preceding copies left behind: for M that is x2 = x3 = 0, so `insn_div`/`insn_rem`
formally check the divide-by-zero path, and the arithmetic cases are covered by
the trace fixtures (`oracle.py run`).  The ISA string is `rv32im` for the M
instructions (the emitted core then has the multiplier/divider) and `rv32i`
otherwise.

Usage:
    python3 oracle/scripts/formal_insns.py --list
    python3 oracle/scripts/formal_insns.py --list --muldiv
    python3 oracle/scripts/formal_insns.py --name add --out oracle/.build/formal-add.hex
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkfixtures as M  # noqa: E402

x0, x1, x2, x3 = 0, 1, 2, 3

# A valid RV32I encoding per check name (the 37 base-I names in
# riscv-formal's insns/isa_rv32i.txt).  Operands are x0/zero-valued registers;
# addresses are 0, hence aligned; branches/jumps target themselves or 0, where
# the repeated instruction also lives.
WORDS = {
    "add":     M.add(x1, x2, x3),
    "addi":    M.addi(x1, x2, 0),
    "and":     M.andr(x1, x2, x3),
    "andi":    M.andi(x1, x2, 0),
    "auipc":   M.auipc(x1, 0),
    "beq":     M.beq(x1, x1, 0),
    "bge":     M.bge(x1, x1, 0),
    "bgeu":    M.bgeu(x1, x1, 0),
    "blt":     M.blt(x1, x2, 0),
    "bltu":    M.bltu(x1, x2, 0),
    "bne":     M.bne(x1, x2, 0),
    "jal":     M.jal(x1, 0),
    "jalr":    M.jalr(x1, x0, 0),
    "lb":      M.lb(x1, x0, 0),
    "lbu":     M.lbu(x1, x0, 0),
    "lh":      M.lh(x1, x0, 0),
    "lhu":     M.lhu(x1, x0, 0),
    "lui":     M.lui(x1, 0),
    "lw":      M.lw(x1, x0, 0),
    "or":      M.orr(x1, x2, x3),
    "ori":     M.ori(x1, x2, 0),
    "sb":      M.sb(x1, x0, 0),
    "sh":      M.sh(x1, x0, 0),
    "sll":     M.sll(x1, x2, x3),
    "slli":    M.slli(x1, x2, 0),
    "slt":     M.slt(x1, x2, x3),
    "slti":    M.slti(x1, x2, 0),
    "sltiu":   M.sltiu(x1, x2, 0),
    "sltu":    M.sltu(x1, x2, x3),
    "sra":     M.sra(x1, x2, x3),
    "srai":    M.srai(x1, x2, 0),
    "srl":     M.srl(x1, x2, x3),
    "srli":    M.srli(x1, x2, 0),
    "sub":     M.sub(x1, x2, x3),
    "sw":      M.sw(x1, x0, 0),
    "xor":     M.xor(x1, x2, x3),
    "xori":    M.xori(x1, x2, 0),
    # M extension (riscv-formal's insns/isa_rv32im.txt; no separate `rvfi_muldiv`
    # check exists at the pinned revision — `isa rv32im` makes genchecks.py emit
    # these eight `insn_*_ch0` checks from the Sail-derived models).
    "mul":     M.mul(x1, x2, x3),
    "mulh":    M.mulh(x1, x2, x3),
    "mulhsu":  M.mulhsu(x1, x2, x3),
    "mulhu":   M.mulhu(x1, x2, x3),
    "div":     M.div(x1, x2, x3),
    "divu":    M.divu(x1, x2, x3),
    "rem":     M.rem(x1, x2, x3),
    "remu":    M.remu(x1, x2, x3),
}

LOADS = {"lb", "lbu", "lh", "lhu", "lw"}
MUL = {"mul", "mulh", "mulhsu", "mulhu"}
DIV = {"div", "divu", "rem", "remu"}
MULDIV = MUL | DIV


def names(muldiv_only=False):
    return sorted(MULDIV if muldiv_only else WORDS)


def isa_of(name):
    return "rv32im" if name in MULDIV else "rv32i"


def depth_of(name):
    if name in DIV:
        return 35          # E at 2, 32 V cycles, D at 35
    if name in MUL:
        return 4           # E at 2, X at 3, D at 4
    if name in LOADS:
        return 4
    return 3


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name")
    p.add_argument("--out")
    p.add_argument("--list", action="store_true")
    p.add_argument("--muldiv", action="store_true",
                   help="with --list: only the M-extension instructions")
    args = p.parse_args(argv)
    if args.list:
        print("\n".join(names(args.muldiv)))
        return 0
    if not args.name or not args.out:
        print(__doc__)
        return 2
    if args.name not in WORDS:
        raise SystemExit(f"formal_insns: unknown instruction {args.name!r} "
                         f"(have: {' '.join(names())})")
    word = WORDS[args.name]
    # mbits=8 -> wb=6 -> 64 byte addresses per lane; 64 words fill every lane.
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(f"formal-{args.name}\n")
        f.write(f"{isa_of(args.name)} 8 0 0 0\n")
        for _ in range(64):
            f.write(f"{word & 0xFFFFFFFF:08x}\n")
    # depth and ISA string, read by run-rvfi.sh
    print(f"{depth_of(args.name)} {isa_of(args.name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
