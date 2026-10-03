"""Real PIM glitches (no index shortcut) at an interaction spot, then an optional backflip and a
Snooze Pack push. Reports where the push actually landed and what changed, so the shortcut
used by t_effect.py can be checked against the real thing.

usage: t_real.py SPOTSTATE MODE K [K ...]
  SPOTSTATE  savestate with Solo Banjo standing where B starts a text box
  MODE       A (pack straight after the glitches) or B (backflip first)
  K          number of glitches
"""
import sys
from emu import Emu
import bt, heap
import t_effect as T
from t_write import glitch
from t_probe import detail, NAMES

STATE, MODE = sys.argv[1], sys.argv[2]
KS = [int(k) for k in sys.argv[3:]]
T.MODE = MODE


def script(emu):
    for k in KS:
        yield from emu.load_state(STATE); yield 10
        tries = 0
        while tries < 2 * k + 3:  # the first Snooze Pack in a room tends to miss (assets loading)
            ps = bt.player(emu); sk = bt.stick(emu, ps)
            if emu.r8(sk + 0x66) == (256 - k) & 0xFF:
                break
            yield from glitch(emu)
            tries += 1
        ps = bt.player(emu); sk = bt.stick(emu, ps)
        idx = emu.r8(sk + 0x66)
        if idx != 256 - k:
            print(f"k={k}: index is {idx}, expected {256 - k} (a glitch failed)", flush=True)
            continue
        # do_write with idx=None keeps the real (glitched) index; MODE B adds the backflip
        slot, what, before, after = yield from T.do_write(emu, None)
        nchg = sum(1 for a, b in zip(before, after) if a != b)
        d0 = detail(emu)
        froze = yield from T.play(emu)
        d1 = detail(emu)
        print(f"k={k:2d} ({tries} tries) idx={idx} push @{slot:08X} {what} | wrote {nchg}B | {froze or 'ok'} | "
              f"state {d0['st'][1]:X}->{d1['st'][1]:X} pos {[round(v) for v in d1['pos']]}", flush=True)


if __name__ == "__main__":
    e = Emu(bt.ROM, video="null")
    e.run(script, timeout=3000, stall=40)
