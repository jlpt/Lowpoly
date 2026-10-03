# PIM Pack (Pack Index Manipulation) — Banjo-Tooie research

Root cause, exact trigger conditions, what the corrupted index actually reads and writes,
and tooling to watch it live in BizHawk. Everything below was read out of the game's code
(Banjo-Tooie decomp + disassembly) and then reproduced in an automated emulator harness.

## TL;DR

* The "pointer" that underflows is a **u8 stack index** in Solo Banjo's analog-stick
  component: `BaStick.unk66` at `stick + 0x66`, where `stick = *(PlayerState + 0x128)`.
  The stack it indexes (`stored_zones`) only has **2** entries of 0x1C bytes.
* Pack moves push the current stick "zone" when you enter the pack and pop it when you
  leave. **Snooze Pack and Shack Pack only push part-way into their entry animation**, but
  their talk states still pop on the way out. Interacting (warp pad, sign, NPC) before the
  push happens gives a pop with no push: `0 -> 255`. Each repeat: `255 -> 254 -> ...`.
* After that, every pack entry **writes 28 bytes to `stick + index * 0x1C`** and every pack
  exit **reads 28 bytes back from there into Banjo's stick zone**.
* Verified in emulator: Snooze and Shack underflow, **Sack Pack does not** (its entry
  handler does the missing push itself), Taxi Pack cannot trigger it.

## Root cause

All three Solo-Banjo packs share one pair of helpers per pack:

| | Snooze (`bsbansnooze`) | Shack (`bsbanshack`) | Sack (`bsbansack`) |
|---|---|---|---|
| setup (push) | `func_80800098` | `func_8080021C` | `func_808002D4` |
| teardown (pop) | `func_80800000` | `func_80800164` | `func_80800238` |
| state group | `0x14` | `0x13` | `0x12` |

* **setup** = `bastick_pushZone` + set pack zone thresholds, skipped if the *previous*
  state was already in the pack's group.
* **teardown** = `bastick_popZone`, skipped if the *next* state is in the pack's group.

```c
void bastick_popZone(PlayerState *self) {      // core2, 0x8009EF60
    self->stick->unk66--;                        // u8: 0 -> 255
    copy(&self->stick->zone, &self->stick->stored_zones[self->stick->unk66]);
}
void bastick_pushZone(PlayerState *self) {     // core2, 0x8009EFA8
    copy(&self->stick->stored_zones[self->stick->unk66], &self->stick->zone);
    self->stick->unk66++;
}
```

The index is loaded with `lbu` (unsigned), so 255 means `stick + 255*0x1C = stick + 0x1BE4`,
far past the end of the struct.

The entry states don't call setup in their init. They call it from the update function at
a fixed point in the animation and set `PlayerState + 0x15D` (Sack uses `+0x15E`):

| Entry state | push happens at | measured window (game frames after the C-button) |
|---|---|---|
| `0x171` Entering Snooze Pack | 37.0 % of anim `0x276` | B on frames 1–16 works, 20+ is too late |
| `0x16A` Entering Shack Pack | 19.8 % of anim `0x145` | B on frames 1–6 works, 10+ is too late |
| `0x163` Entering Sack Pack | 51.5 % of anim `0x143` | never underflows (see below) |

If something interrupts the entry state before that point, its end handler runs:

* **Snooze / Shack** end handler: `if (+0x15D) teardown(); else backpack_state = 1;`. No
  push. The talk state it goes to (`0x61` / `0x5F`) is in the same group, so its init
  skips the push too. Every state after it (`0x16F` Snoozing / `0x16C` Shack idle) also
  sees a same-group previous state and skips. When you finally leave the pack, the leave
  state's end handler pops: **unbalanced pop, index 0 -> 255**.
* **Sack** end handler: `if (!+0x15E) setup(); teardown();`. It performs the missing push
  before deciding whether to pop, so the stack stays balanced. Tested: index stays 0 at
  every timing.
* **Taxi Pack** (`bstaxi`) pushes in its init, so it can't be interrupted before the push.

Observed state path (emulator, GI Floor 1 warp pad, B pressed 6 frames into Snooze):

```
0x171 Entering Snooze -> 0x61 Snooze talk -> 0x16F Snoozing -> 0x172 Leaving -> 0x01 Idle
index:      0                0                    0                0            255
```

## How to do it

1. Be **Solo Banjo** with **Snooze Pack** (Z + C-Right) or **Shack Pack** (Z + C-Down) learned.
2. Stand where B starts an interaction. A warp pad is easiest. With no other pad unlocked it
   gives the "find another…" text, which still counts. Signs and NPCs should work the same
   way, as long as the interaction puts Banjo into the pack's talk state.
