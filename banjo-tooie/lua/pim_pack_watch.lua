-- PIM Pack watcher for Banjo-Tooie (BizHawk, N64 core)
--
-- Shows the solo-Banjo stick-zone stack index that the PIM Pack glitch underflows,
-- whether the "entering pack" window is still open, where the next pack push will
-- write, what lives there, and the 28 bytes that will be written.
--
-- Load via Tools > Lua Console > Script > Open Script.
-- Addresses verified for USA (NTSC-U 1.0). PAL/JP player pointers come from ScriptHawk
-- and are untested here; the PlayerState field offsets are assumed identical.

local VERSION = "USA" -- "USA", "EUR", "AUS", "JPN"

local V = {
	-- asset_ptrs/asset_ids: asset cache (pointer[0x82], u16 id[0x82]); dll_array: loaded code
	-- overlays; om2: loading-zone/prop array pointer. USA only for these extras.
	USA = { player_pointer = 0x135490, player_index = 0x1354DF, map = 0x132DC2,
	        asset_ptrs = 0x12B450, asset_ids = 0x12B6E0, dll_array = 0x126738, om2 = 0x132DB0 },
	EUR = { player_pointer = 0x13A4A0, player_index = 0x13A4EF, map = 0x137DD2 },
	AUS = { player_pointer = 0x13A210, player_index = 0x13A25F, map = 0x137B42 },
	JPN = { player_pointer = 0x12F660, player_index = 0x12F6AF, map = 0x12CF92 },
};
local M = V[VERSION];

-- PlayerState: one heap block = 0x19C header (0x56 component pointers) + components.
local PS_STATE     = 0x120 -- -> { previous, current, next } (u32 each)
local PS_STICK     = 0x128 -- -> BaStick (0x68 bytes)
local PS_TRANSFORM = 0x0A0 -- -> +0x29 current transformation (10 = solo Banjo)
local PS_ENTRYFLAG = 0x15D -- Snooze/Shack "setup already ran" flag (0 = window open)
local STICK_ZONE   = 0x38  -- current zone (0x1C bytes) = what a push writes
local STICK_INDEX  = 0x66  -- u8 stack index (stored_zones has only 2 slots)
local ZONE_SIZE    = 0x1C

-- Components after the stick, in allocation order (index into the 0x56 pointers)
local COMPONENT_NAMES = {
	[74] = "stick", [75] = "comp75 (func_8009F300)", [76] = "sub", [77] = "swim",
	[78] = "comp78 (func_800A06E0)", [79] = "timer", [80] = "translate", [81] = "van",
	[82] = "wandglow", [83] = "washer", [84] = "comp84 (func_800A0E50)", [85] = "wobble",
};

local STATE_NAMES = {
	[0x001] = "Idle", [0x007] = "Crouch", [0x073] = "Locked",
	[0x171] = "Entering Snooze", [0x16F] = "Snoozing", [0x172] = "Leaving Snooze",
	[0x060] = "Snooze talk (move)", [0x061] = "Snooze talk",
	[0x16A] = "Entering Shack", [0x16C] = "Shack idle", [0x16D] = "Shack walk",
	[0x16E] = "Shack jump", [0x16B] = "Leaving Shack",
	[0x05E] = "Shack talk (move)", [0x05F] = "Shack talk",
	[0x163] = "Entering Sack", [0x164] = "Leaving Sack", [0x165] = "Sack idle",
	[0x166] = "Sack walk", [0x169] = "Sack jump", [0x06E] = "Sack talk (move)", [0x080] = "Sack talk",
	[0x122] = "Entering Taxi", [0x127] = "Leaving Taxi",
};

local function isPtr(p) return p >= 0x80000000 and p < 0x80800000 end
local function phys(p) return p - 0x80000000 end
local function r32(p) return mainmemory.read_u32_be(phys(p)) end
local function r8(p) return mainmemory.read_u8(phys(p)) end
local function hex(v, n) return string.format("%0" .. (n or 8) .. "X", v) end

