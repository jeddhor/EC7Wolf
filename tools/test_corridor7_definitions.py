#!/usr/bin/env python3
"""Validate the released Corridor 7 pickup and weapon-definition contract."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
XLAT = (ROOT / "wadsrc/static/xlat/corridor7.txt").read_text()
PLAYER = (ROOT / "wadsrc/static/actors/corridor7/player.txt").read_text()
STATICS = (ROOT / "wadsrc/static/actors/corridor7/statics.txt").read_text()
MONSTERS = (ROOT / "wadsrc/static/actors/corridor7/monsters.txt").read_text()
CO7MAP = (ROOT / "wadsrc/static/co7map.txt").read_text()
WL_PLAY = (ROOT / "src/wl_play.cpp").read_text()
LNSPEC = (ROOT / "src/lnspec.cpp").read_text()
GAMEMAP_H = (ROOT / "src/gamemap.h").read_text()
WL_STATE = (ROOT / "src/wl_state.cpp").read_text()
GAMEMAP_PLANES = (ROOT / "src/gamemap_planes.cpp").read_text()
MAPINFO = (ROOT / "wadsrc/static/mapinfo/corridor7.txt").read_text()
PLAYERPAWN = (ROOT / "src/g_shared/a_playerpawn.cpp").read_text()
WL_AGENT = (ROOT / "src/wl_agent.cpp").read_text()
WL_INTER = (ROOT / "src/wl_inter.cpp").read_text()
WOLF_SBAR = (ROOT / "src/g_wolf/wolf_sbar.cpp").read_text()
SNDINFO = (ROOT / "wadsrc/static/sndinfo.txt").read_text()
M_CLASSES = (ROOT / "src/m_classes.cpp").read_text()
FLAT_TEXTURE = (ROOT / "src/textures/flattexture.cpp").read_text()
FLOOR_CEILING = (ROOT / "src/wl_floorceiling.cpp").read_text()
VSWAP = (ROOT / "src/resourcefiles/file_vswap.cpp").read_text()
WOLF_SHAPE = (ROOT / "src/textures/wolfshapetexture.cpp").read_text()
WL_DRAW = (ROOT / "src/wl_draw.cpp").read_text()
WL_MAIN = (ROOT / "src/wl_main.cpp").read_text()


def require(pattern: str, text: str, description: str) -> None:
    if re.search(pattern, text, re.MULTILINE | re.DOTALL) is None:
        raise SystemExit(f"Corridor 7 definition check failed: {description}")


for object_id, actor in {
    24: "C7Static001",       # red card
    25: "C7Static002",       # blue card
    28: "C7Static005",       # non-pickup row
    29: "C7M343",
    51: "C7DualBlaster",
    52: "C7FloorPlan",
    53: "C7PlasmaRifle",
    79: "C7AmmoPack",
    80: "C7Adrenaline",
    81: "C7ChargePack",
    82: "C7BodyArmor",
    83: "C7Invulnerability",
    84: "C7Static061",
    85: "C7MinePack",
    93: "C7VisorBattery",
    318: "C7Shotgun",
    319: "C7AssaultCannon",
    320: "C7Disintegrator",
}.items():
    require(
        rf"^\s*\{{{object_id},\s*{actor},",
        XLAT,
        f"object {object_id} must translate to {actor}",
    )

require(r"actor\s+C7Static003\s*\{", STATICS, "object 26 must not be a key")
require(r'player\.startitem\s+"C7M16".*?player\.startitem\s+"C7Bayonet"', PLAYER, "M-16 is readied before the backup Bayonet")
require(r'player\.startitem\s+"C7Bullets",\s*100', PLAYER, "100 starting bullets")
require(r"actor\s+C7Bullets\s*:\s*Ammo.*?inventory\.maxamount\s+200", PLAYER, "200 bullet maximum")
require(r"actor\s+C7EnergyCapacity\s*:\s*Ammo.*?inventory\.amount\s+100", PLAYER, "alien energy capacity")
require(r'actor\s+C7ChargePack\s*:\s*CustomInventory.*?A_GiveInventory\("C7Energy",\s*100\).*?A_GiveInventory\("C7EnergyCapacity",\s*100\)', PLAYER, "charge packs restore charge and capacity")
require(r"ConsumeC7AlienCharge\(self,\s*33,\s*4\)", (ROOT / "src/wl_agent.cpp").read_text(), "plasma 33/4 charge model")
require(r"clearance\[4\]\s*=\s*\{\s*10,\s*75,\s*100,\s*100\s*\}", LNSPEC, "rank clearance quotas")
require(r'args\[0\]\s*==\s*1\s*&&\s*!levelInfo->BonusLevel\s*&&\s*gamestate\.killtotal', LNSPEC, "clearance applies only to campaign elevators")
require(r'skill\s*=\s*MIN<unsigned int>\(gamestate\.difficulty->SpawnFilter,\s*3\)', LNSPEC, "zero-based rank clearance index")
require(r'tile\s+105\s*\{.*?sighttransparent\s*=\s*true', XLAT, "wall 105 is sight-transparent but solid")
require(r'tile\s+107\s*\{.*?sighttransparent\s*=\s*true', XLAT, "wall 107 is sight-transparent but solid")
require(r'tile\s+1\s*\{.*?C7W0000.*?tile\s+32\s*\{.*?C7W0031.*?tile\s+92\s*\{.*?C7W0091.*?tile\s+250\s*\{.*?C7W0249', XLAT, "solid wall IDs convert from one-based map IDs to zero-based pages")
for wall_id in range(1, 251):
    block = re.search(rf'tile\s+{wall_id}\s*\{{(.*?)\}}', XLAT, re.DOTALL)
    if block is None:
        raise SystemExit(f"Corridor 7 definition check failed: wall {wall_id} is missing")
    pages = re.findall(r'C7W(\d{4})', block.group(1))
    expected = f"{wall_id - 1:04d}"
    if pages != [expected] * 4:
        raise SystemExit(
            f"Corridor 7 definition check failed: wall {wall_id} must use page {expected}"
        )
require(r'bool\s+sightTransparent', GAMEMAP_H, "sight-transparent solid wall property")
require(r'bool\s+renderMasked', GAMEMAP_H, "masked wall rendering property")
require(r'for\(int candidate = 3;candidate <= 8;\+\+candidate\).*?\(1 << candidate\)\*\(1 << candidate\)\s*==\s*area', FLAT_TEXTURE, "Corridor 7 wall dimensions come from the VSWAP lump length")
require(r'CheckGameFilter\("Corridor7"\).*?Pixels\[i\]\s*==\s*255.*?bMasked\s*=\s*true', FLAT_TEXTURE, "Corridor 7 wall pages detect index-255 transparency")
require(r'source\s*==\s*255\s*\?\s*0\s*:\s*1.*?source\s*==\s*255\s*\?\s*0\s*:\s*source', FLAT_TEXTURE, "Corridor 7 index 255 normalizes to index 0 in a masked buffer with separate opacity")
require(r'bool\s+opaque\s*=\s*postopacity\s*==\s*NULL\s*\|\|\s*postopacity\[yw\]\s*!=\s*0.*?if\(opaque\).*?vbuf\[yendoffs\]', WL_DRAW, "solid walls and doors honor Corridor 7 opacity planes")
require(r'postopacity\s*=\s*source->GetColumnOpacity\(column\)', WL_DRAW, "wall columns carry their matching opacity columns")
require(r'corridor7\s*&&\s*source\s*==\s*255.*?source\s*=\s*0.*?GPalette\.Remap\[source\]', WOLF_SHAPE, "Corridor 7 sprite posts remap index 255 to 0 before palette injection")
require(r'oldplane\[i\]\s*==\s*104\s*\|\|\s*oldplane\[i\]\s*==\s*105.*?corridor7WallID-1.*?maskedWallType\s*=\s*1', GAMEMAP_PLANES, "markers 104/105 select wall-ID-minus-one masked pages")
require(r'corridor7SightTransparent\s*=\s*oldplane\[i\]\s*==\s*105', GAMEMAP_PLANES, "marker 105 alone is sight-transparent")
require(r'else if \(!spot->tile->sightTransparent\s*&&\s*!spot->corridor7SightTransparent\)', WL_STATE, "sight checks distinguish markers 104 and 105")
require(r'oldplane\[i\]\s*>=\s*86\s*&&\s*oldplane\[i\]\s*<=\s*88.*?corridor7WallMarker\s*=\s*oldplane\[i\]-85', GAMEMAP_PLANES, "masked-wall subtypes 86..88 are preserved")
require(r'CheckGameFilter\("Corridor7"\).*?DrawWindow\(x,\s*y,\s*9,\s*9', M_CLASSES, "palette-safe Corridor 7 checkbox")
require(r'trigger\s+98\s*\{.*?action\s*=\s*"Wall_Remove".*?secret\s*=\s*true', XLAT, "marker-98 secret walls disintegrate")
require(r'trigger\s+101\s*\{.*?action\s*=\s*"Wall_Remove"', XLAT, "marker-101 walls disintegrate")
require(r'trigger\s+102\s*\{.*?action\s*=\s*"Wall_Remove"', XLAT, "marker-102 walls disintegrate")
require(r'trigger\s+106\s*\{.*?action\s*=\s*"Wall_AnimateRemove".*?repeatable\s*=\s*false', XLAT, "marker-106 walls use their native four-frame opening")
require(r'oldplane\[i\]\s*==\s*106.*?Wall_AnimateRemove.*?maskedWallType\s*=\s*1.*?corridor7WallMarker\s*=\s*106', GAMEMAP_PLANES, "marker-106 animated walls use masked in-place geometry")
require(r'oldplane\[i\]\s*==\s*107.*?sideSolid\[0\].*?false.*?maskedWallType\s*=\s*1', GAMEMAP_PLANES, "marker-107 walls start permanently open and masked")
require(r'class\s+C7AnimatedWall.*?\+\+frame\s*>\s*3.*?corridor7WallID-1\+frame.*?frame\s*==\s*3.*?OpenWallCell\(spot,\s*false\)', LNSPEC, "Corridor 7 animated walls retain their final aperture")
require(r'color\s*>=\s*208\s*&&\s*color\s*<=\s*239.*?color\s*&\s*~7.*?TimeCount\s*>>\s*3', WL_DRAW, "all four Corridor 7 VGA palette ramps cycle every eight tics")
require(r'IsMaskedWallPassSide.*?IsMaskedWallSide.*?horizontalRun.*?verticalRun', WL_DRAW, "connected glass passes rays without rendering perpendicular end caps")
require(r'void\s+WolfStatusBar::DrawTopOverlay.*?TimeCount\s*<\s*5\*TICRATE.*?Eliminate Aliens To Secure Floor', WOLF_SBAR, "Corridor 7 objective is a timed top overlay")
require(r'ThreeDRefresh\s*\(\s*\).*?DrawTopOverlay\s*\(\s*\)', WL_PLAY, "top overlay redraws every rendered frame")
require(r'hasSignon\s*&&\s*IWad::CheckGameFilter\("Corridor7"\).*?VH_UpdateScreen\(\).*?return\s+false', WL_MAIN, "Corridor 7 startup keeps its splash free of ECWolf initialization text")
if len(re.findall(r'Time\s*=\s*-4', MAPINFO)) != 5 or len(re.findall(r'FadeType\s*=\s*FadeOut', MAPINFO)) < 6:
    raise SystemExit("Corridor 7 definition check failed: credits must hold for four seconds and fade between slides")
require(r'templateTrigger\.arg\[4\]\s*=\s*horizontal', GAMEMAP_PLANES, "door orientation must not overwrite lock IDs")
require(r'!levelInfo->BonusLevel\s*&&\s*gamestate\.killtotal', LNSPEC, "bonus elevators bypass campaign clearance")
require(r'health<=0\s*&&\s*IWad::CheckGameFilter\("Corridor7"\)\s*&&\s*levelInfo->BonusLevel', WL_AGENT, "bonus health expiration is intercepted before death")
require(r'health\s*=\s*mo->health\s*=\s*mo->SpawnHealth\(\).*?playstate\s*=\s*ex_completed', WL_AGENT, "bonus completion revives and advances the travelling pawn")
require(r'levelShotsFired.*?levelShotsHit', WL_AGENT, "save-backed Corridor 7 hit/miss statistics")
require(r'c7/teleport\s+\{\s+NULL\s+C7AL0040\s+C7PC0040\s+\}', SNDINFO, "Corridor 7 vortex completion sound")
require(r'painsound\s+"c7/player/pain".*?deathsound\s+"c7/player/death"', PLAYER, "Corridor 7 player pain and death audio")
require(r'accuracy\s*\*\s*\(shots\s*/\s*100\s*\+\s*1\)\s*\*\s*10', WL_INTER, "released hit/miss bonus equation")
require(r'MISSION HIT/MISS RATIO.*?Shots fired:.*?Shots hit:.*?Accuracy', WL_INTER, "Corridor 7 floor tally")
require(r'CONGRATULATIONS!.*?destroyed the vortex.*?Total floors secured', WL_INTER, "Corridor 7 victory presentation")
require(r'IWad::CheckGameFilter\("Corridor7"\).*?HIGH SCORES', WL_INTER, "Corridor 7 high scores avoid Wolf-only art")
require(r'LevelBonus\s*==\s*-1.*?ForceTally.*?!\(IWad::CheckGameFilter\("Corridor7"\)\s*&&\s*levelInfo->BonusLevel\)', WL_INTER, "bonus floors stay out of forty-floor victory averages")
require(r'LatchString\(10,\s*16,\s*2.*?LatchNumber\(30,\s*16,\s*7.*?LatchNumber\(296,\s*16,\s*2', WOLF_SBAR, "released HUD number placement")
require(r'DrawC7Gauge\(97,\s*172,.*?health\s*<\s*32\s*\?\s*80\s*:\s*128\).*?DrawC7Gauge\(97,\s*191,.*?5,\s*56\).*?DrawC7Gauge\(200,\s*172,.*?5,\s*104\).*?DrawC7Gauge\(200,\s*190,.*?5,\s*104\).*?DrawC7Gauge\(149,\s*193,.*?3,\s*56\)', WOLF_SBAR, "released native-index HUD gauge ramps")
require(r'C7G0019.*?C7G0020.*?C7G0021.*?C7G0018.*?256\+\(slot\+\+\)\*8,\s*176', WOLF_SBAR, "released three-slot HUD item graphics")
require(r'component\s*<<\s*2.*?component\s*>>\s*4', VSWAP, "Corridor 7 VGA DAC palette expansion")
require(r'PSPR_CORRIDOR7.*?TopOffset\s*=\s*-54.*?xScale\s*=\s*4\*FRACUNIT/5', WOLF_SHAPE, "native Corridor 7 weapon scale and anchor")
require(r'actor\s+C7M16.*?Ready:\s*C761\s+A\s+1\s+A_WeaponReady', PLAYER, "M-16 uses its released stationary frame")
require(r'0,\s*1,\s*2,\s*3,\s*4,\s*3,\s*2,\s*1,\s*0,\s*-1,\s*-2,\s*-3,\s*-4,\s*-3,\s*-2,\s*-1.*?if\(readyFrame\).*?xoffset\s*\+=\s*corridor7X\[phase\]', WL_DRAW, "released 16-step Corridor 7 stationary-frame weapon bob")
if "corridor7Frame" in WL_DRAW:
    raise SystemExit("Corridor 7 definition check failed: weapon bob must not copy live Frames")
require(r'CheckGameFilter\("Corridor7"\).*?curveStrength\s*=\s*floor\s*\?\s*40\s*:\s*24', FLOOR_CEILING, "Corridor 7 floor and ceiling depth ramps")
if len(re.findall(r'bonuslevel\s*=\s*true', MAPINFO, re.IGNORECASE)) != 6:
    raise SystemExit("Corridor 7 definition check failed: all six bonus maps must use bonus-level rules")
require(r'map\s+"MAP40".*?forcetally\s*=\s*true', MAPINFO, "MAP40 must tally before victory")
require(r"29,\s*18,\s*20,\s*9,\s*2,\s*14,\s*7,\s*8", WL_PLAY, "released music selector table")
require(r'^\s*\{300,\s*C7Semaj,', XLAT, "object 300 Semaj mapping")
require(r'"AILOA1".*?"AILOA8"', CO7MAP, "Ailoprobe directional sprite set")
require(r'"EITKA1".*?"EITKA8"', CO7MAP, "Eitak directional sprite set")
require(r"actor\s+C7Semaj\s*:.*?A_MeleeAttack", MONSTERS, "Semaj melee-only attack")
require(r'actor\s+C7SkullBoss\s*:.*?A_CustomMissile\("C7BossEnergyBolt"\)', MONSTERS, "Solrac energy projectile")
require(r'"Drop Mine".*?"Visor Mode"', WL_PLAY, "configuration-safe Corridor 7 control labels")

if "Reload / Drop Mine" in WL_PLAY or "Zoom / Visor Mode" in WL_PLAY:
    raise SystemExit("Corridor 7 definition check failed: control name would corrupt the saved config")

expected_slots = [
    "C7Bayonet",
    "C7Shotgun",
    "C7M16",
    "C7M343",
    "C7DualBlaster",
    "C7PlasmaRifle",
    "C7AssaultCannon",
    "C7Disintegrator",
]
for slot, actor in enumerate(expected_slots, 1):
    require(
        rf'player\.weaponslot\s+{slot},\s*"{actor}"',
        PLAYER,
        f"weapon slot {slot} must contain {actor}",
    )

if "C7Spinner" in PLAYER or "C7Needler" in PLAYER or "C7Stunner" in PLAYER:
    raise SystemExit("Corridor 7 definition check failed: fictitious weapon remains")

for actor, health in {
    "C7OrganicEye": "25, 25, 25, 100",
    "C7ProbeEye": "25, 50, 100, 150",
    "C7Technician": "50, 50, 150, 300",
    "C7Ugly": "25, 25, 50, 100",
    "C7Grunt": "50, 50, 150, 300",
    "C7Morph": "50, 50, 200, 500",
    "C7SpaceMarine": "50, 50, 200, 300",
    "C7EniramBoss": "1000, 1500, 2000, 4000",
    "C7PurpleBoss": "1000, 1500, 2000, 4000",
    "C7IronFoot": "500, 500, 1000, 1500",
    "C7SkullBoss": "1000, 1500, 3000, 5000",
    "C7HornedBoss": "5000, 6000, 7000, 9000",
}.items():
    require(
        rf"actor\s+{actor}\s*:.*?\{{.*?health\s+{re.escape(health)}",
        MONSTERS,
        f"{actor} health table",
    )

print("Corridor 7 definition checks passed")
