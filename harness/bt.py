"""Banjo-Tooie (USA) addresses and helpers for the harness."""
import os
import re

ROM = os.environ.get("BT_ROM", "baserom.us.z64")
_src = open(os.environ.get('SCRIPTHAWK_BT_LUA', 'ScriptHawk/games/bt.lua')).read()
_i = _src.find('maps = {')
MAP_NAMES = re.findall(r'"([^"]*)"', _src[_i:_src.find('\n\t},', _i)])
def map_name(m):
    return MAP_NAMES[m - 1] if 0 < m <= len(MAP_NAMES) else '?'

MAP = 0x80132DC2
MAP_TRIGGER_TARGET = 0x80127640
MAP_TRIGGER = 0x80127642
MAP_DESTINATION = 0x80045702
CHARACTER_STATE = 0x80136F63
CHARACTER_CHANGE = 0x8012704C
PLAYER_PTRS = 0x80135490
PLAYER_IDX = 0x801354DF
FLAG_BLOCK_PTR = 0x8012C770

def player(emu):
    p = emu.r32(PLAYER_PTRS + 4 * emu.r8(PLAYER_IDX))
    return p if 0x80000000 <= p < 0x80800000 else 0

def set_flag(emu, flag, on=True):
    blk = emu.r32(FLAG_BLOCK_PTR)
    i = flag - 40
    a = blk + (i >> 3)
    v = emu.r8(a)
    emu.w8(a, (v | (1 << (i & 7))) if on else (v & ~(1 << (i & 7))))

def get_flag(emu, flag):
    blk = emu.r32(FLAG_BLOCK_PTR)
    i = flag - 40
    return (emu.r8(blk + (i >> 3)) >> (i & 7)) & 1

ABILITY_FLAG = lambda ab: 0xED + ab
SNOOZE, SHACK, SACK, TAXI = 0x23, 0x21, 0x2A, 0x27

# PlayerState (Banjo) layout: 0x56 component pointers at +0, component i at +4*i
PS_STATE = 0x120   # {previous, current, next}
PS_STICK = 0x128
def state(emu, ps):
    s = emu.r32(ps + PS_STATE)
    return emu.r32(s), emu.r32(s + 4), emu.r32(s + 8)
def stick(emu, ps):
    return emu.r32(ps + PS_STICK)

_mi = _src.find('models = {', _src.find('local object_model1 = {'))
MODEL_NAMES = {int(k, 16): v for k, v in re.findall(r'\[0x([0-9A-Fa-f]+)\]\s*=\s*"([^"]*)"', _src[_mi:_src.find('\n\t}', _mi)])}
OBJ_ARRAY_PTR = 0x80136EE0

def objects(emu):
    arr = emu.r32(OBJ_ARRAY_PTR)
    if not (0x80000000 <= arr < 0x80800000):
        return []
    first, last = emu.r32(arr + 4), emu.r32(arr + 8)
    if not (0x80000000 <= first <= last < 0x80800000):
        return []
    out = []
    for i in range((last - first) // 0x9C + 1):
        s = arr + 0x10 + i * 0x9C
        idp = emu.r32(s)
        mid = emu.r16(idp + 0x14) if 0x80000000 <= idp < 0x80800000 else -1
        out.append(dict(slot=s, model=mid, name=MODEL_NAMES.get(mid, hex(mid)),
                        pos=(emu.rf(s + 4), emu.rf(s + 8), emu.rf(s + 0xC))))
    return out

def set_pos(emu, x, y, z):
    ps = player(emu)
    pp = emu.r32(ps + 0xE4)
    for k in (0, 12, 24):
        emu.wf(pp + k, x); emu.wf(pp + k + 4, y); emu.wf(pp + k + 8, z)
    vp = emu.r32(ps + 0xC8)
    for k in (0x10, 0x14, 0x18):
        emu.wf(vp + k, 0.0)

def get_pos(emu):
    ps = player(emu)
    pp = emu.r32(ps + 0xE4)
    return (emu.rf(pp), emu.rf(pp + 4), emu.rf(pp + 8))

def transform(emu):
    ps = player(emu)
    return emu.r8(emu.r32(ps + 0xA0) + 0x29) if ps else -1
