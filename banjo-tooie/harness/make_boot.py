"""Cold boot (fresh emulator = power on) with random human-ish delays on every input, then
GI Floor 1 and split up. Saves states/boot_<seed>.st. Used by t_consist.py as a "reset the
console and do it again" history.  usage: make_boot.py SEED"""
import sys, random
from emu import Emu
import bt
from make_base import boot_to_sm, BOOT, warp
from t_consist import split_on_gi1
from t_common import info

seed = int(sys.argv[1])
rng = random.Random(seed)


def script(emu):
    yield from boot_to_sm(emu, [rng.randint(0, 40) for _ in BOOT])
    yield rng.randint(0, 300)
    yield from warp(emu, 0x101, 400 + rng.randint(0, 200))
    yield from split_on_gi1(emu)
    yield rng.randint(0, 300)
    print(info(emu, f"boot_{seed}"), flush=True)
    yield from emu.save_state(f"states/boot_{seed}.st")


if __name__ == "__main__":
    e = Emu(bt.ROM, video="null")
    e.run(script, timeout=900)
