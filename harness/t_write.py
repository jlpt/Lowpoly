"""Glitch N times, then do one normal Snooze Pack; diff RAM to locate the out-of-bounds zone write."""
import sys, struct
from emu import Emu
import bt, heap
from t_common import info

_args = [a for a in sys.argv[1:] if a.lstrip('-').isdigit()] if __name__ == '__main__' else []
N = int(_args[0]) if len(_args) > 0 else 1
STICK_X = int(_args[1]) if len(_args) > 1 else 0
WALK = int(_args[2]) if len(_args) > 2 else 0  # frames of walking between glitch and push


def dialog_until_idle(emu, maxf=600):
    for i in range(maxf):
        yield 1
        st = bt.state(emu, bt.player(emu))[1]
        if st == 0x73 and i % 10 == 0:
            emu.pad("A")
        elif i % 10 == 3:
            emu.pad()
        if i > 60 and st == 1:
            break
    emu.pad()
    yield 10


def glitch(emu, off=6):
    emu.pad("Z"); yield 6
    emu.pad("Z", "CR"); yield 1
    for i in range(off):
        emu.pad("Z"); yield 1
    emu.pad("Z", "B"); yield 2
    emu.pad()
    yield from dialog_until_idle(emu)


def script(emu):
    yield from emu.load_state("states/gi1_solo_pad.st")
    yield 10
    for n in range(N):
        yield from glitch(emu)
        ps = bt.player(emu)
        print(f"after glitch {n+1}: idx={emu.r8(bt.stick(emu, ps) + 0x66)}", flush=True)
    ps = bt.player(emu); sk = bt.stick(emu, ps)
    idx = emu.r8(sk + 0x66)
    tgt = sk + idx * 0x1C
    bl = heap.blocks(emu, ps); lab = heap.labels(emu)
    print(f"ps={ps:08X} stick={sk:08X} idx={idx} target={tgt:08X}: {heap.describe(emu, tgt, bl, lab)}", flush=True)
    if WALK:
        emu.pad(y=60); yield WALK
        emu.pad(); yield 30
        ps = bt.player(emu); sk = bt.stick(emu, ps)
        print("after walk, live zone markers:", emu.read(sk + 0x40, 0x14).hex(), flush=True)
    before = emu.dump()
    # normal snooze pack, with optional stick deflection held during entry
    emu.pad("Z"); yield 6
    emu.pad("Z", "CR", x=STICK_X); yield 1
    for i in range(40):
        emu.pad("Z", x=STICK_X); yield 1
        if emu.r8(bt.stick(emu, bt.player(emu)) + 0x66) != idx:
            break
    mid = emu.dump()
    ps2 = bt.player(emu); sk2 = bt.stick(emu, ps2)
    print(f"push happened: idx now {emu.r8(sk2 + 0x66)} (stick {sk2:08X}, moved={sk2 != sk})", flush=True)
    tgt2 = sk2 + idx * 0x1C
    print("written bytes @%08X:" % tgt2, mid[(tgt2 & 0x7FFFFF):(tgt2 & 0x7FFFFF) + 0x1C].hex(),
          "was", before[(tgt2 & 0x7FFFFF):(tgt2 & 0x7FFFFF) + 0x1C].hex(), flush=True)
    vals = struct.unpack(">fi5f", mid[(tgt2 & 0x7FFFFF):(tgt2 & 0x7FFFFF) + 0x1C])
    print("as zone: position=%.4f id=%d markers=%s" % (vals[0], vals[1], [round(v, 3) for v in vals[2:]]), flush=True)
    print("target block:", heap.describe(emu, tgt2), flush=True)
    emu.pad(); yield 5
    yield from dialog_until_idle(emu, 300)
    print(info(emu, "end"), flush=True)
    yield from emu.save_state(f"states/after_write_{N}_{WALK}.st")


if __name__ == "__main__":
    e = Emu(bt.ROM, video="null")
    e.run(script, timeout=1200)
