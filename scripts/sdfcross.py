# The paths between the half-rate part (cells named core.top_sys*) and the full-rate part
# of doom_top, from nextpnr's SDF: forward from every register on one side, through at
# most DEPTH combinational cells, to a register on the other side. By construction
# (src/Rv/Doom.wiz, `Edge`; `busStep`) these are register, at most a few LUTs, register;
# a deeper search would follow nextpnr's false arcs between the two LUTs of a fractured
# pair (wiz-arty FINDINGS.md). Prints the worst of each direction with its path.
#   python3 -I scripts/sdfcross.py FILE.sdf [DEPTH]
import sys, re, collections
txt = open(sys.argv[1]).read()
DEPTH = int(sys.argv[2]) if len(sys.argv) > 2 else 4
unesc = lambda s: s.replace('\\', '')
def mx(t): return max(int(x) for x in re.findall(r'-?\d+', t))
inter = collections.defaultdict(list); comb = collections.defaultdict(list)
for m in re.finditer(r'\(INTERCONNECT (\S+) (\S+) (\([^)]*\)) (\([^)]*\))\)', txt):
    s, d = unesc(m.group(1)), unesc(m.group(2))
    inter[tuple(s.rsplit('/', 1))].append((tuple(d.rsplit('/', 1)), max(mx(m.group(3)), mx(m.group(4)))))
clk2q = {}; checked = set()
for blk in txt.split('(CELL')[1:]:
    mi = re.search(r'\(INSTANCE ([^)\n]*)\)', blk)
    if not mi: continue
    inst = unesc(mi.group(1).strip())
    for p in re.finditer(r'\(IOPATH (\(posedge (\S+)\)|\S+) (\S+) (\([^)]*\)) (\([^)]*\))\)', blk):
        i, o, d = p.group(1), p.group(3), max(mx(p.group(4)), mx(p.group(5)))
        if 'posedge' in i or 'CLK' in i or i in ('C', 'CK'): clk2q[(inst, o)] = max(clk2q.get((inst, o), 0), d)
        else: comb[(inst, i)].append(((inst, o), d))
    for c in re.finditer(r'\(SETUP(?:HOLD)? \((?:posedge|negedge) (\S+)\)', blk): checked.add((inst, c.group(1)))
    for c in re.finditer(r'\(SETUP(?:HOLD)? (\w[\w\[\]]*) ', blk): checked.add((inst, c.group(1)))
# the half-rate part: the cells whose clock enable (CE, a memory's write or read enable)
# comes from the enable flip-flop, directly or through one LUT
TOG = 'core.top_sys_half_FDRE_Q'
drivers = collections.defaultdict(set)   # (inst, pin) -> driving instances
for a, ds in inter.items():
    for (b, _) in ds: drivers[b].add(a[0])
lutIn = collections.defaultdict(set)     # LUT instance -> instances driving its inputs
for (b_inst, b_pin), srcs in drivers.items(): lutIn[b_inst] |= srcs
ENPINS = re.compile(r'^(CE|WE.*|EN.*|WEA.*|WEBWE.*|ENARDEN|ENBWREN|WEAL.*|WEBWEL.*|WEAU.*|WEBWEU.*)$')
gatedSet = set()
for (inst, pin), srcs in drivers.items():
    if ENPINS.match(pin) and inst != TOG:
        if TOG in srcs or any(TOG in lutIn[d] for d in srcs):
            gatedSet.add(inst)
half = lambda inst: inst in gatedSet
print('half-rate cells (enable from %s): %d' % (TOG, len(gatedSet)))
worst = {}
def walk(src, n, t, depth, path):
    for m, d in inter.get(n, []):
        a = t + d
        if m in checked and half(m[0]) != half(src[0]):
            k = 'half -> full' if half(src[0]) else 'full -> half'
            if a > worst.get(k, (0,))[0]: worst[k] = (a, path + [m])
        if depth < DEPTH:
            for o, cd in comb.get(m, []):
                walk(src, o, a + cd, depth + 1, path + [m, o])
for q, c in clk2q.items():
    walk(q, q, c, 0, [q])
for k, (a, path) in sorted(worst.items()):
    print('%s: %.3f ns (clock-to-out included, setup not), %d cells' % (k, a / 1000, (len(path) - 2) // 2))
    for p in path: print('    %s/%s' % (p[0][:100], p[1]))