local function getPlayer()
	local i = mainmemory.read_u8(M.player_index);
	local p = mainmemory.read_u32_be(M.player_pointer + 4 * i);
	if isPtr(p) then return p end
end

-- Heap block containing addr, walking forward from the PlayerState's block header.
local function findBlock(ps, addr)
	local h = ps - 0x10;
	for _ = 1, 4000 do
		local nxt = r32(h + 4);
		if not isPtr(nxt) or nxt <= h then return nil end
		if addr >= h and addr < nxt then
			return h + 0x10, nxt - (h + 0x10), addr < h + 0x10;
		end
		h = nxt;
	end
end

-- What a heap block is, as far as we can tell: a loaded code overlay (DLL) by name, an asset by
-- id, Banjo's floor-triangle cache (PlayerState component 37), or the loading-zone array.
local function dllName(base)
	local off = 0x3C;
	for _ = 1, 400 do
		if not isPtr(r32(base + off)) then break end
		off = off + 4;
	end
	local t = {};
	for i = 0, 47 do
		local c = r8(base + off + i);
		if c == 0 then break end
		if c < 32 or c > 126 then return nil end
		t[#t + 1] = string.char(c);
	end
	if #t > 2 then return table.concat(t) end
end

local function blockLabel(ps, data)
	if data == r32(ps + 0x6AC) then return "Banjo floor cache (fall-through)" end
	local function m32(a) return mainmemory.read_u32_be(a) end -- M.* are physical addresses
	if M.om2 and data == m32(M.om2) then return "loading-zone array" end
	if M.asset_ptrs then
		for k = 0, 0x81 do
			if m32(M.asset_ptrs + 4 * k) == data then
				return string.format("asset %04X", mainmemory.read_u16_be(M.asset_ids + 2 * k));
			end
		end
	end
	if M.dll_array then
		for k = 0, 0x3FF do
			local p = m32(M.dll_array + 4 * k);
			if not isPtr(p) then break end
			if p == data then return "code: " .. (dllName(p) or "DLL") end
		end
	end
	return "";
end

local function describeTarget(ps, target)
	local psEnd = r32(ps - 0x10 + 4); -- next block header = end of PlayerState block
	if isPtr(psEnd) and target >= ps and target < psEnd then
		local best, bestIdx = nil, nil;
		for i = 0, 0x55 do
			local c = r32(ps + 4 * i);
			if c <= target and (best == nil or c > best) then best, bestIdx = c, i end
		end
		if best then
			return string.format("PlayerState %s +0x%X", COMPONENT_NAMES[bestIdx] or ("comp" .. bestIdx), target - best);
		end
	end
	local data, size, inHeader = findBlock(ps, target);
	if data == nil then return "unknown (heap walk failed)" end
	local where = inHeader and "HEAP HEADER of " or "";
	local past = isPtr(psEnd) and string.format(" (0x%X past PlayerState end)", target - psEnd) or "";
	return string.format("%sheap block %s size 0x%X +0x%X %s%s", where, hex(data), size, target - data, blockLabel(ps, data), past);
end

local function zoneString(addr)
	local pos = mainmemory.readfloat(phys(addr), true);
	local id = mainmemory.read_s32_be(phys(addr) + 4);
	local m = {};
	for k = 0, 4 do m[#m + 1] = string.format("%.3g", mainmemory.readfloat(phys(addr) + 8 + 4 * k, true)) end
	return string.format("pos=%.3f id=%d markers=[%s]", pos, id, table.concat(m, ", "));
end

local function rawString(addr)
	local t = {};
	for k = 0, ZONE_SIZE - 4, 4 do t[#t + 1] = hex(r32(addr + k)) end
	return table.concat(t, " ");
end

local lastIndex, lastPs = nil, nil;

local function onFrame()
	local ps = getPlayer();
	if ps == nil then return end
	local statePtr, stick, tf = r32(ps + PS_STATE), r32(ps + PS_STICK), r32(ps + PS_TRANSFORM);
	if not (isPtr(statePtr) and isPtr(stick)) then return end
	local cur, prev = r32(statePtr + 4), r32(statePtr);
	local idx = r8(stick + STICK_INDEX);
	local target = stick + idx * ZONE_SIZE;
	local transform = isPtr(tf) and r8(tf + 0x29) or -1;

	local window = "";
	if cur == 0x171 or cur == 0x16A then
		window = (r8(ps + PS_ENTRYFLAG) == 0) and "  <-- WINDOW OPEN: interact now" or "  (window closed: zone already pushed)";
	end

	local y, dy = 70, 14;
	local function line(s) gui.text(2, y, s); y = y + dy end
	line(string.format("Map %03X  transform %d  state %03X %s (prev %03X)", mainmemory.read_u16_be(M.map), transform, cur, STATE_NAMES[cur] or "", prev));
	line(string.format("Zone index %d %s%s", idx, idx > 1 and "(UNDERFLOWED: " .. (256 - idx) .. " glitch(es))" or "", window));
	line(string.format("PlayerState %s  stick %s", hex(ps), hex(stick)));
	line("Next push writes to " .. hex(target) .. ": " .. describeTarget(ps, target));
	line("  there now: " .. rawString(target));
	line("  will write: " .. rawString(stick + STICK_ZONE));
	line("  live zone: " .. zoneString(stick + STICK_ZONE));

	if lastPs ~= nil and ps ~= lastPs then
		-- heap compaction (e.g. a backflip or a new animation loading) moved Banjo's data: every
		-- target moves with it, relative to the blocks around it
		print(string.format("[frame %d] PlayerState moved %s -> %s (%+d bytes): targets shifted", emu.framecount(), hex(lastPs), hex(ps), ps - lastPs));
	end
	lastPs = ps;
	if lastIndex ~= nil and idx ~= lastIndex then
		print(string.format("[frame %d] zone index %d -> %d (state %03X, target %s)", emu.framecount(), lastIndex, idx, cur, hex(target)));
	end
	lastIndex = idx;
end

-- Practice helper: call PIM.setIndex(n) from the Lua console to jump straight to an
-- index (e.g. 255 = one glitch) without performing the setup each time.
PIM = {
	setIndex = function(n)
		local ps = getPlayer();
		if ps then mainmemory.write_u8(phys(r32(ps + PS_STICK) + STICK_INDEX), n % 256) end
	end,
	-- PIM.map(): print every heap block the glitch can reach right now, with the glitch counts
	-- that land in it (count k writes to slot 256-k). Compare rooms/routes with this.
	map = function()
		local ps = getPlayer();
		if not ps then return end
		local stick = r32(ps + PS_STICK);
		local lo, hi = stick + 20 * ZONE_SIZE, stick + 256 * ZONE_SIZE;
		local h = ps - 0x10;
		print(string.format("Map %03X  PlayerState %s  stick %s", mainmemory.read_u16_be(M.map), hex(ps), hex(stick)));
		for _ = 1, 4000 do
			local nxt = r32(h + 4);
			if not isPtr(nxt) or nxt <= h or h >= hi then break end
			if nxt > lo then
				local i0 = math.max(20, math.floor((h - stick) / ZONE_SIZE));
				local i1 = math.min(255, math.floor((nxt - 1 - stick) / ZONE_SIZE));
				local used = bit.band(r32(h + 0xC), 0xC0) ~= 0;
				print(string.format("  glitches %3d-%3d  block %s size %5X %s %s", 256 - i1, 256 - i0, hex(h + 0x10),
					nxt - h - 0x10, used and "    " or "FREE", blockLabel(ps, h + 0x10)));
			end
			h = nxt;
		end
	end,
};

event.onframeend(onFrame, "PIM Pack watcher");
print("PIM Pack watcher loaded (" .. VERSION .. "). PIM.setIndex(n) sets the zone index, PIM.map() lists what each glitch count hits.");
