"""Headless mupen64plus driver for Banjo-Tooie (USA) experiments.

A script is a generator function `script(emu)` that runs inside the core's frame
callback: each `yield n` waits n frames (VI interrupts). Between yields it can read /
write RDRAM, set the pad, take screenshots and save/load states.
"""
import ctypes as C
import os
import struct
import sys
import threading
import time
import zlib

LIBDIR = "/usr/lib/x86_64-linux-gnu/mupen64plus"
CORE = "/usr/lib/x86_64-linux-gnu/libmupen64plus.so.2"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

DBG = C.CFUNCTYPE(None, C.c_void_p, C.c_int, C.c_char_p)
STATE = C.CFUNCTYPE(None, C.c_void_p, C.c_int, C.c_int)
FRAME = C.CFUNCTYPE(None, C.c_uint)

# libultra button bits (BUTTONS.Value low half, as the input plugin receives it)
BTN = {
    "R_DPAD": 0x0001, "L_DPAD": 0x0002, "D_DPAD": 0x0004, "U_DPAD": 0x0008,
    "START": 0x0010, "Z": 0x0020, "B": 0x0040, "A": 0x0080,
    "R_CBUTTON": 0x0100, "L_CBUTTON": 0x0200, "D_CBUTTON": 0x0400, "U_CBUTTON": 0x0800,
    "R": 0x1000, "L": 0x2000,
}
ALIAS = {"CR": "R_CBUTTON", "CL": "L_CBUTTON", "CD": "D_CBUTTON", "CU": "U_CBUTTON",
         "DU": "U_DPAD", "DD": "D_DPAD", "DL": "L_DPAD", "DR": "R_DPAD"}


def _ensure_rom_db(data):
    """Private copy of the mupen64plus data dir; register this ROM's MD5 as US Banjo-Tooie
    (EEPROM 16K) so modified/rebuilt ROMs get the right save type."""
    import hashlib, shutil
    if not os.path.isdir(DATA):
        shutil.copytree("/usr/share/games/mupen64plus", DATA)
    ini = os.path.join(DATA, "mupen64plus.ini")
    md5 = hashlib.md5(data).hexdigest().upper()
    txt = open(ini, encoding="latin1").read()
    if f"[{md5}]" not in txt and md5 != "40E98FAA24AC3EBE1D25CB5E5DDF49E4":
        with open(ini, "a", encoding="latin1") as fh:
            fh.write(f"\n[{md5}]\nGoodName=Banjo-Tooie (U) local build\nRefMD5=40E98FAA24AC3EBE1D25CB5E5DDF49E4\n")


