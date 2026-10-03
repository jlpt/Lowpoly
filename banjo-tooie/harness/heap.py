"""Banjo-Tooie heap walker / block labeller (USA)."""
import bt

KNOWN = {
    0x8012C770: "Flag Block",
    0x8012B250: "Consumables Block",
    0x80136EE0: "Object Model 1 Array",
    0x80132DB0: "Object Model 2 Array",
    0x80136E70: "Object Model 1 Animation State",
    0x801289D0: "Text Buffer",
    0x80127600: "Text Script",
}
LOADED_DLL_ARRAY = 0x80126738


def ok(p):
    return 0x80000000 <= p < 0x80800000


def blocks(emu, start_data_ptr):
    """All heap blocks reachable from the block whose data starts at start_data_ptr."""
    h = start_data_ptr - 0x10
    seen = 0
    while ok(emu.r32(h)) and emu.r32(h) < h and seen < 20000:
        h = emu.r32(h); seen += 1
    out = []
    seen = 0
    while ok(h) and seen < 20000:
        nxt = emu.r32(h + 4)
        w = emu.r32(h + 0xC)
        out.append(dict(hdr=h, data=h + 0x10, end=nxt if ok(nxt) and nxt > h else h + 0x10,
                        tag=emu.r32(h + 8), state=(w >> 6) & 3))
        if not ok(nxt) or nxt <= h:
            break
        h = nxt; seen += 1
    return out


def dll_name(emu, base):
    off = 0x38
    for _ in range(400):
        off += 4
        if not ok(emu.r32(base + off)):
            break
    s = b""
    for i in range(48):
        c = emu.r8(base + off + i)
        if c == 0:
            break
        s += bytes([c])
    return s.decode(errors="replace") if s and all(32 <= ch < 127 for ch in s) else None


def labels(emu):
    lab = {}
    for i in range(8):
        p = emu.r32(bt.PLAYER_PTRS + 4 * i)
        if ok(p):
            lab[p] = f"PlayerState[{i}]"
    for a, n in KNOWN.items():
        p = emu.r32(a)
        if ok(p):
            lab.setdefault(p, n)
    off = 0
    while True:
        p = emu.r32(LOADED_DLL_ARRAY + off)
        if not ok(p):
            break
        nm = dll_name(emu, p)
        lab.setdefault(p, f"DLL {nm}" if nm else "DLL ?")
        off += 4
        if off > 0x1000:
            break
    # objects: label blocks referenced from model-1 slots
    for i, o in enumerate(bt.objects(emu)):
        for k in range(0, 0x9C, 4):
            p = emu.r32(o["slot"] + k)
            if ok(p) and p not in lab:
                lab[p] = f"obj#{i} {o['name']} +{k:02X}"
    return lab


def describe(emu, addr, blist=None, lab=None):
    blist = blist if blist is not None else blocks(emu, bt.player(emu))
    lab = lab if lab is not None else labels(emu)
    for b in blist:
        if b["hdr"] <= addr < b["end"]:
            name = lab.get(b["data"], "?")
            if addr < b["data"]:
                return f"HEAP HEADER of block {b['data']:08X} ({name}) +{addr - b['hdr']:X}"
            st = "free" if b["state"] == 0 else "used"
            return f"block {b['data']:08X} [{st} size {b['end'] - b['data']:X}] {name} +{addr - b['data']:X}"
    return "outside heap walk"


def load_symbols():
    import re
    syms = {}
    import os
    base = os.environ.get("BT_DECOMP", "banjo-tooie") + "/"
    for fn in ("symbol_addrs.us.txt", "syscall_symbol_addrs.us.txt"):
        for line in open(base + fn):
            m = re.match(r"\s*(\w+)\s*=\s*0x([0-9A-Fa-f]+)", line)
            if m:
                syms[int(m.group(2), 16)] = m.group(1)
    for fn in ("src/core2/core2bss1.s", "src/core1/core1bss1_0.s", "src/core1/core1bss1_1.s", "src/core1/core1bss1_2.s"):
        try:
            for line in open(base + fn):
                m = re.match(r"dlabel (D_([0-9A-Fa-f]{8}))", line)
                if m:
                    syms[int(m.group(2), 16)] = m.group(1)
        except FileNotFoundError:
            pass
    return syms


def referrers(ram, target, limit=8):
    """Addresses of 32-bit words in RAM equal to target (ram = bytes of full RDRAM dump)."""
    import array
    a = array.array("I", ram)
    a.byteswap()
    out = []
    t = target
    i = 0
    try:
        while len(out) < limit:
            i = a.index(t, i)
            out.append(0x80000000 + i * 4)
            i += 1
    except ValueError:
        pass
    return out
