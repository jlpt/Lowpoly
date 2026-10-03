"""Is the memory after Banjo's PlayerState the same every time you enter a room?

usage: t_consist.py MAP [MAP ...] [HISTORY ...]   (maps in hex; default: every history)
Enters each target map as Solo Banjo after several different histories and prints the
"window" (heap blocks the glitch can reach, index 20..255) for each, then how long it stays
the same while you stay in the room. Histories:
  base      GI F1 split state -> map
  idle      same, after idling 1500 frames first
  via_F2    GI F1 -> GI Floor 2 -> map
  glitched  3 PIM glitches + a pack on GI F1 -> map
  boot_N    states/boot_N.st from make_boot.py (power on, random input timing, GI F1 split) -> map
"""
import sys
from emu import Emu
import bt, heap
from t_write import glitch, dialog_until_idle
from t_common import settle

_args = sys.argv[1:] if __name__ == "__main__" else []
ONLY = [a for a in _args if a.isalpha() or "_" in a]   # history names
MAPS = [int(a, 16) for a in _args if a not in ONLY]


def warp(emu, m, frames=450):
    emu.w16(bt.MAP_TRIGGER_TARGET, m); emu.w16(bt.MAP_TRIGGER, 0x0101)
    for i in range(frames):
        yield 1
        ps = bt.player(emu)
        if i > 100 and ps and emu.r16(bt.MAP) == m and bt.state(emu, ps)[1] == 1:
            break
    yield from settle(emu)


def signature(emu):
    ps = bt.player(emu)
    sk = bt.stick(emu, ps)
    lab = heap.labels(emu)
    sig = []
    for b in heap.blocks(emu, ps):
        if b["end"] <= sk + 20 * 0x1C or b["hdr"] >= sk + 256 * 0x1C:
            continue
        i0 = max(20, (b["hdr"] - sk) // 0x1C)
        i1 = min(255, (b["end"] - 1 - sk) // 0x1C)
        name = lab.get(b["data"], "")
        if name.startswith("obj#"):
            name = name.split(" ", 1)[1]
        sig.append(f"{i0}-{i1}:{b['end'] - b['data']:X}{'' if b['state'] else '(free)'}{(' ' + name) if name else ''}")
    return " | ".join(sig)


def split_on_gi1(emu):
    """make_solo2.py inline: learn moves, stand on the Banjo split pad, split."""
    bt.set_flag(emu, bt.ABILITY_FLAG(0x0E))
    for ab in (bt.SNOOZE, bt.SHACK, bt.SACK, bt.TAXI):
        bt.set_flag(emu, bt.ABILITY_FLAG(ab))
    for i in range(5):
        bt.set_pos(emu, 2100, 1010, -124); yield 1
    for i in range(300):
        yield 1
        if bt.state(emu, bt.player(emu))[1] == 1:
            break
    yield 20
    ps = bt.player(emu)
    for i in range(4):
        emu.w8(emu.r32(ps + 0x58) + 1, 1); yield 1
    emu.w8(emu.r32(ps + 0x58) + 1, 1)
    emu.pad("A"); yield 1
    emu.w8(emu.r32(ps + 0x58) + 1, 1); yield 3; emu.pad()
    for i in range(400):
        yield 2
        st = bt.state(emu, bt.player(emu))[1]
        if bt.transform(emu) == 10 and st == 1 and i > 40:
            break
        if i > 30 and st == 0x73:
            emu.pad("B" if (i // 6) % 2 else "A") if i % 6 == 0 else emu.pad()
    emu.pad()
    yield 30
    assert bt.transform(emu) == 10, "split failed"


def history(emu, h):
    if h == "base":
        yield from emu.load_state("states/gi1_solo_pad.st")
    elif h == "idle":
        yield from emu.load_state("states/gi1_solo_pad.st"); yield 1500
    elif h == "via_F2":
        yield from emu.load_state("states/gi1_solo_pad.st")
        yield from warp(emu, 0x106); yield 300
    elif h == "glitched":
        yield from emu.load_state("states/gi1_solo_pad.st"); yield 10
        for _ in range(3):
            yield from glitch(emu)
        emu.pad("Z"); yield 6; emu.pad("Z", "CU"); yield 40; emu.pad(); yield 5
        yield from dialog_until_idle(emu, 300)
    elif h.startswith("boot_"):  # made by make_boot.py: fresh power-on, random input timing
        yield from emu.load_state(f"states/{h}.st")
    yield 5


HIST = ["base", "idle", "via_F2", "glitched", "boot_1", "boot_2", "boot_3", "boot_4"]


def script(emu):
    for m in MAPS:
        print(f"=== {m:03X} {bt.map_name(m)}", flush=True)
        for h in (ONLY or HIST):
            yield from history(emu, h)
            yield from warp(emu, m)
            sigs = [signature(emu)]
            ps0 = bt.player(emu)
            for wait in (600, 1500):
                yield wait
                sigs.append(signature(emu))
            stable = "stable for 2100 frames after settling" if len(set(sigs)) == 1 else "CHANGES while in room"
            print(f"  {h:9s} ps={ps0:08X} tf={bt.transform(emu)} {stable}\n      {sigs[0]}", flush=True)
            if len(set(sigs)) > 1:
                for s in sigs[1:]:
                    print(f"      later: {s}", flush=True)


if __name__ == "__main__":
    e = Emu(bt.ROM, video="null")
    e.run(script, timeout=7000)
