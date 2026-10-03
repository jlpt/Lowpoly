"""Warp Solo Banjo into each map and record what the glitch can reach.

usage: t_scan.py out.json [state] map map ...   (maps in hex; 'all' = every named map)
For each map: PlayerState/stick address, every heap block overlapping stick+0x38 .. stick+0x1C00
(index 2..255) with its label, loading-zone array offset, and split pads present.
"""
import sys, json
from emu import Emu
import bt, heap, om2
from t_common import settle

out = sys.argv[1]
state = sys.argv[2] if sys.argv[2].endswith(".st") else "states/gi1_solo_pad.st"
args = [a for a in sys.argv[2:] if not a.endswith(".st")]
if args == ["all"]:
    maps = [i + 1 for i, n in enumerate(bt.MAP_NAMES) if i + 1 >= 0xA1 and not n.startswith("!") and n != "?"]
else:
    maps = [int(x, 16) for x in args]


def window(emu):
    ps = bt.player(emu)
    sk = bt.stick(emu, ps)
    bl = heap.blocks(emu, ps)
    lab = heap.labels(emu)
    lo, hi = sk + 2 * 0x1C, sk + 256 * 0x1C
    rows = []
    for b in bl:
        if b["end"] <= lo or b["hdr"] >= hi:
            continue
        i0 = max(2, (b["hdr"] - sk) // 0x1C)
        i1 = min(255, (b["end"] - 1 - sk) // 0x1C)
        rows.append(dict(data=b["data"], size=b["end"] - b["data"], used=b["state"] != 0,
                         label=lab.get(b["data"], ""), idx=[i0, i1]))
    return ps, sk, rows


def script(emu):
    res = []
    for m in maps:
        yield from emu.load_state(state); yield 5
        emu.w16(bt.MAP_TRIGGER_TARGET, m); emu.w16(bt.MAP_TRIGGER, 0x0101)
        ok = False
        for i in range(450):
            yield 1
            ps = bt.player(emu)
            if i > 100 and ps and emu.r16(bt.MAP) == m and bt.state(emu, ps)[1] in (1, 0x16F, 0x2F, 0x4):
                ok = True
                break
        waited = (yield from settle(emu)) if bt.player(emu) else 0
        ps = bt.player(emu)
        if not ps or emu.r16(bt.MAP) != m:
            print(f"{m:03X} {bt.map_name(m)}: no player / not loaded (map={emu.r16(bt.MAP):03X})", flush=True)
            res.append(dict(map=m, name=bt.map_name(m), ok=False))
            continue
        ps, sk, rows = window(emu)
        a = om2.array(emu)
        lzs = om2.loading_zones(emu)
        names = sorted(set(o["name"] for o in bt.objects(emu)))
        splits = [n for n in names if "Split" in n]
        r = dict(map=m, name=bt.map_name(m), ok=ok, tf=bt.transform(emu), ps=ps, stick=sk, settle=waited, objects=names,
                 om2_off=(a[0] - sk) if a else None, n_lz=len(lzs), splits=splits, window=rows)
        res.append(r)
        desc = " | ".join(f"{w['idx'][0]}-{w['idx'][1]}:{w['size']:X}{'' if w['used'] else '(free)'} {w['label']}" for w in rows if w['idx'][1] >= 20)
        print(f"{m:03X} {bt.map_name(m)[:30]:30s} tf={r['tf']} settle={waited} ps={ps:08X} om2={r['om2_off']:+X} lz={len(lzs)} split={len(splits)} :: {desc}", flush=True)
        json.dump(res, open(out, "w"), indent=1)


e = Emu(bt.ROM, video="null")
e.run(script, timeout=7200)
