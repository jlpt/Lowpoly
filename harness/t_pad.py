"""Put Solo Banjo on the GI floor 1 warp pad, get through activation, save states/gi1_solo_pad.st."""
from emu import Emu
import bt
from t_common import info

PAD = (3664, 550, 3072)
e = Emu(bt.ROM, video="null")

def script(emu):
    yield from emu.load_state("states/gi1_solo.st")
    for i in range(5):
        bt.set_pos(emu, PAD[0], PAD[1] + 10, PAD[2]); yield 1
    last = None
    for i in range(900):
        yield 1
        ps = bt.player(emu)
        st = bt.state(emu, ps)[1]
        if st != last:
            print(info(emu, "pad"), flush=True); last = st
        # advance any dialog
        if st == 0x73 and i % 12 == 0:
            emu.pad("A")
        elif i % 12 == 2:
            emu.pad()
        if i > 300 and st == 1:
            break
    emu.pad(); yield 30
    print(info(emu, "final"), flush=True)
    for o in bt.objects(emu):
        if o['name'] == 'Warp Pad':
            print("warp pad slot", hex(o['slot']), o['pos'], emu.read(o['slot'], 0x9C).hex())
    yield from emu.save_state("states/gi1_solo_pad.st")

e.run(script, timeout=300)
