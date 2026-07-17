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
WL_GAME = (ROOT / "src/wl_game.cpp").read_text()
G_INTERMISSION = (ROOT / "src/g_intermission.cpp").read_text()
ID_VH = (ROOT / "src/id_vh.cpp").read_text()
GAMEMAP = (ROOT / "src/gamemap.cpp").read_text()
INVENTORY = (ROOT / "src/g_shared/a_inventory.cpp").read_text()
WL_DEBUG = (ROOT / "src/wl_debug.cpp").read_text()
R_SPRITES = (ROOT / "src/r_sprites.cpp").read_text()
NATIVE_ACTORS = (ROOT / "wadsrc/static/actors/native.txt").read_text()
LOCKDEFS = (ROOT / "wadsrc/static/lockdefs.txt").read_text()


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
    318: "C7Shotgun",
    319: "C7AssaultCannon",
    320: "C7Disintegrator",
}.items():
    require(
        rf"^\s*\{{{object_id},\s*{actor},",
        XLAT,
        f"object {object_id} must translate to {actor}",
    )

for ignored_id in (93,):
    require(
        rf"^\s*ignore\s+{ignored_id};",
        XLAT,
        f"internal object {ignored_id} must not spawn a graphics-page sprite",
    )

require(r"^\s*\{32,\s*C7DamageField,", XLAT,
        "electric-field object 32 must use the damage actor")
require(r"^\s*\{33,\s*C7DamageFieldAlt,", XLAT,
        "electric-field object 33 must preserve its alternate field art")
require(r"actor\s+C7DamageField\s*\{.*?C010\s+A\s+7\s+A_C7DamageField", STATICS,
        "electric fields must apply contact damage while retaining infrared art")

require(r"actor\s+C7Static003\s*\{", STATICS, "object 26 must not be a key")
require(r'player\.startitem\s+"C7M16".*?player\.startitem\s+"C7Bayonet"', PLAYER, "M-16 is readied before the backup Bayonet")
require(r'player\.startitem\s+"C7Bullets",\s*100', PLAYER, "100 starting bullets")
require(r"actor\s+C7Bullets\s*:\s*Ammo.*?inventory\.maxamount\s+200", PLAYER, "200 bullet maximum")
require(r"actor\s+C7EnergyCapacity\s*:\s*Ammo.*?inventory\.amount\s+100", PLAYER, "alien energy capacity")
require(r'actor\s+C7ChargePack\s*:\s*CustomInventory.*?A_GiveInventory\("C7Energy",\s*100\).*?A_GiveInventory\("C7EnergyCapacity",\s*100\)', PLAYER, "charge packs restore charge and capacity")
require(r"ConsumeC7AlienCharge\(self,\s*33,\s*4\)", (ROOT / "src/wl_agent.cpp").read_text(), "plasma 33/4 charge model")
require(r"clearance\[4\]\s*=\s*\{\s*10,\s*75,\s*100,\s*100\s*\}", LNSPEC, "rank clearance quotas")
require(r'trigger\s+63\s*\{.*?Exit_Normal.*?arg0\s*=\s*1', XLAT, "normal elevators pass their mode in argument zero")
require(r'actor\s+C7ExitVortex\s*:\s*CustomInventory.*?Exit_Normal', MONSTERS, "vortex pickup executes its floor exit action")
require(r'args\[0\]\s*==\s*1\s*&&\s*!levelInfo->BonusLevel\s*&&\s*gamestate\.killtotal', LNSPEC, "clearance applies only to campaign elevators")
require(r'MAX<unsigned int>\(1,\s*gamestate\.difficulty->SpawnFilter\)-1', LNSPEC,
        "one-based spawn filters must be converted to the zero-based clearance table")
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
require(r'oldplane\[i\]\s*>=\s*86\s*&&\s*oldplane\[i\]\s*<=\s*88.*?corridor7WallMarker\s*=\s*oldplane\[i\]-85', GAMEMAP_PLANES, "animated-wall phase markers 86..88 are preserved")
require(r'CheckGameFilter\("Corridor7"\).*?DrawWindow\(x,\s*y,\s*9,\s*9', M_CLASSES, "palette-safe Corridor 7 checkbox")
require(r'trigger\s+98\s*\{.*?action\s*=\s*"Wall_Remove".*?secret\s*=\s*true', XLAT, "marker-98 secret walls disintegrate")
require(r'trigger\s+101\s*\{.*?action\s*=\s*"Wall_Remove"', XLAT, "marker-101 walls disintegrate")
require(r'trigger\s+102\s*\{.*?action\s*=\s*"Wall_Remove"', XLAT, "marker-102 walls disintegrate")
require(r'trigger\s+106\s*\{.*?action\s*=\s*"Wall_AnimateRemove".*?repeatable\s*=\s*false', XLAT, "marker-106 walls use their native four-frame opening")
require(r'oldplane\[i\]\s*==\s*106.*?Wall_AnimateRemove.*?maskedWallType\s*=\s*1.*?corridor7WallMarker\s*=\s*106', GAMEMAP_PLANES, "marker-106 animated walls use masked in-place geometry")
require(r'oldplane\[i\]\s*==\s*107.*?sideSolid\[0\].*?false.*?maskedWallType\s*=\s*1', GAMEMAP_PLANES, "marker-107 walls start permanently open and masked")
require(r'class\s+C7AnimatedWall.*?\+\+frame\s*>\s*3.*?corridor7WallID-1\+frame.*?frame\s*==\s*3.*?OpenWallCell\(spot,\s*false\)', LNSPEC, "Corridor 7 animated walls retain their final aperture")
require(r'class\s+C7AnimatedWall.*?\+\+tics\s*<\s*8.*?\+\+frame', LNSPEC, "Corridor 7 chamber doors visibly advance their opening frames")
require(r'ActivateTrigger.*?trig\.active\s*&&\s*trig\.isSecret.*?\+\+gamestate\.secretcount.*?trig\.active\s*=\s*false',
        GAMEMAP, "successful secret walls count exactly once")