class Emu:
    def __init__(self, rom, video="glide64mk2", log=False, cpu=2):
        self.log = log
        self.core = C.CDLL(CORE, mode=C.RTLD_GLOBAL)
        self._dbg = DBG(self._on_debug)
        self.events = []
        self._st = STATE(lambda c, p, v: self.events.append((p, v)))
        cfg = os.path.join(HERE, "cfg")
        os.makedirs(cfg, exist_ok=True)
        rc = self.core.CoreStartup(0x020001, cfg.encode(), DATA.encode(), None, self._dbg, None, self._st)
        assert rc == 0, f"CoreStartup {rc}"
        self._set_core_cfg(cpu)
        names = []
        if video == "null":
            names.append((2, os.path.join(HERE, "video_null.so")))
        elif video:
            names.append((2, os.path.join(LIBDIR, f"mupen64plus-video-{video}.so")))
        names += [(4, os.path.join(HERE, "input_ctl.so")), (1, os.path.join(LIBDIR, "mupen64plus-rsp-hle.so"))]
        self.plugins = []
        for t, path in names:
            h = C.CDLL(path)
            h.PluginStartup(C.c_void_p(self.core._handle), None, self._dbg)
            self.plugins.append((t, h))
            if t == 4:
                self.inp = h
        data = open(rom, "rb").read()
        _ensure_rom_db(data)
        self._rombuf = C.create_string_buffer(data, len(data))
        assert self.core.CoreDoCommand(1, len(data), self._rombuf) == 0, "rom open"
        for t, h in self.plugins:
            assert self.core.CoreAttachPlugin(t, C.c_void_p(h._handle)) == 0, f"attach {t}"
        self.buttons = C.c_uint32.in_dll(self.inp, "ctl_buttons")
        self.core.DebugMemGetPointer.restype = C.c_void_p
        self.frame = 0
        self._fcb = FRAME(self._on_frame)
        self.core.CoreDoCommand(15, 0, self._fcb)
        self._gen = None
        self.done = threading.Event()
        self.error = None
        self._wait = 0
        self._limiter_off = False
        self.rdram = None

    def _set_core_cfg(self, cpu=2):
        core = self.core
        h = C.c_void_p()
        core.ConfigOpenSection.argtypes = [C.c_char_p, C.POINTER(C.c_void_p)]
        core.ConfigSetParameter.argtypes = [C.c_void_p, C.c_char_p, C.c_int, C.c_void_p]
        core.ConfigOpenSection(b"Core", C.byref(h))
        v = C.c_int(0)
        core.ConfigSetParameter(h, b"R4300Emulator", 1, C.byref(C.c_int(cpu)))  # 0 interp, 1 cached, 2 dynarec
        core.ConfigSetParameter(h, b"OnScreenDisplay", 2, C.byref(v))
        shots = os.environ.get("SHOTS", os.path.join(HERE, "shots")).encode()
        os.makedirs(shots, exist_ok=True)
        core.ConfigSetParameter(h, b"ScreenshotPath", 4, C.c_char_p(shots))
        core.ConfigOpenSection(b"Video-General", C.byref(h))
        core.ConfigSetParameter(h, b"Fullscreen", 2, C.byref(v))
        core.ConfigSetParameter(h, b"ScreenWidth", 1, C.byref(C.c_int(320)))
        core.ConfigSetParameter(h, b"ScreenHeight", 1, C.byref(C.c_int(240)))

    def _on_debug(self, ctx, lvl, msg):
        if self.log or lvl <= 1:
            sys.stderr.write(f"[m64p {lvl}] {msg.decode(errors='replace')}\n")

    # ---------- memory (N64 virtual 0x80xxxxxx or physical) ----------
    def _ram(self):
        if self.rdram is None:
            p = self.core.DebugMemGetPointer(1)
            self.rdram = (C.c_uint32 * (0x800000 // 4)).from_address(p)
        return self.rdram

    @staticmethod
    def _phys(a):
        return a & 0x1FFFFFFF

    def r32(self, a):
        return self._ram()[self._phys(a) >> 2]

    def w32(self, a, v):
        self._ram()[self._phys(a) >> 2] = v & 0xFFFFFFFF

    def r8(self, a):
        a = self._phys(a)
        return (self._ram()[a >> 2] >> (8 * (3 - (a & 3)))) & 0xFF

    def w8(self, a, v):
        a = self._phys(a)
        sh = 8 * (3 - (a & 3))
        w = self._ram()[a >> 2]
        self._ram()[a >> 2] = (w & ~(0xFF << sh) & 0xFFFFFFFF) | ((v & 0xFF) << sh)

    def r16(self, a):
        return (self.r8(a) << 8) | self.r8(a + 1)

    def w16(self, a, v):
        self.w8(a, v >> 8)
        self.w8(a + 1, v)

    def rf(self, a):
        return struct.unpack(">f", struct.pack(">I", self.r32(a)))[0]

    def wf(self, a, f):
        self.w32(a, struct.unpack(">I", struct.pack(">f", f))[0])

    def read(self, a, n):
        return bytes(self.r8(a + i) for i in range(n))

    def dump(self):
        r = self._ram()
        return struct.pack(">%dI" % len(r), *r)

    # ---------- pad ----------
    def pad(self, *buttons, x=0, y=0):
        v = 0
        for b in buttons:
            v |= BTN[ALIAS.get(b, b)]
        self.buttons.value = v | ((x & 0xFF) << 16) | ((y & 0xFF) << 24)

    # ---------- states / screenshots ----------
    def save_state(self, path):
        """Generator: `yield from emu.save_state(p)` - waits until the core reports completion."""
        n = len(self.events)
        self.core.CoreDoCommand(11, 1, C.c_char_p(os.path.abspath(path).encode()))
        for _ in range(600):
            yield 1
            if any(p == 11 for p, v in self.events[n:]):
                break
        else:
            raise RuntimeError("savestate did not complete")
        time.sleep(0.5)

    def load_state(self, path):
        """Generator: `yield from emu.load_state(p)`."""
        assert os.path.getsize(path) > 0
        n = len(self.events)
        self.core.CoreDoCommand(10, 0, C.c_char_p(os.path.abspath(path).encode()))
        for _ in range(600):
            yield 1
            if any(p == 10 for p, v in self.events[n:]):
                if not [v for p, v in self.events[n:] if p == 10][-1]:
                    raise RuntimeError("load failed: " + path)
                return
        raise RuntimeError("loadstate did not complete")


    def screenshot(self):
        self.core.CoreDoCommand(16, 0, None)

    # ---------- run ----------
    def _on_frame(self, n):
        self.frame += 1
        if not self._limiter_off:
            self._limiter_off = True
            self.core.CoreDoCommand(17, 5, C.byref(C.c_int(0)))  # M64CORE_SPEED_LIMITER off
        if self._wait > 0:
            self._wait -= 1
            return
        try:
            w = next(self._gen)
            self._wait = max(0, int(w or 1) - 1)
        except StopIteration:
            self.done.set()
            self.core.CoreDoCommand(6, 0, None)
        except Exception as e:  # surface script errors
            import traceback
            traceback.print_exc()
            self.error = e
            self.done.set()
            self.core.CoreDoCommand(6, 0, None)

    def run(self, script, timeout=3600, stall=30):
        self._gen = script(self)
        th = threading.Thread(target=lambda: self.core.CoreDoCommand(5, 0, None), daemon=True)
        th.start()
        t_end, last, last_t = time.time() + timeout, -1, time.time()
        while not self.done.wait(2) and time.time() < t_end:
            if self.frame != last:
                last, last_t = self.frame, time.time()
            elif time.time() - last_t > stall:  # core stopped delivering frames: give up
                sys.stderr.write(f"emu: no frame for {stall}s at frame {self.frame}, aborting\n")
                sys.stderr.flush()
                os._exit(3)
        th.join(10)
        time.sleep(1.5)  # let background savestate compression finish
        if self.error:
            raise self.error


def png(path, w, h, rgb):
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                          + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Cheat(C.Structure):
    _fields_ = [("address", C.c_uint32), ("value", C.c_int)]


def add_cheat(emu, name, writes, enabled=True):
    """writes: list of (addr, u16) -> GameShark 81 codes (code-safe: invalidates dynarec blocks)."""
    arr = (Cheat * len(writes))(*[Cheat(0x81000000 | (a & 0x00FFFFFF), v & 0xFFFF) for a, v in writes])
    emu.core.CoreAddCheat.argtypes = [C.c_char_p, C.c_void_p, C.c_int]
    rc = emu.core.CoreAddCheat(name.encode(), C.cast(arr, C.c_void_p), len(writes))
    emu.core.CoreCheatEnabled(name.encode(), 1 if enabled else 0)
    return rc


def cheat_words(addr, words):
    out = []
    for i, w in enumerate(words):
        out += [(addr + 4 * i, w >> 16), (addr + 4 * i + 2, w & 0xFFFF)]
    return out
