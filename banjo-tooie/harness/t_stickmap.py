"""Measure raw analog stick (x, y) -> BaStick value/distance, to know which `pos` floats a push
can write. Prints per-axis curves and checks the 2D rule on a sample grid. Writes
data/stickmap.json: {"x": {raw: value}, "y": {...}, "grid": [[x, y, distance], ...]}."""
import json, struct
from emu import Emu
import bt


def script(emu):
    yield from emu.load_state("states/gi1_solo_pad.st"); yield 10
    ps = bt.player(emu); sk = bt.stick(emu, ps)
    out = {"x": {}, "y": {}, "grid": []}

    def read(x, y):
        emu.pad(x=x, y=y)
        yield 3
        return emu.rf(sk + 0x54), emu.rf(sk + 0x58), emu.rf(sk + 0x60)

    for r in range(-128, 128):
        vx, vy, d = yield from read(r, 0)
        out["x"][r] = vx
        vx, vy, d = yield from read(0, r)
        out["y"][r] = vy
    for x in range(0, 128, 5):
        for y in range(0, 128, 5):
            vx, vy, d = yield from read(x, y)
            out["grid"].append([x, y, vx, vy, d])
    emu.pad()
    json.dump(out, open("data/stickmap.json", "w"))
    nz = [r for r in range(0, 128) if out["x"][r] != 0]
    print("x: first nonzero raw", nz[0] if nz else None, "value", out["x"][nz[0]] if nz else None,
          "| raw 80 ->", out["x"][80], "| raw 127 ->", out["x"][127], "| raw -128 ->", out["x"][-128], flush=True)
    print("y: raw 80 ->", out["y"][80], "| raw -80 ->", out["y"][-80], flush=True)
    bad = 0
    for x, y, vx, vy, d in out["grid"]:
        if abs(min(1.0, (out["x"][x] ** 2 + out["y"][y] ** 2) ** 0.5) - d) > 1e-5:
            bad += 1
    print("2D rule distance=min(1, hypot(fx(x), fy(y))) mismatches:", bad, "of", len(out["grid"]), flush=True)


if __name__ == "__main__":
    e = Emu(bt.ROM, video="null")
    e.run(script, timeout=600)