3. Hold Z, press C-Right, then press **B within the window** (Snooze ≈ first 16 game frames,
   Shack ≈ first 6). The animation is cancelled into the talk.
4. Close the text. Banjo drops into the pack (Snoozing / Shack idle). **Leave the pack**:
   that exit pops, and the index is now 255.
5. Repeat steps 3–4 to go to 254, 253, … (verified 255 → 254 → 253 in a row).

What resets it: the index is only zeroed when a PlayerState is created (`bastick_reset`
is only called from the PlayerState constructor), i.e. on map load. Splitting up did
**not** recreate Banjo's PlayerState in testing. So the glitch lives for one map visit.

## What a corrupted index actually does

Every Snooze / Shack / Sack / Taxi entry calls `pushZone`; every exit calls `popZone`.
With index `i` (≥ 2) and slot address `S = stick + i * 0x1C`:

* **pack entry (push):** copies the live zone (`stick + 0x38`, 0x1C bytes) **to `S`**, then `i++`.
* **pack exit (pop):** `i--`, then copies **from `S`** into the live zone.
* **each glitch:** is a pop. It moves the index down one and loads the 28 bytes at the
  new `S` into Banjo's live zone.

The zone is:

```
+0x00 f32 position   (0..1, how far the stick is through the current band)
+0x04 s32 id         (0..4, which stick-magnitude band)
+0x08 f32 markers[5] (band thresholds; default 0.12, 0.2, 0.5, 0.75, 1.0)
```

`id`/`position` are recomputed **every frame** from the analog stick against the current
markers (`bastick_updateZone`). The markers are only changed by states that set them.

That gives two practical write modes:

1. **Glitch, then pack straight away.** The glitch pop loaded `S`'s own bytes into the zone,
   so the push writes the 5 marker words back unchanged. Only **bytes 0–7** at `S` change:
   `position` and `id` from your stick (neutral stick → `00000000 00000000`). Measured in
   emulator: exactly 8 bytes changed.
2. **Glitch, walk, then pack.** The walk states' init calls `bastick_resetZones`, so the
   zone becomes `[pos, id, 0.12, 0.2, 0.5, 0.75, 1.0]` and the push writes all 28 bytes:
   `PPPPPPPP IIIIIIII 3DF5C28F 3E4CCCCD 3F000000 3F400000 3F800000`.
   **Catch:** you have to be *able* to walk (see the side effect below). In my test
   setup you couldn't, so this mode stayed code-only.

**Side effect of every glitch:** the 28 bytes it loads become Banjo's stick thresholds.
`bastick_updateZone` only changes the band when the stick falls inside one of the
thresholds, so garbage thresholds can freeze the band. Measured (GI Floor 1, 1 glitch):
the loaded thresholds were tiny denormals, and **Banjo could not walk from idle with the
stick** (moved 0 units vs 684 without the glitch). Jumping still worked. Inside a pack,
movement is normal (pack setup writes its own thresholds), but leaving pops the garbage
back. What you get depends entirely on what the slot contains.

Leaving the pack pops the slot back into the zone, so the write at `S` **stays** in memory.
The game only sees it if something else uses that memory before it's overwritten.

## Where it writes

`S = stick + i * 0x1C`. The PlayerState is one heap block, `0x19C` bytes of component
pointers followed by every component in a fixed order. The stick is component 74 at
`PlayerState + 0xDD0` and the block is `0x1000` bytes. So:

**Map-independent part (i = 2…19): Banjo's own components.** These offsets don't depend on
the map, so they're the most consistent targets, but they need 237–254 glitches.

| i | slot covers | what's there |
|---|---|---|
| 2 | `stick+0x38` | the live zone itself (no-op) |
| 3 | `stick+0x54` | stick values, angle, distance **and the index byte itself** (`+0x66` = marker[2] byte 2). With default markers this sets the byte at `+0x64` to `0x3F`, which disables stick input, and the index becomes 1 again. |
| 4–7 | `ps+0xE40…0xEAF` | `sub` component (+0x04 … +0x58; slot 7 spills into `swim`) |
| 8 | `ps+0xEB0` | component 78 (size from `func_800A06E0`), spills into `timer` |
| 9–13 | `ps+0xECC…0xF57` | `timer` component, last slot spills into `translate` |
| 14 | `ps+0xF58` | `translate` +0x18 |
| 15 | `ps+0xF74` | `van` +0x14 / `wandglow` |
| 16–17 | `ps+0xF90…0xFC7` | `washer` (slot 17 spills into component 84) |
| 18 | `ps+0xFC8` | component 84 |
| 19 | `ps+0xFE4` | `wobble`, ends exactly at the end of the block |

