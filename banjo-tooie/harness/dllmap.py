"""Map an address inside a loaded code overlay (DLL) to overlay function + offset, using the
decomp (BT_DECOMP) symbol file and decompressed ROM. Only needs the RAM bytes of the block."""
import os, re, bisect, subprocess

BASE = os.environ.get("BT_DECOMP", "banjo-tooie")
_SEG = None


def _load():
    global _SEG, _ROM
    if _SEG is not None:
        return
    _SEG = {}
    for line in open(os.path.join(BASE, "ovl_symbol_addrs.us.txt")):
        m = re.match(r"\s*(\w+)\s*=\s*0x([0-9A-Fa-f]+);\s*//\s*segment:(\w+)\s+rom:0x([0-9A-Fa-f]+)", line)
        if m:
            name, va, seg, rom = m.group(1), int(m.group(2), 16), m.group(3), int(m.group(4), 16)
            _SEG.setdefault(seg, []).append((va, name, rom))
    for v in _SEG.values():
        v.sort()
    _ROM = open(os.path.join(BASE, "decompressed.us.z64"), "rb").read()


def locate(name, block_bytes):
    """-> (text offset inside the block, rom offset of vram 0x80800000) or None."""
    _load()
    syms = _SEG.get(name)
    if not syms:
        return None
    va, _, rom = syms[0]
    text_rom = rom - (va - 0x80800000)
    hdr = block_bytes[:8]
    i = _ROM.rfind(hdr, max(0, text_rom - 0x2000), text_rom)
    if i < 0:
        return None
    return text_rom - i, text_rom


def where(name, block_bytes, off):
    """Overlay function containing block offset `off` -> (vram, 'func+0xNN') or None."""
    loc = locate(name, block_bytes)
    if not loc:
        return None
    text_off, _ = loc
    va = 0x80800000 + off - text_off
    syms = [s for s in _SEG[name] if not s[1].startswith("D_")]
    keys = [s[0] for s in syms]
    k = bisect.bisect_right(keys, va) - 1
    if va < 0x80800000 or k < 0:
        return va, "header" if va < 0x80800000 else "?"
    # past the last function -> probably data/rodata
    data = [s for s in _SEG[name] if s[1].startswith("D_") and s[0] <= va]
    if data and data[-1][0] > syms[k][0]:
        return va, f"data {data[-1][1]}+{va - data[-1][0]:X}"
    return va, f"{syms[k][1]}+{va - syms[k][0]:X}"


def disasm(words, vaddr):
    data = b"".join(w.to_bytes(4, "big") for w in words)
    p = "/tmp/dllmap_blob.bin"
    open(p, "wb").write(data)
    out = subprocess.run(["mips-linux-gnu-objdump", "-D", "-b", "binary", "-m", "mips:4300", "-EB",
                          f"--adjust-vma={vaddr:#x}", p], capture_output=True, text=True).stdout
    return [l.split("\t", 2)[-1].strip() for l in out.splitlines() if re.match(r"\s*[0-9a-f]+:\t", l)]
