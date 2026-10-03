"""Snooze Pack + warp pad B-press at a given frame offset; report state path and zone index."""
import sys
from emu import Emu
import bt
from t_common import info

COMBO = sys.argv[1].split("+")
offsets = [int(x) for x in sys.argv[2:]] or [2, 5, 8, 11, 14]
e = Emu(bt.ROM, video="null")

def attempt(emu, off, combo=None):
    combo = combo or COMBO
    yield from emu.load_state("states/gi1_solo_pad.st")
    yield 10
    emu.pad("Z"); yield 6
    emu.pad(*combo); yield 1
    ps = bt.player(emu); sk = bt.stick(emu, ps)
    path = []
    for i in range(off):
        emu.pad("Z"); yield 1
        path.append(bt.state(emu, ps)[1])
    pre_idx = emu.r8(sk + 0x66); pre_flag = emu.r8(ps + 0x15D)
    emu.pad("Z", "B"); yield 2
    emu.pad()
    last = None
    for i in range(500):
        yield 1
        st = bt.state(emu, bt.player(emu))[1]
        if st != last:
            path.append(st); last = st
            path.append('i%d' % emu.r8(bt.stick(emu, bt.player(emu)) + 0x66))
        if st == 0x73 and i % 10 == 0:
            emu.pad("A")
        elif i % 10 == 3:
            emu.pad()
        if i > 200 and st == 1:
            break
    emu.pad(); yield 20
    ps = bt.player(emu); sk = bt.stick(emu, ps)
    print(f"{'+'.join(COMBO)} off={off:2d} pre_idx={pre_idx} pre15D={pre_flag} path={' '.join(('%X' % s) if isinstance(s, int) else s for s in path[off:])} idx={emu.r8(sk + 0x66)}", flush=True)

def script(emu):
    for off in offsets:
        yield from attempt(emu, off)

e.run(script, timeout=900)
