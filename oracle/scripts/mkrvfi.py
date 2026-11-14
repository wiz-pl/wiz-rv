#!/usr/bin/env python3
"""Generate the rvfi wrapper for a Wiz-emitted multi-cycle core.

    python3 oracle/scripts/mkrvfi.py --verilog build/rv32im_arty.v --out build/rvfi.v

The template is oracle/rtl/rvfi_shim.v.in.  This script reads the core's module
header and the state declarations it depends on, fills in the core name, the port
instantiation and the byte-lane word-address width, and fails loudly if a name has
changed (that is the drift check: the wrapper is coupled to the emitted Verilog's
flat register names, which the emitter derives from `CoreSt`'s fields).

Nothing here changes the core: it is a separate wrapper for riscv-formal.
"""
import argparse
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(os.path.dirname(HERE), "rtl", "rvfi_shim.v.in")

NEEDED_REGS = ["ph", "pc", "q0", "q1", "q2", "q3", "x1", "x2"]
NEEDED_MEMS = ["m0", "m1", "m2", "m3", "rfa"]


def parse_ports(header):
    body = header[header.index("(") + 1:header.rindex(")")]
    ports = []
    for part in body.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"(input|output|inout)\s+(?:\[(\d+):(\d+)\]\s+)?(\w+)$", part)
        if not m:
            raise SystemExit(f"mkrvfi: cannot parse port {part!r}")
        direction, hi, lo, name = m.groups()
        width = 1 if hi is None else abs(int(hi) - int(lo)) + 1
        ports.append((direction, width, name))
    return ports


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--verilog", default="build/rv32im_arty.v",
                   help="the emitted core (default: build/rv32im_arty.v)")
    p.add_argument("--out", default="build/rvfi.v",
                   help="the generated wrapper (default: build/rvfi.v)")
    args = p.parse_args(argv)

    with open(args.verilog) as f:
        text = f.read()

    m = re.search(r"^module\s+(\w+)\s*\(", text, re.M)
    if not m:
        raise SystemExit(f"mkrvfi: {args.verilog}: no module header")
    core = m.group(1)
    header = text[m.start():text.index(");", m.start()) + 2]
    ports = parse_ports(header)

    # A core emitted directly is `ph`, `pc`, …; one wrapped by a bundle field is
    # `cpu_ph`, … (the iCEstick `board` top has a `cpu` field in `Sys`).
    m = re.search(r"^\s*reg\s+\[[23]:0\]\s+(\w*)ph\s*;", text, re.M)
    if not m:
        raise SystemExit(f"mkrvfi: {args.verilog}: cannot find the phase register (<prefix>ph)")
    prefix = m.group(1)

    def nm(n):
        return prefix + n

    missing = [nm(r) for r in NEEDED_REGS
               if not re.search(r"^\s*reg\s+(\[[^]]*\]\s*)?%s\s*;" % re.escape(nm(r)), text, re.M)]
    missing += [f"{nm(mm)}[]" for mm in NEEDED_MEMS
                if not re.search(r"^\s*reg\s+\[[^]]*\]\s*%s\s*\[" % re.escape(nm(mm)), text, re.M)]
    # The trap state's emitted name depends on whether the design has a `trap` port:
    # the emitter uniquifies it to `trap_2` in that case, otherwise it is `trap`.
    trap = (nm("trap_2") if re.search(r"^\s*reg\s+\[2:0\]\s+%s\s*;" % re.escape(nm("trap_2")), text, re.M)
            else nm("trap") if re.search(r"^\s*reg\s+\[2:0\]\s+%s\s*;" % re.escape(nm("trap")), text, re.M)
            else "")
    if not trap:
        missing.append(nm("trap") + "/" + nm("trap_2"))
    if missing:
        raise SystemExit(
            f"mkrvfi: {args.verilog}: missing internal signal(s): {', '.join(missing)}\n"
            f"  the rvfi shim is coupled to the emitted flat state names; update\n"
            f"  oracle/rtl/rvfi_shim.v.in and this list if CoreSt's fields were renamed")

    m = re.search(r"^\s*reg\s+\[7:0\]\s+%s\s*\[0:(\d+)\];" % re.escape(nm("m0")), text, re.M)
    if not m:
        raise SystemExit(f"mkrvfi: cannot find the {nm('m0')} lane depth")
    depth = int(m.group(1)) + 1
    wb = int(math.log2(depth))
    if (1 << wb) != depth:
        raise SystemExit(f"mkrvfi: m0 depth {depth} is not a power of two")

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
               .replace("${TRAP}", trap)
               .replace("${P}", prefix)
               .replace("${WB}", str(wb)))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(out)
    print(f"{args.out}: rvfi wrapper for {core} ({wb}-bit word address, "
          f"{len(ports)} core ports)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
