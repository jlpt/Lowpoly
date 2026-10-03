"""Turn run_effect.sh output into plain outcome categories.
usage: summarize_effects.py OUT.txt START_X,START_Y,START_Z"""
import re, sys

start = tuple(int(v) for v in sys.argv[2].split(","))
for line in open(sys.argv[1]):
    m = re.match(r"\s*(\d+) glitches=\s*(\d+)(.*)", line)
    if not m:
        continue
    k, rest = int(m.group(2)), m.group(3)
    where = re.search(r"@\w+ (.*?) \| wrote", rest)
    where = where.group(1) if where else ""
    if "CRASH" in rest or "FROZE" in rest:
        out = "crash"
    else:
        st = re.search(r"state \w+->(\w+)", rest)
        pos = re.search(r"pos \((-?\d+), (-?\d+), (-?\d+)\)->\((-?\d+), (-?\d+), (-?\d+)\)", rest)
        c = tuple(int(v) for v in pos.groups()[:3]) if pos else None   # control end position
        p = tuple(int(v) for v in pos.groups()[3:]) if pos else None
        if st and st.group(1) in ("47", "2F") or (p and p[1] < c[1] - 30):
            out = "falls through the floor"
        elif p and max(abs(a - b) for a, b in zip(p, start)) < 30:
            out = "stuck stick (can't walk afterwards)"
        elif "no difference" in rest:
            out = "no visible difference"
        elif p and max(abs(a - b) for a, b in zip(p, c)) < 30:
            out = "ends within 30 units of the control (nothing visible)"
        else:
            out = "other: " + rest.split("|")[-1].strip()
    print(f"{k:3d} | {where[:60]:60s} | {out}")
