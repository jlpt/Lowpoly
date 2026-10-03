from emu import Emu
import bt
from t_common import info
e = Emu(bt.ROM, video="null")
def script(emu):
    yield from emu.load_state("states/gi1_bk.st")
    bt.set_flag(emu, bt.ABILITY_FLAG(0x0E))
    for ab in (bt.SNOOZE, bt.SHACK, bt.SACK, bt.TAXI): bt.set_flag(emu, bt.ABILITY_FLAG(ab))
    for i in range(5):
        bt.set_pos(emu, 2100, 1010, -124); yield 1
    for i in range(300):
        yield 1
        if bt.state(emu, bt.player(emu))[1] == 1: break
    yield 20
    ps = bt.player(emu)
    print(info(emu, "onpad"), "duo+1", emu.r8(emu.r32(ps+0x58)+1), flush=True)
    for i in range(4):
        emu.w8(emu.r32(ps+0x58)+1, 1); yield 1
    emu.w8(emu.r32(ps+0x58)+1, 1)
    emu.pad("A"); yield 1
    emu.w8(emu.r32(ps+0x58)+1, 1); yield 3; emu.pad()
    for i in range(400):
        yield 2
        if i % 20 == 0: print(info(emu, "split"), "tf", bt.transform(emu), flush=True)
        st = bt.state(emu, bt.player(emu))[1]
        if bt.transform(emu) == 10 and st == 1 and i > 40:
            break
        if i > 30 and st == 0x73:
            emu.pad("B" if (i//6) % 2 else "A") if i % 6 == 0 else emu.pad()
    yield 30
    print(info(emu, "done"), "tf", bt.transform(emu), "pidx", emu.r8(bt.PLAYER_IDX), flush=True)
    yield from emu.save_state("states/gi1_solo.st")
e.run(script, timeout=300)
