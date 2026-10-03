"""Detailed look at one PIM write: objects, item counts, flags and screenshots, vs a control.
usage: t_probe.py ROOMSTATE MODE IDX [video]"""
import sys, os
from emu import Emu
import bt
import t_effect as T

STATE, MODE, IDX = sys.argv[1], sys.argv[2], int(sys.argv[3])
VIDEO = sys.argv[4] if len(sys.argv) > 4 else "null"
T.MODE = MODE
CONS_BASE = 0x8011B080
NAMES = ["Blue Eggs", "Fire Eggs", "Ice Eggs", "Grenade Eggs", "CWK Eggs", "Prox Eggs", "Red Feathers",
         "Gold Feathers", "Glowbos", "Empty Honeycombs", "Cheato Pages", "Burgers", "Fries", "Tickets",
         "Doubloons", "Gold Idols", "Beans", "Fish", "SnS Eggs", "Ice Keys", "Mega Glowbos", "c21", "c22", "c23"]


def detail(emu):
    blk = emu.r32(bt.FLAG_BLOCK_PTR)
    return dict(objs=[(o["name"], tuple(round(v) for v in o["pos"])) for o in bt.objects(emu)],
                cons=[emu.r16(CONS_BASE + i * 0xC) for i in range(24)],
                flags=emu.read(blk, 0xC0), st=bt.state(emu, bt.player(emu)), pos=bt.get_pos(emu))


def run(emu, idx, tag):
    yield from emu.load_state(STATE); yield 5
    slot, what, before, after = yield from T.do_write(emu, idx)
    print(f"[{tag}] slot {slot:08X} {what}\n   before {before.hex()}\n   after  {after.hex()}", flush=True)
    d0 = detail(emu)
    if VIDEO != "null":
        emu.screenshot(); yield 5
    froze = yield from T.play(emu)
    if VIDEO != "null":
        emu.screenshot(); yield 5
    return froze, d0, detail(emu)


def script(emu):
    f0, c_mid, c_end = yield from run(emu, None, "control")
    f1, x_mid, x_end = yield from run(emu, IDX, f"idx {IDX}")
    print("froze:", f1)
    for tag, a, b in (("right after leaving the pack", c_mid, x_mid), ("after the walk/jump", c_end, x_end)):
        print(f"--- {tag}: state {a['st']} -> {b['st']}, pos {[round(v) for v in a['pos']]} -> {[round(v) for v in b['pos']]}")
        for i, (u, v) in enumerate(zip(a["cons"], b["cons"])):
            if u != v:
                print(f"   item {NAMES[i]}: {u} -> {v}")
        for i, (u, v) in enumerate(zip(a["flags"], b["flags"])):
            if u != v:
                for bit in range(8):
                    if (u ^ v) >> bit & 1:
                        print(f"   flag {40 + i * 8 + bit:#x} {(u >> bit) & 1} -> {(v >> bit) & 1}")
        ao, bo = a["objs"], b["objs"]
        gone = [o for o in ao if o not in bo]; new = [o for o in bo if o not in ao]
        if gone: print("   objects gone:", gone)
        if new: print("   objects new:", new)


if __name__ == "__main__":
    e = Emu(bt.ROM, video=VIDEO)
    e.run(script, timeout=300)
