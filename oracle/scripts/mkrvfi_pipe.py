#!/usr/bin/env python3
"""Generate the riscv-formal adapter for the pipeline's rvfi port.

    python3 oracle/scripts/mkrvfi_pipe.py --verilog build/oracle_rvfi.v --out build/rvfi_pipe.v

The template is oracle/rtl/rvfi_pipe.v.in.  **The emitted module carries the rvfi port
itself**: `oracle/wiz/emit_pipe.wiz` emits `Rv.Pipe.pipeRvfiCore`, whose outputs are
`Pp.rvfi` (src/Rv/Pipe.wiz), i.e.

    rvfi_valid, rvfi_insn, rvfi_trap, rvfi_halt, rvfi_intr,
    rvfi_rs1_addr/rdata, rvfi_rs2_addr/rdata, rvfi_rd_addr/rdata,
    rvfi_pc_rdata/pc_wdata, rvfi_mem_addr/rmask/wmask/rdata/wdata

so this script only ties the core's bus/I/O inputs and adds `rvfi_order` (a counter)
and `rvfi_mode`/`rvfi_ixl` (constants).  There are no hierarchical memory references
and no debug read ports: unlike the multi-cycle core, the pipeline's rvfi values are
latched in R (`rr_ins`, `rr_pcw`, `rr_ldw`; FINDINGS.md, H12), and the two register
operands are read from the architectural register file at R inside the design.

This script fails loudly if the emitted module's rvfi ports have drifted.

A deliberately *non*-formal use (Icarus) is the pipeline sequence trace:
`oracle.py rvfi --pipe` compiles the same two files plus tb_rvfi_pipe.v.in.
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(os.path.dirname(HERE), "rtl", "rvfi_pipe.v.in")

# The port `Pp.rvfi` must provide (src/Rv/Pipe.wiz).  `rvfi_order`, `rvfi_mode` and
# `rvfi_ixl` are the adapter's.
RVFI_OUTPUTS = [
    "rvfi_valid", "rvfi_insn", "rvfi_trap", "rvfi_halt", "rvfi_intr",
    "rvfi_rs1_addr", "rvfi_rs2_addr", "rvfi_rs1_rdata", "rvfi_rs2_rdata",
    "rvfi_rd_addr", "rvfi_rd_wdata", "rvfi_pc_rdata", "rvfi_pc_wdata",
    "rvfi_mem_addr", "rvfi_mem_rmask", "rvfi_mem_wmask",
    "rvfi_mem_rdata", "rvfi_mem_wdata",
]


def parse_ports(header):
    body = header[header.index("(") + 1:header.rindex(")")]
    ports = []
    for part in body.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"(input|output|inout)\s+(?:\[(\d+):(\d+)\]\s+)?(\w+)$", part)
        if not m:
            raise SystemExit(f"mkrvfi_pipe: cannot parse port {part!r}")
        direction, hi, lo, name = m.groups()
        width = 1 if hi is None else abs(int(hi) - int(lo)) + 1
        ports.append((direction, width, name))
    return ports


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--verilog", default="build/oracle_rvfi.v",
                   help="the emitted pipeline with the rvfi port (default: build/oracle_rvfi.v)")
    p.add_argument("--out", default="build/rvfi_pipe.v",
                   help="the generated adapter (default: build/rvfi_pipe.v)")
    args = p.parse_args(argv)

    with open(args.verilog) as f:
        text = f.read()

    m = re.search(r"^module\s+(\w+)\s*\(", text, re.M)
    if not m:
        raise SystemExit(f"mkrvfi_pipe: {args.verilog}: no module header")
    core = m.group(1)
    header = text[m.start():text.index(");", m.start()) + 2]
    ports = parse_ports(header)
    names = {name for _, _, name in ports}

    missing = [n for n in ["clk"] + RVFI_OUTPUTS if n not in names]
    if missing:
        raise SystemExit(
            f"mkrvfi_pipe: {args.verilog}: missing port(s): {', '.join(missing)}\n"
            f"  the emitted module must have Pp.rvfi's outputs; re-emit with\n"
            f"  oracle/wiz/emit_pipe.wiz (and check src/Rv/Pipe.wiz's Pp.rvfi)")

    # Inputs other than clk are tied high: the formal programs use the on-chip
    # memory only, so the bus/I/O inputs are never consulted.  Outputs are wired to
    # the adapter's same-named rvfi nets; anything else is left unconnected.
    ties = []
    for direction, width, name in ports:
        if direction == "input" and name == "clk":
            ties.append("    .clk(clk)")
        elif direction == "input":
            ties.append(f"    .{name}({{{width}{{1'b1}}}})" if width > 1 else f"    .{name}(1'b1)")
        elif name in RVFI_OUTPUTS:
            ties.append(f"    .{name}({name})")
        else:
            ties.append(f"    .{name}()")
    inst = [f"  {core} dut("] + [",\n".join(ties)] + ["  );"]

    with open(TEMPLATE) as f:
        tmpl = f.read()
    out = tmpl.replace("${CORE}", core).replace("${INSTANCE}", "\n".join(inst))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(out)
    print(f"{args.out}: rvfi adapter for {core} ({len(ports)} core ports)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
