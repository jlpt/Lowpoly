import bt
def info(emu, tag=""):
    ps=bt.player(emu)
    if not ps: return f"{tag} f={emu.frame} map={emu.r16(bt.MAP):04X} no player"
    st=bt.state(emu, ps); sk=bt.stick(emu, ps); pp=emu.r32(ps+0xE4)
    return (f"{tag} f={emu.frame} map={emu.r16(bt.MAP):04X} char={emu.r8(bt.CHARACTER_STATE)} ps={ps:08X} "
            f"st=({st[0]:X},{st[1]:X},{st[2]:X}) stick={sk:08X} idx={emu.r8(sk+0x66)} "
            f"pos=({emu.rf(pp):.0f},{emu.rf(pp+4):.0f},{emu.rf(pp+8):.0f})")


def settle(emu, maxf=1800, quiet=300, step=30):
    """Wait until Banjo's PlayerState stops moving (the heap is defragmented for a while after
    a map load). Returns frames waited."""
    ps, same, n = bt.player(emu), 0, 0
    while n < maxf:
        yield step
        n += step
        p = bt.player(emu)
        if p == ps:
            same += step
            if same >= quiet:
                break
        else:
            ps, same = p, 0
    return n
