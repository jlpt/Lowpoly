"""After one glitch: can Banjo still move? Try stick, jump+stick, and a normal pack."""
from emu import Emu
import bt
from t_common import info
from t_write import glitch  # noqa (reuses dialog handling)

e = Emu(bt.ROM, video="null")

def moved(emu, a):
    b = bt.get_pos(emu)
    return round(((a[0]-b[0])**2 + (a[2]-b[2])**2) ** 0.5)

def script(emu):
    yield from emu.load_state("states/gi1_solo_pad.st"); yield 10
    import sys
    if 'control' not in sys.argv: yield from glitch(emu)
    sk = bt.stick(emu, bt.player(emu))
    print("idx", emu.r8(sk + 0x66), "markers", emu.read(sk + 0x40, 0x14).hex(), flush=True)
    p = bt.get_pos(emu); emu.pad(y=70); yield 60; emu.pad(); yield 10
    print("stick only: moved", moved(emu, p), "state", hex(bt.state(emu, bt.player(emu))[1]), flush=True)
    p = bt.get_pos(emu); emu.pad("A", y=70); yield 4; emu.pad(y=70); yield 60; emu.pad(); yield 30
    print("jump+stick: moved", moved(emu, p), "pos", [round(v) for v in bt.get_pos(emu)], "markers", emu.read(sk + 0x40, 0x14).hex(), flush=True)
    p = bt.get_pos(emu); emu.pad(y=70); yield 60; emu.pad(); yield 10
    print("stick after jump: moved", moved(emu, p), "state", hex(bt.state(emu, bt.player(emu))[1]), flush=True)

e.run(script, timeout=600)
