#!/usr/bin/env python3
"""Add read-only debug ports to an emitted core, for riscv-formal.

Yosys's Verilog parser does not resolve hierarchical references to a memory
(`dut.cpu_rfa[i]`, `dut.cpu_m0[j]`) the way Icarus does; it treats them as an
undriven wire, so a formal wrapper that observes the register file or the byte
lanes through `dut.*` sees x.  This script adds the read ports to the *copy* of
the emitted core used by the formal harness:

    input  [4:0]    dbg_rd -> output [31:0] dbg_rfa = <prefix>rfa[dbg_rd]
    input  [WB-1:0] dbg_wa -> output [31:0] dbg_mem = {<prefix>m3[dbg_wa], ...}
    output [3:0]    dbg_ph, dbg_pc[31:0], dbg_q0..q3[7:0], dbg_x1/x2[31:0],
                    dbg_trap[2:0]

The core's datapath, memories and initial values are unchanged; the ports are
combinational reads of the existing state.  mkrvfi.py --formal drives them and
uses the outputs in the rvfi beats.

    python3 oracle/scripts/formal_core.py core.v core-formal.v
"""
import math
import re
import sys


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    src, dst = argv[1], argv[2]
    with open(src) as f:
        text = f.read()

    m = re.search(r"^module\s+(\w+)\s*\(", text, re.M)
    if not m:
        raise SystemExit("formal_core: no module header")
    header_end = text.index(");", m.start()) + 2
    header = text[m.start():header_end]

    pm = re.search(r"^\s*reg\s+\[[23]:0\]\s+(\w*)ph\s*;", text, re.M)
    if not pm:
        raise SystemExit("formal_core: cannot find <prefix>ph")
    prefix = pm.group(1)
    mm = re.search(r"^\s*reg\s+\[7:0\]\s+%sm0\s*\[0:(\d+)\];" % re.escape(prefix), text, re.M)
    if not mm:
        raise SystemExit("formal_core: cannot find <prefix>m0")
    depth = int(mm.group(1)) + 1
    wb = int(math.log2(depth))
    if (1 << wb) != depth:
        raise SystemExit("formal_core: m0 depth is not a power of two")

    # The module header is one line in the emitter; insert before `);`.
    new_ports = (
        ", input [4:0] dbg_rd, input [%d:0] dbg_wa, "
        "output [3:0] dbg_ph, output [31:0] dbg_pc, "
        "output [7:0] dbg_q0, output [7:0] dbg_q1, "
        "output [7:0] dbg_q2, output [7:0] dbg_q3, "
        "output [31:0] dbg_x1, output [31:0] dbg_x2, output [2:0] dbg_trap, "
        "output [31:0] dbg_rfa, output [31:0] dbg_mem") % (wb - 1)
    new_header = header[:-2] + new_ports + ");\n"
    text = text[:m.start()] + new_header + text[header_end:]

    trap_reg = prefix + ("trap_2" if re.search(
        r"^\s*reg\s+\[2:0\]\s+%strap_2\s*;" % re.escape(prefix), text, re.M) else "trap")
    assigns = (
        "\n  // formal debug read ports (added by oracle/scripts/formal_core.py)\n"
        f"  assign dbg_ph = {prefix}ph;\n"
        f"  assign dbg_pc = {prefix}pc;\n"
        f"  assign dbg_q0 = {prefix}q0;\n"
        f"  assign dbg_q1 = {prefix}q1;\n"
        f"  assign dbg_q2 = {prefix}q2;\n"
        f"  assign dbg_q3 = {prefix}q3;\n"
        f"  assign dbg_x1 = {prefix}x1;\n"
        f"  assign dbg_x2 = {prefix}x2;\n"
        f"  assign dbg_trap = {trap_reg};\n"
        f"  assign dbg_rfa = {prefix}rfa[dbg_rd];\n"
        f"  assign dbg_mem = {{{prefix}m3[dbg_wa], {prefix}m2[dbg_wa], "
        f"{prefix}m1[dbg_wa], {prefix}m0[dbg_wa]}};\n"
    )
    end = text.rfind("endmodule")
    if end < 0:
        raise SystemExit("formal_core: no endmodule")
    text = text[:end] + assigns + text[end:]

    with open(dst, "w") as f:
        f.write(text)
    print(f"{dst}: added dbg_rd/dbg_wa/dbg_rfa/dbg_mem ({wb}-bit word address)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