require(r'color\s*>=\s*208\s*&&\s*color\s*<=\s*239.*?color\s*&\s*~7.*?TimeCount\s*>>\s*3', WL_DRAW, "all four Corridor 7 VGA palette ramps cycle every eight tics")
require(r'IsMaskedWallPassSide.*?CheckGameFilter\("Corridor7"\).*?return\s+true.*?RecordMaskedWallHit.*?maskedWallHits\.Push.*?DrawMaskedWall.*?hitFirst.*?hitLast', WL_DRAW, "masked Corridor 7 rays cross adjacent glass and retain their exact surface spans")
require(r'IsConnectedMaskedWall.*?corridor7WallID.*?IsMaskedWallRenderSide.*?horizontalRun.*?verticalRun.*?RecordMaskedWallHit', WL_DRAW, "adjacent masked walls suppress internal end faces while rays continue through them")
require(r'height\s*>=\s*maskedWallDepth\[depthIndex\].*?maskedWallDepth\[depthIndex\]\s*=\s*height', WL_DRAW, "overlapping masked walls use per-pixel depth compositing")
require(r'GetWallTexture.*?corridor7WallMarker\s*>=\s*1.*?corridor7WallMarker\s*<=\s*3.*?textureName\.Format\("C7W%04u",\s*base\+i\).*?TimeCount/5.*?animation\[base\]\[frame\]', WL_DRAW, "markers 86..88 animate four wall pages at the DOS cadence")
for wall_id, result_id, kind in ((9, 10, 1), (11, 12, 2), (30, 31, 3)):
    require(
        rf'trigger\s+{wall_id}\s*\{{.*?action\s*=\s*"C7_WallSwitch".*?arg0\s*=\s*{result_id}.*?arg1\s*=\s*{kind}.*?playeruse\s*=\s*true',
        XLAT,
        f"wall {wall_id} must activate its native Corridor 7 terminal result",
    )
require(r'FUNC\(C7_WallSwitch\).*?C7Static001.*?C7Static002.*?GiveInventory.*?P_AlertCorridor7Monsters', LNSPEC, "Corridor 7 terminals grant access cards or raise the intruder alert")
require(r'RED Access Granted.*?BLUE Access Granted', LNSPEC, "access terminals display their released grant messages")
require(r'Lock\s+1\s+Corridor7.*?BLUE Access Required.*?Lock\s+2\s+Corridor7.*?RED Access Required', LOCKDEFS, "locked doors display their released access requirements")
for wall_id, kind in ((85, 1), (88, 1), (111, 2), (110, 3)):
    require(
        rf'trigger\s+{wall_id}\s*\{{.*?action\s*=\s*"C7_Dispenser".*?arg0\s*=\s*{kind}.*?playeruse\s*=\s*true.*?repeatable\s*=\s*true',
        XLAT,
        f"Corridor 7 dispenser wall {wall_id}",
    )
