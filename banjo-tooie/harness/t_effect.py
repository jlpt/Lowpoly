"""Do one PIM write in a room and watch what it changes.

usage: t_effect.py ROOMSTATE OUT.txt MODE IDX [IDX ...]
  ROOMSTATE  savestate with Solo Banjo standing in the room (heap settled)
  MODE       A = glitch then pack straight away (rewrites pos/id only)
             B = glitch, backflip, pack (writes pos, id, 0.12, 0.2, 0.5, 0.75, 1.0)
  IDX        slot index (255 = 1 glitch, 254 = 2, ...) or a range lo-hi
The glitches themselves are skipped: the index byte is set directly and, for mode A, the slot
is loaded into the live zone exactly like the glitch's pop does. Everything after that is the
real game: backflip, Snooze Pack entry (the push), leaving the pack, then 600 frames of
walking/jumping. A control run without the write is compared against each result.
Each line of OUT: idx, address, what is there, then the outcome.
"""
import sys, struct, zlib
from emu import Emu
import bt, heap, dllmap
from t_write import dialog_until_idle

STATE = OUT = None
MODE = "B"
IDX = []
if __name__ == "__main__":
    STATE, OUT, MODE = sys.argv[1], sys.argv[2], sys.argv[3]
    for a in sys.argv[4:]:
        lo, _, hi = a.partition("-")
        IDX += list(range(int(lo), int(hi or lo) + 1))
FRAME_TIMER = 0x8012AAE0  # core2 counter, +1 per game frame (stops if the game thread dies)


def wait_idle(emu, maxf=300):
    for i in range(maxf):
        yield 1
        if i > 10 and bt.state(emu, bt.player(emu))[1] == 1:
            return


def snapshot(emu):
    ps = bt.player(emu)
    flags = emu.read(emu.r32(bt.FLAG_BLOCK_PTR), 0xC0) if ps else b""
    cons = emu.read(emu.r32(0x8012B250), 0x80)
    return dict(map=emu.r16(bt.MAP), ps=ps, state=bt.state(emu, ps)[1] if ps else None,
                pos=tuple(round(v) for v in bt.get_pos(emu)) if ps else None,
                nobj=len(bt.objects(emu)), flags=flags, cons=cons)


def play(emu):
    """Fixed input sequence after the write: idle, walk, jump, walk back."""
    timer = emu.r32(FRAME_TIMER)
    stuck = 0
    for step in [(None, 120), ("UP", 60), ("A", 5), (None, 60), ("DOWN", 60), (None, 120)]:
        b, n = step
        for k in range(n):
            if b == "UP":
                emu.pad(y=60)
            elif b == "DOWN":
                emu.pad(y=-60)
            elif b == "A":
                emu.pad("A")
            else:
                emu.pad()
            yield 1
            t = emu.r32(FRAME_TIMER)
            stuck = stuck + 1 if t == timer else 0
            timer = t
            if stuck > 90:
                return "FROZE (game frame timer stopped)"
    emu.pad()
    return None


def do_write(emu, idx):
    """idx=None: control run, same inputs but the index is left alone (normal push)."""
    ps = bt.player(emu); sk = bt.stick(emu, ps)
    if idx is not None:
        emu.w8(sk + 0x66, idx)
    if MODE == "A" and idx is not None:
        slot = sk + idx * 0x1C
        for k in range(0, 0x1C, 4):  # what the glitch's pop does
            emu.w32(sk + 0x38 + k, emu.r32(slot + k))
    else:
        emu.pad("Z"); yield 6
        emu.pad("Z", "A"); yield 3
        emu.pad(); yield from wait_idle(emu)
        yield 5
    # The PlayerState can move (heap compaction) during the backflip and even during the pack
    # entry, so track the stick every frame and take the slot at the frame the push happens.
    ps = bt.player(emu); sk = bt.stick(emu, ps)
    if idx is None:
        idx = emu.r8(sk + 0x66)
    prev = emu.read(sk + idx * 0x1C, 0x1C)
    slot, what, before, after = sk + idx * 0x1C, "", prev, prev
    emu.pad("Z"); yield 6
    emu.pad("Z", "CR"); yield 1
    for i in range(60):
        emu.pad("Z"); yield 1
        ps = bt.player(emu); sk2 = bt.stick(emu, ps)
        cur = emu.read(sk2 + idx * 0x1C, 0x1C)
        if emu.r8(sk2 + 0x66) != idx:
            slot, before, after = sk2 + idx * 0x1C, prev, cur
            what = describe(emu, slot, heap.blocks(emu, ps), heap.labels(emu))
            if sk2 != sk:
                what += f" [PlayerState moved {sk2 - sk:+X} during entry]"
            break
        sk, prev = sk2, cur
    emu.pad(); yield 5
    yield from dialog_until_idle(emu, 300)
    return slot, what, before, after


def describe(emu, addr, bl, lab):
    for b in bl:
        if b["hdr"] <= addr < b["end"]:
            name = lab.get(b["data"], "")
            off = addr - b["data"]
            if name.startswith("DLL "):
                blk = emu.read(b["data"], 16)
                w = dllmap.where(name[4:], blk, off)
                return f"{name} +{off:X} ({w[1] if w else '?'})"
            if addr < b["data"]:
                return f"heap header of {b['data']:08X} {name}"
            return f"{name or 'block'} {b['data']:08X}[{b['end'] - b['data']:X}]{'' if b['state'] else ' FREE'} +{off:X}"
    return "?"


def script(emu):
    yield from emu.load_state(STATE); yield 5
    yield from do_write(emu, None)
    froze = yield from play(emu)
    assert not froze, "control run froze"
    ctrl = snapshot(emu)
    out = open(OUT, "a")
    for idx in IDX:
        open(OUT + ".cur", "w").write(str(idx))
        yield from emu.load_state(STATE); yield 5
        slot, what, before, after = yield from do_write(emu, idx)
        nchg = sum(1 for a, b in zip(before, after) if a != b)
        froze = yield from play(emu)
        s = snapshot(emu)
        diffs = []
        for k in ("map", "state", "pos", "nobj"):
            if s[k] != ctrl[k]:
                diffs.append(f"{k} {ctrl[k]}->{s[k]}")
        for k in ("flags", "cons"):
            d = [i for i, (a, b) in enumerate(zip(ctrl[k], s[k])) if a != b]
            if d:
                diffs.append(f"{k} bytes {d[:6]}")
        res = froze or ("; ".join(diffs) if diffs else "no difference vs control")
        line = f"{idx:3d} glitches={256 - idx:3d} @{slot:08X} {what} | wrote {nchg}B | {res}"
        print(line, flush=True)
        out.write(line + "\n"); out.flush()
        if froze:
            break  # a frozen game can't be trusted for the next load; driver restarts us


if __name__ == "__main__":
    e = Emu(bt.ROM, video="null")
    e.run(script, timeout=36000, stall=40)
