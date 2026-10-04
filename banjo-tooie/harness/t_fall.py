"""Follow Banjo after a floor-cache write: position/state over time, screenshots.
usage: t_fall.py ROOMSTATE IDX [video] [frames]"""
import sys
from emu import Emu
import bt
import t_effect as T
from t_common import info

STATE, IDX = sys.argv[1], int(sys.argv[2])
VIDEO = sys.argv[3] if len(sys.argv) > 3 else "null"
FRAMES = int(sys.argv[4]) if len(sys.argv) > 4 else 900
T.MODE = "B"


def script(emu):
    yield from emu.load_state(STATE); yield 5
    slot, what, before, after = yield from T.do_write(emu, IDX)
    print(f"write @{slot:08X} {what}", flush=True)
    last = None
    for f in range(FRAMES):
        yield 1
        ps = bt.player(emu)
        if not ps:
            continue
        st = bt.state(emu, ps)[1]
        if st != last or f % 150 == 0:
            print(f"  +{f:4d} {info(emu, '')}", flush=True)
            last = st
        if VIDEO != "null" and f in (10, 60, 200, 600):
            emu.screenshot()


if __name__ == "__main__":
    e = Emu(bt.ROM, video=VIDEO)
    e.run(script, timeout=600)