require(r'FUNC\(C7_Dispenser\).*?C7MedicPack.*?GiveInventory.*?SetC7WallTexture\(spot,\s*89\).*?C7Bullets.*?GiveInventory\(ammo,\s*50\).*?SetC7WallTexture\(spot,\s*112\)', LNSPEC, "Corridor 7 wall dispensers grant 25 health or 50 bullets and become empty")
require(r'args\[0\]\s*==\s*3.*?C7VisorCharge.*?FULL VISOR CHARGE.*?visor->amount\s*=\s*visor->maxamount.*?VISOR BATTERY RECHARGED',
        LNSPEC, "wall 110 is a non-wasteful reusable visor charger")
require(r'FULL HEALTH.*?return\s+false', INVENTORY,
        "health packs remain in the world when the player is full")
require(r'amount\s*<\s*maxamount.*?else.*?FULL AMMO.*?return\s+true', INVENTORY,
        "ammo packs remain in the world when the player is full")
require(r'FUNC\(C7_Dispenser\).*?FULL HEALTH.*?SetC7WallTexture\(spot,\s*89\).*?FULL AMMO.*?SetC7WallTexture\(spot,\s*112\)',
        LNSPEC, "full players cannot waste wall health or ammunition")
require(r'actor\s+C7MedicPack\s*:\s*Health.*?inventory\.amount\s+25', PLAYER, "Corridor 7 health dispensers supply 25 health")
require(r'skill\s+nightmare\s*\{.*?name\s*=\s*"President".*?spawnfilter\s*=\s*4',
        MAPINFO, "Presidential difficulty is exposed")
require(r'RandomizeCorridor7PresidentThings.*?FL_ISMONSTER.*?NATIVE_CLASS\(Inventory\).*?pr_c7president',
        GAMEMAP, "President relocates monsters and pickups")
require(r'P_AlertCorridor7Monsters.*?AActor::GetIterator.*?FL_SHOOTABLE.*?FirstSighting', WL_STATE, "intruder alert wakes every live monster")
require(r'void\s+WolfStatusBar::DrawTopOverlay.*?TimeCount\s*<\s*5\*TICRATE.*?Eliminate Aliens To Secure Floor', WOLF_SBAR, "Corridor 7 objective is a timed top overlay")
require(r'SetTopMessage.*?topMessageUntil.*?DrawTopOverlay', WOLF_SBAR, "Corridor 7 transient gameplay messages draw above the view")
require(r'TryUseC7HealthChamber.*?c7ChamberState\s*=\s*1.*?TickC7HealthChamber.*?C7ChamberExitAngle.*?SetC7HealthChamberPower',
        PLAYERPAWN, "health chambers turn the player, close, heal, and show remaining power")
require(r'TryUseC7HealthChamber.*?MapSpot\s+panel.*?MapSpot\s+door.*?panel->corridor7WallID\s*!=\s*35.*?door->corridor7WallID\s*!=\s*53.*?door->corridor7WallMarker\s*!=\s*107',
        PLAYERPAWN, "health chambers activate at the rear panel with the open door opposite")
require(r'actor\s+C7FloorPlan\s*:\s*MapRevealer', PLAYER,
        "the floor-plan pickup uses the native full-map inventory path")
require(r'class\s+AMapRevealer.*?TryPickup.*?gamestate\.fullmap\s*=\s*true.*?CheckGameFilter\("Corridor7"\).*?Super::TryPickup',
        INVENTORY, "Corridor 7 keeps the floor-plan HUD token after revealing the map")
require(r'Keyboard\[sc_W\].*?Keyboard\[sc_A\].*?Keyboard\[sc_X\].*?GiveCorridor7Cheat',
        WL_DEBUG, "holding W+A+X activates the Corridor 7 equipment cheat")
