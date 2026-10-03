"""Boot -> new game -> Spiral Mountain, save states/sm_bk.st; then GI floor 1 states/gi1_bk.st."""
from emu import Emu
import bt
from t_common import info
e = Emu(bt.ROM, video="null")
def tap(emu, b, hold=3, after=20):
    emu.pad(b); yield hold; emu.pad(); yield after
def script(emu):
    yield 700
    i = 0
    while True:
        yield from tap(emu, ["START", "A", "B"][i % 3], after=30); i += 1
        ps = bt.player(emu)
        if emu.r16(bt.MAP) == 0xAF and ps and bt.state(emu, ps)[1] == 1:
            break
        if i % 20 == 0: print(info(emu, "nav"), flush=True)
    yield 60
    print(info(emu, "sm"), flush=True)
    yield from emu.save_state("states/sm_bk.st")
    emu.w16(bt.MAP_TRIGGER_TARGET, 0x101); emu.w16(bt.MAP_TRIGGER, 0x0101)
    for i in range(400):
        yield 1
    print(info(emu, "gi1"), flush=True)
    yield from emu.save_state("states/gi1_bk.st")
e.run(script, timeout=900)
