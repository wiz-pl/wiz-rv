#!/usr/bin/env python3
"""Generate the retirement-observation shim for a Wiz-emitted pipelined core.

    python3 oracle/scripts/mkrvfi_pipe.py --verilog build/oracle_pipe.v --out build/rvfi_pipe.v

The template is oracle/rtl/rvfi_pipe.v.in.  Unlike the multi-cycle core, the
pipeline has no `ph`/`pc`/`q` projection and its R stage does not carry the
instruction word, so this shim observes `PpSt`'s flat state directly:

    rr_v, rr_miss, rr_pc, rr_we, rr_rd, rr_val, rr_trap,
    ms_rfa (register file), ms_mi0..3 (fetch lanes), ms_md0..3 (data lanes)

A beat is a retirement: `rr_v && !rr_miss`, the same condition as
`src/Rv/PLockstep.wiz`.  This is a *documented shim*, not riscv-formal's `rvfi`
checker interface: `rvfi_insn` is the on-chip instruction word at `rr_pc`, and
`rvfi_pc_wdata` is decoded from the ISA with the architectural register values,
because R holds no next-PC register.  `rvfi_rd_wdata` and `rvfi_rd_addr` are the
core's own (`rr_val`/`rr_we`/`rr_rd`), and the trap is `rr_trap`.  The sequence
trace check (`oracle.py rvfi --pipe`) prints the pre-state from the core's
register file and data memory; the formal `insn_*` checks are not claimed for
the pipeline (no `rvfi_muldiv` either).

This script fails loudly if the emitted state names have drifted.
"""
import argparse
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(os.path.dirname(HERE), "rtl", "rvfi_pipe.v.in")

NEEDED_REGS = ["rr_v", "rr_miss", "rr_pc", "rr_we", "rr_rd", "rr_val", "rr_trap"]
NEEDED_MEMS = ["ms_rfa", "ms_mi0", "ms_mi1", "ms_mi2", "ms_mi3",
               "ms_md0", "ms_md1", "ms_md2", "ms_md3"]


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
    p.add_argument("--verilog", default="build/oracle_pipe.v",
                   help="the emitted pipeline (default: build/oracle_pipe.v)")
    p.add_argument("--out", default="build/rvfi_pipe.v",
                   help="the generated wrapper (default: build/rvfi_pipe.v)")
    args = p.parse_args(argv)

    with open(args.verilog) as f:
        text = f.read()

    m = re.search(r"^module\s+(\w+)\s*\(", text, re.M)
    if not m:
        raise SystemExit(f"mkrvfi_pipe: {args.verilog}: no module header")
    core = m.group(1)
    header = text[m.start():text.index(");", m.start()) + 2]
    ports = parse_ports(header)

    missing = [r for r in NEEDED_REGS
               if not re.search(r"^\s*reg\s+(\[[^]]*\]\s*)?%s\s*;" % re.escape(r), text, re.M)]
    missing += [f"{mm}[]" for mm in NEEDED_MEMS
                if not re.search(r"^\s*reg\s+\[[^]]*\]\s*%s\s*\[" % re.escape(mm), text, re.M)]
    if missing:
        raise SystemExit(
            f"mkrvfi_pipe: {args.verilog}: missing internal signal(s): {', '.join(missing)}\n"
            f"  the pipeline shim is coupled to the emitted flat pp state names;\n"
            f"  update oracle/rtl/rvfi_pipe.v.in and this list if PpSt's fields were renamed")

    m = re.search(r"^\s*reg\s+\[7:0\]\s+ms_mi0\s*\[0:(\d+)\];", text, re.M)
    if not m:
        raise SystemExit("mkrvfi_pipe: cannot find the ms_mi0 lane depth")
    depth = int(m.group(1)) + 1
    wb = int(math.log2(depth))
    if (1 << wb) != depth:
        raise SystemExit(f"mkrvfi_pipe: ms_mi0 depth {depth} is not a power of two")

    inst = [f"  {core} dut("]
    ties = []
    for direction, width, name in ports:
        if direction == "input" and name == "clk":
            ties.append("    .clk(clk)")
        elif direction == "input":
            ties.append(f"    .{name}({{{width}{{1'b1}}}})" if width > 1 else f"    .{name}(1'b1)")
        else:
            ties.append(f"    .{name}()")
    inst.append(",\n".join(ties))
    inst.append("  );")

    with open(TEMPLATE) as f:
        tmpl = f.read()
    out = (tmpl.replace("${CORE}", core)
               .replace("${INSTANCE}", "\n".join(inst))
               .replace("${WB}", str(wb)))
    reads = {
        "RR_V": "dut.rr_v", "RR_MISS": "dut.rr_miss", "RR_PC": "dut.rr_pc",
        "RR_WE": "dut.rr_we", "RR_RD": "dut.rr_rd", "RR_VAL": "dut.rr_val",
        "RR_TRAP": "dut.rr_trap",
        "RFA": "dut.ms_rfa",
        "MI0": "dut.ms_mi0", "MI1": "dut.ms_mi1", "MI2": "dut.ms_mi2", "MI3": "dut.ms_mi3",
        "MD0": "dut.ms_md0", "MD1": "dut.ms_md1", "MD2": "dut.ms_md2", "MD3": "dut.ms_md3",
    }
    for key, value in reads.items():
        out = out.replace("${" + key + "}", value)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(out)
    print(f"{args.out}: pipeline rvfi shim for {core} ({wb}-bit word address, "
          f"{len(ports)} core ports)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
