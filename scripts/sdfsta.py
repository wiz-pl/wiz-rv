# A static timing check of a half-rate design from nextpnr's SDF (README.md, "Doom",
# and FINDINGS.md, H5): every register whose cell name contains GATED (the default:
# "top_sys", the machine under Circuit.half) is clocked under the half-rate enable.
# Paths from a gated register to a gated register have two periods; every other path
# (from or to an ungated register: the enable flip-flop, the bus adapter, the cache,
# the DDR controller and PHY) has one. Prints the worst path of each kind.
#   python3 -I scripts/sdfsta.py FILE.sdf [GATED]
import sys, re, collections, threading
txt = open(sys.argv[1]).read()
GATED = sys.argv[2] if len(sys.argv) > 2 else 'top_sys'
# the clock-to-out of the ungated registers that feed the half-rate part (the bus
# adapter's, the enable's): `ungated->gated` counts paths from these only
FEED = [a for a in sys.argv[3:] if not a.startswith('-')]
unesc = lambda s: s.replace('\\', '')
def mx(t): return max(int(x) for x in re.findall(r'-?\d+', t))
succ = collections.defaultdict(list)    # (inst, pin) -> [((inst, pin), delay)]
pred = collections.defaultdict(list)
def edge(a, b, d): succ[a].append((b, d)); pred[b].append((a, d))
for m in re.finditer(r'\(INTERCONNECT (\S+) (\S+) (\([^)]*\)) (\([^)]*\))\)', txt):
    s, d = unesc(m.group(1)), unesc(m.group(2))
    si, sp = s.rsplit('/', 1); di, dp = d.rsplit('/', 1)
    edge((si, sp), (di, dp), max(mx(m.group(3)), mx(m.group(4))))
ctype = {}
checked = set()                          # endpoints: pins with a setup check
clk2q = {}                               # sequential outputs: (inst, pin) -> clock-to-out
for blk in txt.split('(CELL')[1:]:
    mi = re.search(r'\(INSTANCE ([^)\n]*)\)', blk)
    mt = re.search(r'\(CELLTYPE "?([^")\n]*)"?\)', blk)
    if not mi: continue
    inst = unesc(mi.group(1).strip()); ctype[inst] = mt.group(1) if mt else '?'
    for c in re.finditer(r'\(SETUP(?:HOLD)? \((?:posedge|negedge) (\S+)\)', blk):
        checked.add((inst, c.group(1)))
    for c in re.finditer(r'\(SETUP(?:HOLD)? (\w[\w\[\]]*) ', blk):
        checked.add((inst, c.group(1)))
    for p in re.finditer(r'\(IOPATH (\(posedge (\S+)\)|\S+) (\S+) (\([^)]*\)) (\([^)]*\))\)', blk):
        i, o = p.group(1), p.group(3)
        d = max(mx(p.group(4)), mx(p.group(5)))
        if 'posedge' in i or i in ('CK', 'CLK', 'C', 'CLKARDCLK', 'CLKBWRCLK', 'WCLK') or 'CLK' in i:
            clk2q[(inst, o)] = max(clk2q.get((inst, o), 0), d)
        else:
            edge((inst, i), (inst, o), d)
            # (nextpnr gives a CARRY4 no arcs from DI: treat DIk as Sk)
            if ctype[inst] == 'CARRY4' and i.startswith('S'):
                edge((inst, 'DI' + i[1:]), (inst, o), d)
gated = lambda inst: inst.startswith('core.' + GATED) or inst.startswith(GATED)
SEQ = ('FD', 'RAMB', 'RAM32', 'RAM64', 'RAM128', 'RAM256', 'SRL', 'DSP48', 'OSERDES', 'ISERDES', 'IDELAYE', 'IOBUF', 'OBUF')
# arrival times from the two kinds of source, by longest path over the predecessors
# (edges that close a cycle are skipped: nextpnr's SDF has false loops between the two
# LUTs of a fractured pair)
sys.setrecursionlimit(10000000)
memo = {}; onstack = set(); via = {}
def arr(n):
    if n in memo: return memo[n]
    onstack.add(n)
    au, ag = -1, -1; bu = bg = None
    if n in clk2q:
        if gated(n[0]): ag = max(ag, clk2q[n])
        elif not FEED or any(n[0].startswith(f) for f in FEED): au = max(au, clk2q[n])
    for p, d in pred.get(n, []):
        if p in onstack: continue
        pu, pg = arr(p)
        if pu >= 0 and pu + d > au: au = pu + d; bu = p
        if pg >= 0 and pg + d > ag: ag = pg + d; bg = p
    onstack.discard(n); memo[n] = (au, ag); via[n] = (bu, bg); return memo[n]
def show(e, k):
    n = e; out = []
    while n is not None:
        out.append('    %7.3f %s/%s' % (memo[n][k] / 1000, n[0][:100], n[1])); n = via.get(n, (None, None))[k]
    print('\n'.join(reversed(out[-60:])))
def main():
    ends = [n for n in checked if n in pred]
    worst = {'ungated->gated (10 ns)': (0, None), 'gated->ungated (10 ns)': (0, None), 'gated->gated (20 ns)': (0, None)}
    for e in ends:
        au, ag = arr(e)
        if gated(e[0]) and au > worst['ungated->gated (10 ns)'][0]: worst['ungated->gated (10 ns)'] = (au, e)
        if gated(e[0]):
            if ag > worst['gated->gated (20 ns)'][0]: worst['gated->gated (20 ns)'] = (ag, e)
        else:
            if ag > worst['gated->ungated (10 ns)'][0]: worst['gated->ungated (10 ns)'] = (ag, e)
    print('endpoints: %d (gated %d); sequential outputs: %d' % (len(ends), sum(1 for e in ends if gated(e[0])), len(clk2q)))
    for k, (t, e) in worst.items():
        print('%-26s %7.3f ns  at %s/%s (%s)' % (k, t / 1000, e[0][:90] if e else '-', e[1] if e else '', ctype.get(e[0]) if e else ''))
        if e and '-v' in sys.argv: show(e, 0 if k.startswith('ungated') else 1)
threading.stack_size(512 * 1024 * 1024)
t = threading.Thread(target=main); t.start(); t.join()