require(r'GiveCorridor7Cheat.*?GiveAllWeaponsAndAmmo.*?P_GiveKeys.*?gamestate\.fullmap\s*=\s*true.*?C7VisorCharge',
        WL_DEBUG, "the WAX cheat grants weapons, access, map, health, armor, and visor charge")
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
require(r'ACTION_FUNCTION\(A_C7GunAttack\).*?DepleteAmmo.*?PlaySoundLocActor.*?if\(!closest\)\s*return\s+true.*?return\s+true', WL_AGENT, "missed Corridor 7 shots consume ammo, play audio, and finish their weapon state")
require(r'accuracy\s*\*\s*\(shots\s*/\s*100\s*\+\s*1\)\s*\*\s*10', WL_INTER, "released hit/miss bonus equation")
require(r'CA_CacheScreen\(TexMan\("C7G0014"\)\).*?SECURED.*?aliens.*?restricted.*?accuracy.*?InterState\.bonus',
        WL_INTER, "Corridor 7 floor tally uses the original status-report screen")
require(r'case\s+ex_died:.*?CheckGameFilter\("Corridor7"\).*?Corridor7Death.*?CheckHighScore.*?return\s+false',
        WL_GAME, "Corridor 7 death must show its report and return to high scores/title without retrying")
require(r'Background\s*=\s*"C7G0006".*?FadeType\s*=\s*Fizzle', MAPINFO,
        "the Corridor 7 logo must fizzle into the clean title background")
require(r'FFizzleFader\s+dissolve.*?MAX\(1U,\s*fader->Time\),\s*true\).*?ShowImage.*?FizzleFade', G_INTERMISSION,
        "intermission fizzle captures both the title and destination pages")
require(r'fadems\(TICS2MS\(frames\)\),\s*startms\(0\).*?if\(startms\s*==\s*0\).*?startms\s*=\s*SDL_GetTicks',
        ID_VH, "fizzle timing starts after the destination page is ready")
require(r'CheckGameFilter\("Corridor7"\).*?C7G0004.*?C7G0073.*?PreloadUpdate', WL_INTER,
        "Corridor 7 level loads must show the original loading plate and progress screen")
require(r'Corridor7Death.*?C7G0004.*?C7G0003.*?Total floors secured.*?Alien kill ratio.*?Overall rating',
        WL_INTER, "Corridor 7 death uses its original report artwork and fields")
require(r'DrawHighScores.*?CheckGameFilter\("Corridor7"\).*?C7G0016.*?HIGH SCORES',
        WL_INTER, "Corridor 7 high scores use the original portrait page")
require(r'PrepareCorridor7HighScores.*?id software-.*?Capstone 94.*?Les.*?Joe.*?Jeff.*?Ruben.*?Carlos.*?David',
        WL_INTER, "fresh Corridor 7 high scores use the original Capstone names")
require(r'C7StencilPrintAt.*?HIGH SCORES.*?0xB7.*?NAME.*?0x24.*?0x57-2\*i.*?0x6F-2\*i',
        WL_INTER, "high scores use the executable's exact VGA text colors")
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
require(r'actor\s+C7SpaceMarine\s*:.*?Missile:.*?C676.*?C678.*?A_WolfAttack.*?C681.*?A_WolfAttack.*?Pain:.*?C684',
        MONSTERS, "Eniram attack and pain animations use separate released frame ranges")
require(r'actor\s+C7Ugly\s*:.*?Missile:.*?C233.*?C238.*?Pain:.*?C225.*?C226',
        MONSTERS, "Rodex attack no longer reuses its hurt frames")
require(r'A_CustomMissile\("C7BossEnergyBolt"\).*?A_PlaySound\("c7/monster/attack"\)|A_PlaySound\("c7/monster/attack"\).*?A_CustomMissile\("C7BossEnergyBolt"\)',
        MONSTERS, "projectile bosses play their attack sound")
require(r'A_FireCustomMissile.*?C7PlasmaBolt.*?c7MuzzleFlashTics\s*=\s*5.*?PlaySoundLocActor',
        WL_AGENT, "the player plasma projectile has firing audio and muzzle lighting")
require(r'action\s+native\s+A_C7AlienAlarm', NATIVE_ACTORS,
        "the Ailoprobe alarm action is registered")
require(r'C7VisorCanSeeActor.*?C7DamageField.*?C7SpaceMarine.*?infrared',
        R_SPRITES, "infrared alone reveals damage fields and cloaked Eniram actors")
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
