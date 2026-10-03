"""Power on -> new game -> Spiral Mountain, save states/sm_bk.st; then GI floor 1 states/gi1_bk.st.

The menu inputs are a fixed sequence (tap, then wait N frames), so the run is the same every
time; `boot_to_sm(emu, jitter)` lets other scripts insert extra frames to test timing.
"""
from emu import Emu
import bt
from t_common import info

# (button, frames to wait after the 3-frame tap); None = only wait
BOOT = [(None, 700), ("START", 200), ("START", 200), ("A", 200), ("A", 200), ("A", 200), ("A", 200),
        ("START", 100), ("START", 100), ("A", 100), ("START", 100), ("A", 100), ("START", 100),
        ("A", 100), ("B", 100), ("START", 100), ("A", 100), ("B", 100)]


def boot_to_sm(emu, jitter=None):
    """Drive the menus from power-on into Spiral Mountain. jitter: list of extra frames per step."""
    for i, (b, wait) in enumerate(BOOT):
        if b:
            emu.pad(b); yield 3; emu.pad()
        yield wait + (jitter[i] if jitter else 0)
        ps = bt.player(emu)
        if emu.r16(bt.MAP) == 0xAF and ps and bt.state(emu, ps)[1] == 1:
            return
    for i in range(3000):  # mash through any remaining text until Banjo is idle in SM
        emu.pad("B" if (i // 20) % 2 else "A") if i % 20 == 0 else emu.pad()
        yield 1
        ps = bt.player(emu)
        if emu.r16(bt.MAP) == 0xAF and ps and bt.state(emu, ps)[1] == 1:
            emu.pad()
            return
    raise RuntimeError("never reached Spiral Mountain idle: " + info(emu))


def warp(emu, m, frames=400):
    emu.w16(bt.MAP_TRIGGER_TARGET, m); emu.w16(bt.MAP_TRIGGER, 0x0101)
    yield frames


def script(emu):
    yield from boot_to_sm(emu)
    yield 60
    print(info(emu, "sm"), flush=True)
    yield from emu.save_state("states/sm_bk.st")
    yield from warp(emu, 0x101)
    print(info(emu, "gi1"), flush=True)
    yield from emu.save_state("states/gi1_bk.st")


if __name__ == "__main__":
    e = Emu(bt.ROM, video="null")
    e.run(script, timeout=900)
