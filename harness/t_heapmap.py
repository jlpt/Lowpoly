"""Print the heap neighbourhood of Banjo's PlayerState and what each zone index would hit."""
import sys, bisect
from emu import Emu
import bt, heap
state = sys.argv[1]
e = Emu(bt.ROM, video="null")
def script(emu):
    yield from emu.load_state(state)
    yield 5
    ps = bt.player(emu); sk = bt.stick(emu, ps)
    bl = heap.blocks(emu, ps); lab = heap.labels(emu)
    ram = emu.dump(); syms = heap.load_symbols(); skeys = sorted(syms)
    def symname(a):
        i = bisect.bisect_right(skeys, a) - 1
        return f"{syms[skeys[i]]}+{a - skeys[i]:X}" if i >= 0 and a - skeys[i] < 0x400 else f"{a:08X}"
    def who(b):
        if b['data'] in lab: return lab[b['data']]
        refs = heap.referrers(ram, b['data'], 4)
        names = []
        for r in refs:
            owner = next((x for x in bl if x['data'] <= r < x['end']), None)
            if owner:
                names.append(f"<{lab.get(owner['data'], '%08X' % owner['data'])}+{r - owner['data']:X}>")
            else:
                names.append(symname(r))
        return "refs " + ", ".join(names) if names else "no refs"
    pi = next(i for i, b in enumerate(bl) if b['data'] == ps)
    print(f"map={emu.r16(bt.MAP):03X} ps={ps:08X} stick={sk:08X} (ps+{sk-ps:X}) idx={emu.r8(sk+0x66)} heap blocks={len(bl)}")
    lo, hi = sk + 2 * 0x1C, sk + 255 * 0x1C + 0x1C
    for b in bl[max(0, pi - 2):]:
        if b['hdr'] > hi: break
        st = "free" if b['state'] == 0 else "used"
        idxs = [i for i in range(2, 256) if b['hdr'] <= sk + i * 0x1C < b['end'] or b['hdr'] < sk + i * 0x1C + 0x1C <= b['end']]
        rng = f"idx {min(idxs)}..{max(idxs)}" if idxs else ""
        print(f"  {b['data']:08X} size {b['end']-b['data']:5X} {st} {rng:14s} {who(b)}")
    yield 1
e.run(script, timeout=300)
