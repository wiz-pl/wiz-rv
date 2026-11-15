#!/usr/bin/env python3
"""Run the official riscv-arch-test suite against the Wiz RV32I/M core.

This is the opt-in, bounded part of the RISC-V verification: the hand-written
fixtures in oracle/fixtures exercise instructions in isolation, while the arch suite
runs generated programs that check one instruction across many operands, registers
and corners, and compares a signature (a region of memory the test writes) against
the suite's reference.

    suite      the vendored official sources (oracle/arch-test/suite, from
               riscv-arch-test release 2.0 for I/M and the 2026 suite for Zicsr)
    dut        Rv.Core on a flat image, run by oracle/wiz/arch_run.wiz
    reference  the suite's .reference_output for I/M; for Zicsr (which the 2.0
               release does not have) a signature produced by Spike from the same
               source and the same minimal environment, committed under expected/.

Only I, M and Zicsr are vendored, and only the tests whose instructions the machine
implements.  Misaligned accesses (which the Wiz machine traps, an implementation
choice the ISA allows) are reported as failures, not hidden in a skip list.

Commands
    list [--suite I,M,Zicsr]
    build [--suite ...]               compile the sources into ELFs (bounded)
    run [--suite ...] [--tests ...] [--timeout N] [--spike]
    fixture --tests ... --out DIR     write the fixed subset's fixtures and expected
                                      signatures for the `tests/rv/arch-test` group
    selftest                          check the reporter with a perturbed signature

A missing toolchain, arch_run binary, or vendored source is a clean SKIP (exit 0),
never a pass.  A failing comparison exits 1 and prints the first differing signature
words; a fixture that ran out of its step budget or stopped on a non-EBREAK trap is
reported separately, because that is a core/harness problem rather than a wrong
result.

Environment
    WIZ_RV_GCC      the RISC-V gcc (default: riscv32-none-elf-gcc on PATH, then the
                    newest /nix/store/*-riscv32-none-elf-gcc-wrapper-*/bin/...)
    SPIKE           Spike (default: `spike` on PATH, then /nix/store/*-spike-*/bin/spike)
    DTC             dtc, which Spike invokes (default: `dtc` on PATH, then /nix/store)
"""
import argparse
import glob
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SUITE = os.path.join(HERE, "suite")
ENVDIR = os.path.join(HERE, "env")
EXPECTED = os.path.join(HERE, "expected")
BUILDDIR = os.path.join(ROOT, "oracle", ".build", "arch-test")

# suite name -> (source dir, arch, reference dir or None)
SUITES = {
    "I": (os.path.join(SUITE, "rv32i_m", "I", "src"), "rv32i",
          os.path.join(SUITE, "rv32i_m", "I", "references")),
    "M": (os.path.join(SUITE, "rv32i_m", "M", "src"), "rv32im",
          os.path.join(SUITE, "rv32i_m", "M", "references")),
    "Zicsr": (os.path.join(SUITE, "rv32i_m", "Zicsr", "src"), "rv32i_zicsr", None),
}
ALL = ["I", "M", "Zicsr"]


class Report:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.details = []

    def ok(self, name, note=""):
        self.passed += 1
        self.details.append(("PASS", name, note))

    def fail(self, name, note=""):
        self.failed += 1
        self.details.append(("FAIL", name, note))

    def skip(self, name, note=""):
        self.skipped += 1
        self.details.append(("SKIP", name, note))

    def print(self):
        for kind, name, note in self.details:
            print(f"{kind:4s} {name}" + (": " + note if note else ""))
        print(f"# {self.passed} passed, {self.failed} failed, {self.skipped} skipped")
        return 1 if self.failed else 0


# ---------------------------------------------------------------------------
# Tools


def _find_pattern(pattern, what, env):
    val = os.environ.get(env)
    if val:
        return val
    found = shutil.which(what)
    if found:
        return found
    hits = sorted(glob.glob(pattern))
    return hits[-1] if hits else None


def find_gcc(explicit=None):
    if explicit:
        return explicit
    return _find_pattern("/nix/store/*-riscv32-none-elf-gcc-wrapper-*/bin/riscv32-none-elf-gcc",
                         "riscv32-none-elf-gcc", "WIZ_RV_GCC")