**Map-dependent part (i = 20…255).** Past `ps+0x1000` you're in whatever heap blocks follow
the PlayerState. BT's heap is compacted (defragmented) during play: the PlayerState's
address changed several times in testing, so absolute addresses aren't stable, and what
follows it can change as blocks are allocated and freed. Example, GI Floor 1, Solo Banjo
after the split, one glitch:

| i | heap block after PlayerState |
|---|---|
| 20–25 | 0x90-byte block (referenced from `0x80132E84`) |
| 25–34 | 0xF0-byte block |
| 34–45 | 0x120-byte block owned by Banjo (pointer at PlayerState+0x3D0) |
| 45–77 | a loaded code overlay (`idworld`) |
| 80–255 | one 0x3360-byte loaded asset (from the asset cache at `0x8012B450`) |

So on that floor, **every practical glitch count (1–176) hits the same asset block**
(slot `i` is `stick + i*0x1C`; i = 255 is `stick + 0x1BE4`). Which effects are reachable is decided by
what the map has loaded right after Banjo. Run the Lua watcher in the room you care
about to see it live. Landing in other objects' data or code mostly corrupts them,
or crashes.

## Practical notes

* Consistency: for a given map, entry route and actions, the heap is deterministic. If an
  effect works once from a savestate it should be repeatable from the same setup. Different
  routes into the room, or spawned particles/enemies, can shift everything after the
  PlayerState.
* Rough cost per step: one pack start, B, close text, leave pack. Low indices (own
  components) are a long grind; high indices (1–20 glitches) are cheap and map-dependent.
* Any pack that pushes can be the "writer" once the index is corrupted: Snooze, Shack, Sack
  and Taxi Pack. Only Snooze and Shack can *create* the underflow.
* A pack exit right after a push restores the zone, so moving in and out of a pack is safe.
  Each **glitch** is what changes the zone.

## Caveats

* Testing used the decomp-matching build of **USA 1.0** (code and overlays byte-identical
  to retail, assets regenerated). Code paths, timings and struct offsets are retail-exact.
  Exact heap addresses depend on asset sizes, which should match but need checking on a
  retail ROM: that's what the Lua watcher is for.
* Frame windows are in **game frames** (one per rendered frame), not BizHawk VI frames.
  BT usually renders at 20–30 fps, so expect roughly 2–3 VIs per game frame.
* PAL/JP addresses in the Lua script come from ScriptHawk and are untested.

## Tools in this repo

* `lua/pim_pack_watch.lua`: BizHawk overlay. Shows the state, the zone index, whether the
  entry window is open, the next push target (which component or heap block), the bytes
  there and the bytes that will be written. Logs every index change. `PIM.setIndex(n)`
  from the Lua console jumps to an index for practice.
* `harness/`: the headless mupen64plus driver used for the tests (frame-stepped Python
  scripts with RAM access and pad input). Needs `libmupen64plus2`, `mupen64plus-rsp-hle`,
  your own ROM (`BT_ROM=...`), a ScriptHawk checkout (`SCRIPTHAWK_BT_LUA=.../games/bt.lua`)
  and optionally the decomp (`BT_DECOMP=...`) for symbol names. Build the two plugins with
  `gcc -shared -fPIC -O2 -fvisibility=hidden -o input_ctl.so input_ctl.c` (same for
  `video_null.c`).
  * `make_base.py` boots a new file and saves Spiral Mountain and GI Floor 1 states.
  * `make_solo2.py` splits up on the GI Floor 1 split pads.
  * `t_pad.py` puts Solo Banjo on the warp pad.
  * `t_glitch.py Z+CR 2 6 10 …` sweeps the B timing.
  * `t_write.py N` does N glitches plus a push and diffs RAM.
  * `t_heapmap.py <state>` prints the index → heap block map.

## Key addresses (USA)

| what | address / offset |
|---|---|
| player pointers / index | `0x80135490[ *(u8*)0x801354DF ]` |
| PlayerState → state `{prev,cur,next}` | `+0x120` |
| PlayerState → stick | `+0x128` (component 74) |
| PlayerState → transformation | `*(+0xA0) + 0x29` (10 = Solo Banjo) |
| Snooze/Shack entry "pushed" flag | `PlayerState + 0x15D` |
| stick zone (pushed data) / stack index | `stick + 0x38` (0x1C bytes) / `stick + 0x66` (u8) |
| `bastick_popZone` / `bastick_pushZone` | `0x8009EF60` / `0x8009EFA8` |
| state → group table | `0x80117F30` (12-byte entries, group at +2) |
| ability flags | flag `0xED + ability` (Snooze 0x23, Shack 0x21, Sack 0x2A, Taxi 0x27, Split Up 0x0E) |
