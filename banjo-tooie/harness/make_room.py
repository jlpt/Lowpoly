"""Warp Solo Banjo (from a GI F1 split state) into MAP, let the heap settle, save states/room_MAP.st."""
import sys
sys.path.insert(0, '.')
from emu import Emu
import bt
from t_consist import warp
m = int(sys.argv[1], 16); src = sys.argv[2] if len(sys.argv) > 2 else "states/gi1_solo_pad.st"
e = Emu(bt.ROM, video="null")
def script(emu):
    yield from emu.load_state(src); yield 5
    yield from warp(emu, m)
    yield 600
    print(f"room {m:03X} ps={bt.player(emu):08X}", flush=True)
    yield from emu.save_state(f"states/room_{m:03X}.st")
e.run(script, timeout=300)