def find_tool(explicit, suffix, pattern, what, env):
    if explicit:
        return explicit
    gcc = find_gcc()
    if gcc:
        cand = os.path.join(os.path.dirname(gcc), suffix)
        if os.path.exists(cand):
            return cand
    return _find_pattern(pattern, what, env)


def find_spike(explicit=None):
    return _find_pattern("/nix/store/*-spike-*/bin/spike", "spike", "SPIKE") if not explicit else explicit


def find_dtc(explicit=None):
    if explicit:
        return explicit
    found = shutil.which("dtc")
    if found:
        return found
    hits = sorted(glob.glob("/nix/store/*-dtc-*/bin/dtc"))
    return hits[-1] if hits else None


# ---------------------------------------------------------------------------
# Building one test


def sources(suite):
    src, arch, refs = SUITES[suite]
    out = []
    for path in sorted(glob.glob(os.path.join(src, "*.S"))):
        name = os.path.basename(path)[:-2]
        out.append((name, path))
    return out


def all_tests(suites):
    out = []
    for s in suites:
        for name, _ in sources(s):
            out.append((s, name))
    return out


def compile_test(suite, name, dest, spike=False, quiet=True):
    """Compile one test; return the ELF path."""
    gcc = find_gcc()
    if not gcc:
        raise RuntimeError("riscv32-none-elf-gcc not found (set WIZ_RV_GCC)")
    src, arch, _ = SUITES[suite]
    srcfile = os.path.join(src, name + ".S")
    if not os.path.exists(srcfile):
        raise RuntimeError(f"{srcfile}: no such test")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if suite == "Zicsr":
        inc = ["-I", os.path.join(ENVDIR, "zicsr")]
    else:
        inc = ["-I", os.path.join(SUITE, "env"), "-I", ENVDIR]
    cmd = [gcc, "-march=" + arch, "-mabi=ilp32", "-mcmodel=medany", "-mno-relax",
           "-nostdlib", "-nostartfiles", "-static", "-DXLEN=32", "-Wl,--no-warn-rwx-segments"]
    if spike:
        cmd += ["-DSPIKE_HALT", "-T", os.path.join(ENVDIR, "link-spike.ld")]
    else:
        cmd += ["-T", os.path.join(ENVDIR, "link-core.ld")]
    cmd += inc + [srcfile, "-o", dest]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("gcc failed:\n" + " ".join(cmd) + "\n" + r.stdout + r.stderr)
    if not quiet and r.stdout + r.stderr:
        print(r.stdout + r.stderr)
    return dest


