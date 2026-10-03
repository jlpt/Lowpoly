"""What does the pack push write after a glitch, depending on what you do in between?

usage: t_payload.py [pre ...]   pre in: none flip walk jump flip+walk ; append ':x,y' to hold the
stick at (x, y) during the writing pack entry (e.g. flip:0,40).
One glitch (index 255) at the GI Floor 1 warp pad, the pre-action, then a Snooze Pack entry
(the push), then leave. Prints the 28 bytes at the target slot before/after and whether Banjo
can walk afterwards.
"""
import sys, struct
from emu import Emu
import bt
from t_write import glitch, dialog_until_idle

PRE = sys.argv[1:] or ["none", "flip", "walk", "jump"]


def wait_idle(emu, maxf=300):
    for i in range(maxf):
        yield 1
        if i > 10 and bt.state(emu, bt.player(emu))[1] == 1:
            return


def pre_action(emu, what):
    for w in what.split("+"):
        if w == "flip":
            emu.pad("Z"); yield 6
            emu.pad("Z", "A"); yield 3
            emu.pad(); yield from wait_idle(emu)
        elif w == "walk":
            emu.pad(y=70); yield 40
            emu.pad(); yield 30
        elif w == "jump":
            emu.pad("A"); yield 3
            emu.pad(); yield from wait_idle(emu)
        elif w == "none":
            pass
        yield 10


def zone(b):
    pos, zid = struct.unpack(">fi", b[:8])
    return f"pos={pos:.4g} id={zid} markers={[round(v, 4) for v in struct.unpack('>5f', b[8:])]}"


def moved(emu):
    a = bt.get_pos(emu)
    emu.pad(y=70); yield 40
    emu.pad(); yield 20
    b = bt.get_pos(emu)
    return round(((a[0] - b[0]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5)


def script(emu):
    for spec in PRE:
        what, _, stick = spec.partition(":")
        sx, sy = (int(v) for v in stick.split(",")) if stick else (0, 0)
        yield from emu.load_state("states/gi1_solo_pad.st")
        yield 10
        yield from glitch(emu)
        ps = bt.player(emu); sk = bt.stick(emu, ps)
        idx = emu.r8(sk + 0x66)
        yield from pre_action(emu, what)
        ps = bt.player(emu); sk = bt.stick(emu, ps)
        tgt = sk + idx * 0x1C
        live = emu.read(sk + 0x38, 0x1C)
        before = emu.read(tgt, 0x1C)
        emu.pad("Z"); yield 6
        emu.pad("Z", "CR", x=sx, y=sy); yield 1
        for i in range(60):
            emu.pad("Z", x=sx, y=sy); yield 1
            if emu.r8(sk + 0x66) != idx:
                break
        after = emu.read(tgt, 0x1C)
        emu.pad(); yield 5
        yield from dialog_until_idle(emu, 300)
        changed = sum(1 for a, b in zip(before, after) if a != b)
        m = yield from moved(emu)
        print(f"[{spec}] idx={idx} target={tgt:08X}\n   live zone before push: {live.hex()}  ({zone(live)})"
              f"\n   slot before: {before.hex()}\n   slot after:  {after.hex()}  ({changed} bytes changed)"
              f"\n   after leaving the pack: index {emu.r8(sk + 0x66)}, stick walk moved {m} units", flush=True)


if __name__ == "__main__":
    e = Emu(bt.ROM, video="null")
    e.run(script, timeout=1200)
