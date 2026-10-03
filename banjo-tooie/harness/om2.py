"""Object model 2 array (props + loading zones). Layout from ScriptHawk (credit Wedarobi)."""
import bt

OM2_ARRAY_PTR = 0x80132DB0


def ok(p):
    return 0x80000000 <= p < 0x80800000


def array(emu):
    """(base, elem_size, count) of the object model 2 array, or None."""
    base = emu.r32(OM2_ARRAY_PTR)
    if not ok(base):
        return None
    return base, emu.r16(base), emu.r16(base + 2) - 1


def is_lz(bits):
    return (bits & 0x1F) == 0b01010  # bits 1 and 3 set, 0/2/4 clear


def loading_zones(emu):
    a = array(emu)
    if not a:
        return []
    base, size, n = a
    out = []
    for i in range(n):
        p = base + size + i * size
        bits = emu.r16(p + 0xA)
        if is_lz(bits):
            out.append(dict(i=i, addr=p, map=emu.r16(p + 0xC) + 0xA0, exit=emu.r16(p + 0x12),
                            pos=tuple(((emu.r16(p + k) ^ 0x8000) - 0x8000) for k in (4, 6, 8)), bits=bits))
    return out