def symbol_table(elf):
    gcc = find_gcc()
    nm = os.path.join(os.path.dirname(gcc), "riscv32-none-elf-nm") if gcc else "riscv32-none-elf-nm"
    r = subprocess.run([nm, elf], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{nm} {elf}: {r.stderr}")
    out = {}
    for line in r.stdout.splitlines():
        f = line.split()
        if len(f) == 3:
            out[f[2]] = int(f[0], 16)
    return out


def flat_image(elf, dest):
    gcc = find_gcc()
    objcopy = os.path.join(os.path.dirname(gcc), "riscv32-none-elf-objcopy") if gcc else "riscv32-none-elf-objcopy"
    r = subprocess.run([objcopy, "-O", "binary", elf, dest], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{objcopy}: {r.stderr}")
    with open(dest, "rb") as f:
        return f.read()


def log2_ceil(n):
    k = 0
    while (1 << k) < n:
        k += 1
    return k


def write_fixture(suite, name, elf, dest):
    """Turn the core-build ELF into an oracle fixture; return (meta, sig_start, nwords)."""
    sym = symbol_table(elf)
    begin = sym["begin_signature"]
    end = sym["end_signature"]
    if end <= begin:
        raise RuntimeError(f"{name}: empty signature region")
    binpath = os.path.join(BUILDDIR, f"{suite}-{name}.bin")
    image = flat_image(elf, binpath)
    mbits = max(14, log2_ceil(len(image)))
    if end > (1 << mbits):
        raise RuntimeError(f"{name}: signature ends at {end:#x}, past the {1 << mbits}-byte memory")
    # The tests are straight-line generated programs; every executed instruction is in
    # the text, and branch/jump tests loop only over their own bodies.  16x the image
    # in instructions plus a fixed allowance is a generous bound and catches a hang.
    steps = min(400000, 16 * (begin // 4) + 8192)
    arch = SUITES[suite][1]
    words = list(struct.unpack("<%dI" % (len(image) // 4), image[:len(image) // 4 * 4]))
    with open(dest, "w") as f:
        f.write(name + "\n")
        f.write(f"{arch} {mbits} {steps} {begin} {end - begin}\n")
        for w in words:
            f.write("%08x\n" % w)
    return {"name": name, "suite": suite, "elf": elf, "bin": binpath,
            "begin": begin, "end": end, "mbits": mbits, "steps": steps,
            "cfg": arch, "image_len": len(image)}


def run_arch(fixture, arch_run, timeout):
    r = subprocess.run([arch_run, fixture], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"arch_run failed ({r.returncode}): {r.stderr.strip()}")
    line = r.stdout.strip().splitlines()
    if not line or not line[-1].startswith("ARCH "):
        raise RuntimeError("arch_run printed no ARCH line: " + r.stdout[:300])
    f = line[-1].split()
    if len(f) < 5:
        raise RuntimeError("malformed ARCH line: " + line[-1][:200])
    return {
        "name": f[1],
        "steps": int(f[2]),
        "stopped": f[3] == "H",
        "trap": int(f[4]),
        "sig": [int(x, 16) for x in f[5:]],
        "raw": line[-1],
    }


def read_reference(suite, name):
    if suite == "Zicsr":
        path = os.path.join(EXPECTED, name + ".sig")
    else:
        path = os.path.join(SUITES[suite][2], name + ".reference_output")
    if not os.path.exists(path):
        return None, path
    with open(path) as f:
        return [int(x, 16) for x in f if x.strip()], path


def write_expected(name, words):
    os.makedirs(EXPECTED, exist_ok=True)
    path = os.path.join(EXPECTED, name + ".sig")
    with open(path, "w") as f:
        for w in words:
            f.write("%08x\n" % (w & 0xFFFFFFFF))
    return path


def first_diff(got, ref, limit=8):
    if len(got) != len(ref):
        return f"signature length {len(got)} vs {len(ref)}"
    for i, (a, b) in enumerate(zip(got, ref)):
        if a != b:
            out = [f"word {i} (offset {4 * i:#x}): core {a:08x}, ref {b:08x}"]
            for j in range(i + 1, min(i + limit, len(got))):
                if got[j] != ref[j]:
                    out.append(f"  word {j}: core {got[j]:08x}, ref {ref[j]:08x}")
            return "\n      ".join(out)
    return ""


def py_signature(fixture):
    """The signature from the repository's independent reference interpreter."""
    sys.path.insert(0, os.path.join(ROOT, "oracle", "scripts"))
    import rv32_ref  # noqa: E402
    fx = rv32_ref.Fixture(fixture)
    raw = rv32_ref.signature(fx)
    return [int.from_bytes(bytes(raw[i:i + 4]), "little") for i in range(0, len(raw) - 3, 4)]


def spike_signature(elf, timeout, suite):
    spike = find_spike()
    if not spike:
        raise RuntimeError("spike not found (set SPIKE)")
    dtc = find_dtc()
    env = dict(os.environ)
    if dtc:
        env["PATH"] = os.path.dirname(dtc) + os.pathsep + env.get("PATH", "")
    isa = "rv32im_zicsr" if suite == "M" else "rv32i_zicsr"
    with tempfile.TemporaryDirectory(prefix="rv-arch-spike-") as tmp:
        sig = os.path.join(tmp, "sig")
        r = subprocess.run([spike, "--isa=" + isa, "-m0x80000000:0x4000000",
                            "+signature=" + sig, "+signature-granularity=4", elf],
                           capture_output=True, text=True, timeout=timeout, env=env)
        if r.returncode != 0 or not os.path.exists(sig):
            raise RuntimeError(f"spike failed ({r.returncode}): {(r.stdout + r.stderr).strip()[:400]}")
        with open(sig) as f:
            return [int(x, 16) for x in f if x.strip()]


# ---------------------------------------------------------------------------
# Commands


def ensure_arch_run(args):
    path = args.arch_run or os.path.join(ROOT, "oracle", ".build", "arch_run")
    if os.path.exists(path):
        return path
    return None


def cmd_list(args):
    suites = parse_suites(args.suite)
    for s in suites:
        for name, _ in sources(s):
            print(f"{s:5s} {name}")
    return 0


def parse_suites(text):
    if not text or text == "all":
        return ALL
    out = []
    for s in text.split(","):
        s = s.strip()
        if s not in SUITES:
            raise SystemExit(f"unknown suite {s!r} (have: {', '.join(ALL)})")
        out.append(s)
    return out


def select(args):
    suites = parse_suites(args.suite)
    want = None
    if args.tests:
        want = {t.strip() for t in args.tests.split(",") if t.strip()}
    out = []
    for s in suites:
        for name, _ in sources(s):
            if want is None or name in want:
                out.append((s, name))
    if want:
        known = {n for _, n in out}
        unknown = want - known
        if unknown:
            raise SystemExit(f"unknown test(s) for the selected suites: {', '.join(sorted(unknown))}")
    return out


def cmd_run(args):
    rep = Report()
    gcc = find_gcc()
    arch_run = ensure_arch_run(args)
    todo = select(args)
    if not gcc:
        rep.skip("suite", "riscv32-none-elf-gcc not found (set WIZ_RV_GCC); clean skip")
        return rep.print()
    if not arch_run:
        rep.skip("suite", "oracle/.build/arch_run not built; run `python3 oracle/arch-test/arch_test.py build`")
        return rep.print()
    os.makedirs(BUILDDIR, exist_ok=True)
    for suite, name in todo:
        tag = f"{suite}/{name}"
        try:
            elf = os.path.join(BUILDDIR, f"{suite}-{name}.elf")
            compile_test(suite, name, elf)
            fixture = os.path.join(BUILDDIR, f"{suite}-{name}.hex")
            meta = write_fixture(suite, name, elf, fixture)
            got = run_arch(fixture, arch_run, args.timeout)
        except subprocess.TimeoutExpired:
            rep.fail(tag, f"arch_run exceeded {args.timeout}s")
            continue
        except Exception as e:  # toolchain/harness problem for this test
            rep.fail(tag, str(e))
            continue
        if not got["stopped"]:
            rep.fail(tag, f"ran out of the {meta['steps']}-instruction budget "
                          f"(trap {got['trap']}); no signature")
            continue
        if got["trap"] != 2:
            rep.fail(tag, f"stopped on trap cause {got['trap']} instead of EBREAK "
                          f"after {got['steps']} instructions; no signature")
            continue
        ref, refpath = read_reference(suite, name)
        if ref is None:
            rep.skip(tag, f"no reference ({refpath})")
            continue
        if got["sig"] == ref:
            note = f"{got['steps']} insns, {len(ref)} signature words"
            if args.spike and suite != "Zicsr":
                try:
                    sref = spike_signature(elf_spike(suite, name), args.timeout, suite)
                    if sref != ref:
                        rep.fail(tag, "official reference != spike: " + first_diff(sref, ref))
                        continue
                    note += ", official == spike"
                except Exception as e:
                    rep.fail(tag, f"spike check failed: {e}")
                    continue
            rep.ok(tag, note)
        else:
            rep.fail(tag, first_diff(got["sig"], ref))
    return rep.print()


def elf_spike(suite, name):
    path = os.path.join(BUILDDIR, f"{suite}-{name}-spike.elf")
    compile_test(suite, name, path, spike=True)
    return path


def cmd_build(args):
    gcc = find_gcc()
    if not gcc:
        print("SKIP: riscv32-none-elf-gcc not found (set WIZ_RV_GCC)")
        return 0
    os.makedirs(BUILDDIR, exist_ok=True)
    rc = 0
    for s in parse_suites(args.suite):
        for name, src in sources(s):
            elf = os.path.join(BUILDDIR, f"{s}-{name}.elf")
            try:
                compile_test(s, name, elf)
                print(f"ok   {s}/{name}")
            except Exception as e:
                print(f"FAIL {s}/{name}: {e}")
                rc = 1
    return rc


def cmd_fixture(args):
    """Write the fixed subset fixtures and expected signatures for tests/rv/arch-test."""
    gcc = find_gcc()
    arch_run = ensure_arch_run(args)
    if not gcc:
        print("SKIP: riscv32-none-elf-gcc not found")
        return 0
    if not arch_run:
        print("SKIP: oracle/.build/arch_run not built")
        return 0
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(BUILDDIR, exist_ok=True)
    todo = select(args)
    expected = []
    for suite, name in todo:
        elf = os.path.join(BUILDDIR, f"{suite}-{name}.elf")
        compile_test(suite, name, elf)
        dest = os.path.join(args.out, f"{name}.hex")
        meta = write_fixture(suite, name, elf, dest)
        got = run_arch(dest, arch_run, args.timeout)
        if not got["stopped"] or got["trap"] != 2:
            print(f"FAIL {suite}/{name}: stopped={got['stopped']} trap={got['trap']}")
            return 1
        # The expected file is the *reference* signature, never the core's: a core bug
        # must show up as a failure of the fixed group, not be baked into it.
        ref, refpath = read_reference(suite, name)
        if ref is None:
            print(f"SKIP {suite}/{name}: no reference signature ({refpath})")
            continue
        expected.append((name, ref))
        if got["sig"] != ref:
            print(f"FAIL {suite}/{name}: core differs from the reference: "
                  f"{first_diff(got['sig'], ref)}")
            return 1
        print(f"ok   {suite}/{name}: {got['steps']} insns, {len(ref)} signature words")
    # The Wiz test prints one `name word word …` line per fixture; the .expected file is
    # exactly that, so a signature change is a visible diff.
    with open(os.path.join(args.out, "..", "arch-test.expected"), "w") as f:
        for name, words in expected:
            f.write(name + " " + " ".join("%08x" % w for w in words) + "\n")
    return 0


def cmd_crosscheck(args):
    """Check the core, the vendored official reference, and Spike against each other.

    For each I/M test this is the strongest triage: a core/reference mismatch could be a
    core bug *or* a stale suite reference, and Spike says which.  Zicsr has no official
    reference; its expected/ signature is the rv32_ref/Spike one.
    """
    rep = Report()
    if not find_gcc():
        rep.skip("crosscheck", "riscv32-none-elf-gcc not found (set WIZ_RV_GCC)")
        return rep.print()
    if find_spike() is None:
        rep.skip("crosscheck", "spike not found (set SPIKE, or nix build nixpkgs#spike)")
        return rep.print()
    arch_run = ensure_arch_run(args)
    if not arch_run:
        rep.skip("crosscheck", "oracle/.build/arch_run not built")
        return rep.print()
    os.makedirs(BUILDDIR, exist_ok=True)
    for suite, name in select(args):
        tag = f"{suite}/{name}"
        try:
            elf = os.path.join(BUILDDIR, f"{suite}-{name}.elf")
            compile_test(suite, name, elf)
            fixture = os.path.join(BUILDDIR, f"{suite}-{name}.hex")
            write_fixture(suite, name, elf, fixture)
            core = run_arch(fixture, arch_run, args.timeout)
            ref, _ = read_reference(suite, name)
            sp = spike_signature(elf_spike(suite, name), args.timeout, suite)
        except Exception as e:
            rep.fail(tag, str(e))
            continue
        if not core["stopped"] or core["trap"] != 2:
            rep.fail(tag, f"core stopped={core['stopped']} trap={core['trap']}")
            continue
        if ref is None:
            # Zicsr: the expected file is the reference, and cmd_reference checks it
            # against Spike; here compare the core with Spike directly.
            if core["sig"] == sp:
                rep.ok(tag, f"core == spike ({len(sp)} words)")
            else:
                rep.fail(tag, "core != spike: " + first_diff(core["sig"], sp))
            continue
        if core["sig"] != ref:
            rep.fail(tag, ("core != expected: " if suite == "Zicsr" else "core != official reference: ")
                     + first_diff(core["sig"], ref))
        elif sp != ref:
            rep.fail(tag, ("expected != spike: " if suite == "Zicsr" else "official reference != spike: ")
                     + first_diff(sp, ref))
        else:
            label = "core == expected == spike" if suite == "Zicsr" else "core == official reference == spike"
            rep.ok(tag, f"{label} ({len(ref)} words)")
    return rep.print()


def cmd_reference(args):
    """Generate the Zicsr reference signatures with Spike (or check them).

    The 2.0 suite has no Zicsr tests and the 2026 suite ships no static signatures, so
    the reference for the vendored Zicsr subset is Spike running the same source and the
    same minimal environment.  `--update` writes expected/<test>.sig; without it the
    command compares the file and fails on a difference.
    """
    if not find_gcc():
        print("SKIP: riscv32-none-elf-gcc not found (set WIZ_RV_GCC)")
        return 0
    if find_spike() is None and args.backend == "spike":
        print("SKIP: spike not found (set SPIKE, or nix build nixpkgs#spike)")
        return 0
    os.makedirs(BUILDDIR, exist_ok=True)
    rc = 0
    for suite, name in select(args):
        backend = args.backend
        try:
            if backend == "auto":
                backend = "spike" if find_spike() else "py"
            if backend == "spike":
                elf = elf_spike(suite, name)
                sig = spike_signature(elf, args.timeout, suite)
            else:
                elf = os.path.join(BUILDDIR, f"{suite}-{name}.elf")
                compile_test(suite, name, elf)
                fx = os.path.join(BUILDDIR, f"{suite}-{name}.hex")
                write_fixture(suite, name, elf, fx)
                sig = py_signature(fx)
        except Exception as e:
            print(f"FAIL {suite}/{name}: {e}")
            rc = 1
            continue
        path = os.path.join(EXPECTED, name + ".sig")
        if args.update:
            write_expected(name, sig)
            print(f"wrote {path} ({len(sig)} words, {backend})")
        elif os.path.exists(path):
            with open(path) as f:
                old = [int(x, 16) for x in f if x.strip()]
            if old == sig:
                print(f"ok   {suite}/{name}: {len(sig)} words match {backend}")
            else:
                print(f"FAIL {suite}/{name}: {first_diff(sig, old)}")
                rc = 1
        else:
            print(f"SKIP {suite}/{name}: {path} missing (use --update)")
    return rc


def cmd_selftest(args):
    """A reporter check: a perturbed signature must fail, the real one must pass."""
    rep = Report()
    got = [1, 2, 3, 4]
    if first_diff(got, [1, 2, 3, 4]) == "":
        rep.ok("exact", "an equal signature passes")
    else:
        rep.fail("exact", "an equal signature was reported as a difference")
    d = first_diff([1, 2, 9, 4], [1, 2, 3, 4])
    if d:
        rep.ok("perturbed", d.replace("\n", " "))
    else:
        rep.fail("perturbed", "a changed word was not reported")
    d = first_diff([1, 2, 3], [1, 2, 3, 4])
    if "length" in d:
        rep.ok("short", d)
    else:
        rep.fail("short", "a short signature was not reported")
    return rep.print()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--suite", default="all", help="I, M, Zicsr, or all (default: all)")
        p.add_argument("--tests", default=None, help="comma-separated test names")
        p.add_argument("--timeout", type=int, default=180, help="per-test timeout in seconds")
        p.add_argument("--arch-run", default=None, help="arch_run binary (default oracle/.build/arch_run)")
        p.add_argument("--gcc", default=None, help="riscv32 gcc (default: PATH or nix store)")

    p = sub.add_parser("list")
    common(p)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("build")
    common(p)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("run")
    common(p)
    p.add_argument("--spike", action="store_true", help="also compare I/M with Spike")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("fixture")
    common(p)
    p.add_argument("--out", default=os.path.join(ROOT, "tests", "rv", "arch-test"))
    p.set_defaults(func=cmd_fixture)

    p = sub.add_parser("reference")
    common(p)
    p.add_argument("--update", action="store_true", help="write expected/<test>.sig")
    p.add_argument("--backend", default="auto", choices=["auto", "spike", "py"],
                   help="reference backend (default: spike if available, else rv32_ref.py)")
    p.set_defaults(func=cmd_reference)

    p = sub.add_parser("crosscheck")
    common(p)
    p.set_defaults(func=cmd_crosscheck)

    p = sub.add_parser("selftest")
    p.set_defaults(func=cmd_selftest)

    args = ap.parse_args()
    if getattr(args, "gcc", None):
        os.environ["WIZ_RV_GCC"] = args.gcc
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
