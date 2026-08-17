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
WL_ACT2 = (ROOT / "src/wl_act2.cpp").read_text()
WL_INTER = (ROOT / "src/wl_inter.cpp").read_text()
WOLF_SBAR = (ROOT / "src/g_wolf/wolf_sbar.cpp").read_text()
SNDINFO = (ROOT / "wadsrc/static/sndinfo.txt").read_text()
SNDSEQ = (ROOT / "wadsrc/static/sndseq.txt").read_text()
M_CLASSES = (ROOT / "src/m_classes.cpp").read_text()
FLAT_TEXTURE = (ROOT / "src/textures/flattexture.cpp").read_text()
FLOOR_CEILING = (ROOT / "src/wl_floorceiling.cpp").read_text()
VSWAP = (ROOT / "src/resourcefiles/file_vswap.cpp").read_text()
V_PALETTE = (ROOT / "src/v_palette.cpp").read_text()
AUDIO_MUS = (ROOT / "src/resourcefiles/file_audiomus.cpp").read_text()
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
THINGDEF_CODEPTR = (ROOT / "src/thingdef/thingdef_codeptr.cpp").read_text()
WL_DEF = (ROOT / "src/wl_def.h").read_text()
GLWORLD = (ROOT / "src/render/opengl/r_glworld.cpp").read_text()
WL_MENU = (ROOT / "src/wl_menu.cpp").read_text()


def require(pattern: str, text: str, description: str) -> None:
    if re.search(pattern, text, re.MULTILINE | re.DOTALL) is None:
        raise SystemExit(f"Corridor 7 definition check failed: {description}")


def forbid(pattern: str, text: str, description: str) -> None:
    if re.search(pattern, text, re.MULTILINE | re.DOTALL) is not None:
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

# 93 is one of the eight patrol turning points (90..97), not a sprite. The
# guard is kept, because the thing it protects against is real -- read as a
# graphics page, 93 becomes a collectible, room-sized mine-explosion frame --
# but it now asserts what 93 actually is instead of asserting that it is
# ignored, which it no longer is.
require(
    r"^\s*\{90,\s*PatrolPoint,\s*8,",
    XLAT,
    "objects 90..97 must be the inherited patrol turning points, so that "
    "PATHING aliens have a route to follow and 93 stays out of the sprite pages",
)
for sprite_actor in ("C7Static", "C7Ammo", "C7Medic"):
    forbid(
        rf"^\s*\{{9[0-7],\s*{sprite_actor}",
        XLAT,
        f"no patrol turning point may translate to a {sprite_actor}* sprite",
    )

require(r"^\s*\{32,\s*C7DamageField,", XLAT,
        "object 32 must use the normally visible lightpost actor")
require(r"^\s*\{33,\s*C7DamageFieldAlt,", XLAT,
        "electric-field object 33 must preserve its alternate field art")
require(r"actor\s+C7DamageField\s*\{.*?C010\s+A\s+-1", STATICS,
        "normally visible Corridor 7 lightposts remain harmless")
require(r"actor\s+C7DamageField\s*\{.*?\+SOLID.*?C010\s+A\s+-1", STATICS,
        "Corridor 7 lightposts preserve their original solid static type")
require(r"actor\s+C7DamageFieldAlt.*?C011\s+A\s+-1", STATICS,
        "infrared C011 statics remain inert instead of creating inferred beams")
if "A_C7DamageField" in STATICS or "A_C7DamageField" in WL_AGENT:
    raise SystemExit("Corridor 7 definition check failed: C011 statics must not infer paired damage beams")

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
for door_id, page in ((251, 250), (252, 251), (253, 252), (254, 253)):
    require(
        rf'tile\s+{door_id}\s*\{{.*?texturenorth\s*=\s*"C7W0254".*?'
        rf'texturesouth\s*=\s*"C7W0254".*?textureeast\s*=\s*"C7W{page:04d}".*?'
        rf'texturewest\s*=\s*"C7W{page:04d}".*?autoorient\s*=\s*true',
        XLAT,
        f"door {door_id} uses the composite five-bank/track page 254 on its jamb faces",
    )
require(r'horizontal\.texture\[MapTile::North\].*?texture\[MapTile::East\].*?'
        r'horizontal\.texture\[MapTile::East\].*?texture\[MapTile::North\]',
        GAMEMAP_PLANES, "auto-oriented doors rotate face and jamb textures with their axis")
require(r'bool\s+sightTransparent', GAMEMAP_H, "sight-transparent solid wall property")
require(r'bool\s+renderMasked', GAMEMAP_H, "masked wall rendering property")
require(r'for\(int candidate = 3;candidate <= 8;\+\+candidate\).*?\(1 << candidate\)\*\(1 << candidate\)\s*==\s*area', FLAT_TEXTURE, "Corridor 7 wall dimensions come from the VSWAP lump length")
require(r'CheckGameFilter\("Corridor7"\).*?Pixels\[i\]\s*==\s*255.*?bMasked\s*=\s*true', FLAT_TEXTURE, "Corridor 7 wall pages detect index-255 transparency")
require(r'source\s*==\s*255\s*\?\s*0\s*:\s*1.*?source\s*==\s*255\s*\?\s*0\s*:\s*source', FLAT_TEXTURE, "Corridor 7 index 255 normalizes to index 0 in a masked buffer with separate opacity")
require(r'for\(unsigned int side = 0;side < 4;\+\+side\).*?texture\[side\].*?wall->bMasked.*?maskedWallType\s*=\s*1', GAMEMAP_PLANES,
        "all directional faces, including auto-oriented door faces, participate in Corridor 7 transparency detection")
require(r'bool\s+opaque\s*=\s*postopacity\s*==\s*NULL\s*\|\|\s*postopacity\[yw\]\s*!=\s*0.*?if\(opaque\).*?vbuf\[yendoffs\]', WL_DRAW, "solid walls and doors honor Corridor 7 opacity planes")
require(r'postopacity\s*=\s*source->GetColumnOpacity\(column\)', WL_DRAW, "wall columns carry their matching opacity columns")
require(r'corridor7\s*&&\s*source\s*==\s*255.*?source\s*=\s*0.*?GPalette\.Remap\[source\]', WOLF_SHAPE, "Corridor 7 sprite posts remap index 255 to 0 before palette injection")
require(r'oldplane\[i\]\s*==\s*104\s*\|\|\s*oldplane\[i\]\s*==\s*105.*?corridor7WallID-1.*?maskedWallType\s*=\s*1', GAMEMAP_PLANES, "markers 104/105 select wall-ID-minus-one masked pages")
require(r'corridor7SightTransparent\s*=\s*oldplane\[i\]\s*==\s*105', GAMEMAP_PLANES, "marker 105 alone is sight-transparent")
require(r'TileBlocksSight\(spot\)', WL_STATE,
		"render-only masked-wall transparency is kept separate from line-of-sight")
require(r'oldplane\[i\]\s*>=\s*86\s*&&\s*oldplane\[i\]\s*<=\s*88.*?corridor7WallMarker\s*=\s*oldplane\[i\]-85', GAMEMAP_PLANES, "animated-wall phase markers 86..88 are preserved")
if re.search(r'oldplane\[i\]\s*==\s*237.*?SetTile\(NULL\)', GAMEMAP_PLANES, re.DOTALL):
    raise SystemExit("Corridor 7 definition check failed: wall 237 must remain the solid planet-animation frame")
require(r'CheckGameFilter\("Corridor7"\).*?DrawWindow\(x,\s*y,\s*9,\s*9', M_CLASSES, "palette-safe Corridor 7 checkbox")
require(r'trigger\s+98\s*\{.*?action\s*=\s*"Pushwall_Move".*?arg1\s*=\s*8.*?arg2\s*=\s*2.*?arg3\s*=\s*2.*?secret\s*=\s*true', XLAT, "marker-98 secret walls visibly slide two tiles")
require(r'trigger\s+101\s*\{.*?action\s*=\s*"Pushwall_Move".*?arg1\s*=\s*8.*?arg2\s*=\s*2.*?arg3\s*=\s*2', XLAT, "marker-101 walls visibly slide two tiles")
require(r'trigger\s+102\s*\{.*?action\s*=\s*"Pushwall_Move".*?arg1\s*=\s*8.*?arg2\s*=\s*2.*?arg3\s*=\s*2', XLAT, "marker-102 walls visibly slide two tiles")
require(r'trigger\s+106\s*\{.*?action\s*=\s*"Wall_AnimateRemove".*?repeatable\s*=\s*false', XLAT, "marker-106 walls use their native four-frame opening")
require(r'oldplane\[i\]\s*==\s*106.*?Wall_AnimateRemove.*?maskedWallType\s*=\s*1.*?corridor7WallMarker\s*=\s*106', GAMEMAP_PLANES, "marker-106 animated walls use masked in-place geometry")
require(r'oldplane\[i\]\s*==\s*107.*?sideSolid\[0\].*?false.*?maskedWallType\s*=\s*1', GAMEMAP_PLANES, "marker-107 walls start permanently open and masked")
# Split across three checks rather than one ordered match: the frame texture
# moved into SetFrameTexture(), which is defined below the frame logic, so a
# single regex spanning both can no longer match in source order.
require(r'class\s+C7AnimatedWall.*?\+\+frame\s*>\s*3.*?Destroy\(\)', LNSPEC, "Corridor 7 animated walls stop after their fourth page")
require(r'!activating\s*&&\s*frame\s*==\s*3.*?maskedWallType\s*=\s*1.*?OpenWallCell\(spot,\s*false\)', LNSPEC, "Corridor 7 animated walls retain their final aperture")
require(r'SetFrameTexture.*?C7W%04u.*?corridor7WallID-1\+frame', LNSPEC, "Corridor 7 animated walls page through wall-ID-minus-one")
require(r'class\s+C7AnimatedWall.*?\+\+tics\s*<\s*8.*?\+\+frame', LNSPEC, "Corridor 7 chamber doors visibly advance their opening frames")
require(r'ActivateTrigger.*?trig\.active\s*&&\s*trig\.isSecret.*?\+\+gamestate\.secretcount.*?trig\.active\s*=\s*false',
        GAMEMAP, "successful secret walls count exactly once")
# The rotation rate is measured, not chosen: facing a force-field wall in the
# released game, a phase lasts exactly 2 tics at 20000 DOSBox cycles and 1 tic at
# 60000 (the 70Hz retrace ceiling). Shift 1 is the 2-tic value. All three render
# paths must read the same constant or a wall and the sprite in front of it will
# rotate at different speeds.
require(r'#define\s+C7_RAMP_CYCLE_SHIFT\s+1\b', WL_DEF, "Corridor 7 VGA ramps rotate one phase every two tics")
require(r'color\s*>=\s*208\s*&&\s*color\s*<=\s*239.*?color\s*&\s*~7.*?TimeCount\s*>>\s*C7_RAMP_CYCLE_SHIFT', WL_DRAW, "Corridor 7 wall ramps rotate on the shared cycle constant")
require(r'color\s*>=\s*208\s*&&\s*color\s*<=\s*239.*?color\s*&\s*~7.*?TimeCount\s*>>\s*C7_RAMP_CYCLE_SHIFT', R_SPRITES, "Corridor 7 sprite ramps rotate on the shared cycle constant")
require(r'cyclePhase\s*=.*?TimeCount\s*>>\s*C7_RAMP_CYCLE_SHIFT', GLWORLD, "the GL renderer rotates ramps on the shared cycle constant")
require(r'ShadeWallColor.*?GPalette\.Remap\[15\].*?GPalette\.Remap\[254\].*?GPalette\.Remap\[208\].*?GPalette\.Remap\[239\].*?NormalLight\.Maps\[color\]', WL_DRAW,
        "Corridor 7 dedicated lamp whites and animated light ramps remain full-bright")
if re.search(r'ShadeWallColor.*?GPalette\.Remap\[39\]', WL_DRAW, re.DOTALL):
    raise SystemExit("Corridor 7 definition check failed: ordinary structural white 39 must remain shaded")
# The visor palettes are now the released game's own DAC, read per index
# (see V_SetCorridor7PaletteMode), so check the tables themselves rather than
# the hand-written exemptions they replaced. Doing it as data also catches the
# thing the old regex asserted wrongly: only infrared keeps the lamp white.
# Night vision tints index 15 like everything else.
def c7_visor_table(name):
    body = re.search(name + r'\[256\]\[3\]\s*=\s*\{(.*?)\n\};', V_PALETTE, re.DOTALL)
    if body is None:
        raise SystemExit("Corridor 7 definition check failed: %s table missing" % name)
    entries = re.findall(r'\{\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\}', body.group(1))
    if len(entries) != 256:
        raise SystemExit("Corridor 7 definition check failed: %s has %d entries, expected 256"
                         % (name, len(entries)))
    return [tuple(int(c) for c in e) for e in entries]

_c7_nv = c7_visor_table('Corridor7NightVisionPal')
_c7_ir = c7_visor_table('Corridor7InfraredPal')
for _idx, _want, _table, _why in (
        (15, (255, 255, 255), _c7_ir, "infrared keeps the lamp core white"),
        (254, (0, 0, 0), _c7_ir, "infrared blacks out the lamp halo ring"),
        (39, (255, 0, 0), _c7_ir, "infrared tints ordinary structural white, unlike the lamp"),
        (15, (0, 255, 0), _c7_nv, "night vision tints the lamp core like everything else")):
    if _table[_idx] != _want:
        raise SystemExit("Corridor 7 definition check failed: %s (index %d is %s, expected %s)"
                         % (_why, _idx, _table[_idx], _want))
if re.search(r'mode\s*!=\s*3.*?i\s*==\s*39', V_PALETTE, re.DOTALL):
    raise SystemExit("Corridor 7 definition check failed: visor palettes must tint ordinary white 39")
# The visor modes are a whole-DAC rewrite, not a tint over the 3D view, so every
# 2D surface inherits them -- and UpdatePaletteShifts, which would undo it, only
# runs inside the play loop. The menu is entered from within that loop, so it has
# to reset the palette itself or it comes out green or red.
require(r'void SetupControlPanel \(void\)\s*\{.*?FinishPaletteShifts\(\);', WL_MENU,
        "the menu resets the Corridor 7 visor palette on the way in")
if len(re.findall(r'ShadeWallColor\((?:postsource|source)\[yw\],\s*curshades\)', WL_DRAW)) != 3:
    raise SystemExit("Corridor 7 definition check failed: solid and masked wall posts must share emissive shading")
require(r'actor\s+C7DamageField\s*\{.*?C010\s+A\s+-1\s+bright', STATICS,
        "the normally visible C010 floor light keeps its source brightness")
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
require(r'skill\s+easy\s*\{.*?name\s*=\s*"Lieutenant".*?spawnfilter\s*=\s*2',
        MAPINFO, "the second Corridor 7 rank uses its original Lieutenant label")
if "2nd Lieutenant" in MAPINFO:
    raise SystemExit("Corridor 7 definition check failed: non-original 2nd Lieutenant label remains")
require(r'RandomizeCorridor7PresidentThings.*?FL_ISMONSTER.*?NATIVE_CLASS\(Inventory\).*?pr_c7president',
        GAMEMAP, "President relocates monsters and pickups")
require(r'P_AlertCorridor7Monsters.*?AActor::GetIterator.*?FL_SHOOTABLE.*?FirstSighting', WL_STATE, "intruder alert wakes every live monster")
# The yellow is measured off a DOSBox capture of the CD release on MAP01, where
# the banner is exactly (255,255,0) with no intermediate shades. This check used
# to assert BaseColors[3] -- (215,215,0) -- which is the value the code had, not
# the value the game had, and only looks wrong over a pale background.
require(r'DrawC7TopMessage.*?CR_BLACK,\s*5,\s*5.*?DTA_FillColor.*?BlackIndex.*?CR_YELLOW,\s*4,\s*4.*?DTA_FillColor,\s*PalEntry\(255, 255, 0\)', WOLF_SBAR,
        "Corridor 7 top notifications use the DOS release's (255,255,0) stencil and a one-pixel black drop shadow")
require(r'void\s+WolfStatusBar::DrawTopOverlay.*?TimeCount\s*<\s*5\*TICRATE.*?DrawC7TopMessage\("Eliminate Aliens To Secure Floor"\)', WOLF_SBAR, "Corridor 7 objective is a timed top overlay")
require(r'SetTopMessage.*?topMessageUntil.*?DrawTopOverlay', WOLF_SBAR, "Corridor 7 transient gameplay messages draw above the view")
require(r'TryUseC7HealthChamber.*?c7ChamberState\s*=\s*1.*?TickC7HealthChamber.*?C7ChamberExitAngle.*?SetC7HealthChamberPower',
        PLAYERPAWN, "health chambers turn the player, close, heal, and show remaining power")
require(r'buttonstate\[bt_use\]\s*&&\s*!cmd\.buttonheld\[bt_use\].*?Cmd_Use\(\)',
        PLAYERPAWN, "Use actions run once per key press instead of grunting every tic")
require(r'corridor7ChamberPower.*?SetC7HealthChamberPower\(player->c7ChamberPower,\s*4\*TICRATE\).*?MIN<unsigned int>\(missing,\s*power\).*?corridor7ChamberPower\s*=\s*power-restored.*?StartC7ChamberFlash',
		PLAYERPAWN, "health chambers immediately show and persist a proportional 100-point reservoir")
require(r'DrawC7GradientBar.*?column\*paletteColors\)/fullWidth.*?paletteStart\+shade',
		WOLF_SBAR, "wide gauges stretch a complete palette ramp across their authored well")
require(r'C7G0062.*?meterLeft\s*=\s*3.*?meterRight\s*=\s*3.*?'
		r'meterBottom\s*=\s*3.*?meterHeight\s*=\s*5.*?GetScaledWidth\(\).*?'
		r'filledWidth\s*=\s*\(power\*meterWidth\+50\)/100.*?'
		r'DrawC7GradientBar\(meterX,\s*meterY,\s*filledWidth,\s*meterWidth,.*?128,\s*8\)',
		WOLF_SBAR,
		"health chamber power fills C7G0062's 42x5 recessed well with the green ramp")
require(r'storedPower.*?corridor7ChamberPower.*?0x80.*?corridor7ChamberPower\s*&=\s*0x7f.*?MIN<unsigned int>\(plane\.map\[i\]\.corridor7ChamberPower,\s*3\)\*100\)/3', GAMEMAP,
		"health chamber reservoir saves are tagged while legacy three-use saves remain compatible")
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
# The overlay is no longer drawn inline after ThreeDRefresh: it goes through
# IRenderer::DrawViewOverlay so a compositing backend can measure which view
# texels it paints. The property is the same -- rendered scene, then overlay.
require(r'Renderer->RenderScene\s*\(\s*\).*?Renderer->DrawViewOverlay\(DrawTopOverlayThunk\)',
        WL_PLAY, "top overlay redraws every rendered frame, through the renderer seam")
# The Wolf PAUSED art was never absent for Corridor 7 -- VGAGRAPH chunk 72 holds
# it, and it was simply still under its numeric name, so TexMan found nothing and
# the label was stencilled out of the small font instead. A DOSBox capture of the
# CD release matches that 64x32 picture at exactly (128, 64), which is where the
# stock call already draws it: naming the chunk is the whole fix, and the
# game-specific branch is gone with it.
require(r'^\t"PAUSED",$', CO7MAP, "VGAGRAPH chunk 72 must be named PAUSED")
require(r'if\(Paused\s*&\s*1\).*?VWB_DrawGraphic\(TexMan\("PAUSED"\), \(20 - 4\)\*8, 80 - 2\*8\);',
        WL_PLAY, "the pause label is Corridor 7's own picture, drawn at (128, 64)")
forbid(r'DrawPausedOverlay.*?CheckGameFilter\("Corridor7"\)',
       WL_PLAY, "the pause overlay must not need a Corridor 7 special case")
require(r'hasSignon\s*&&\s*IWad::CheckGameFilter\("Corridor7"\).*?VH_UpdateScreen\(\).*?return\s+false', WL_MAIN, "Corridor 7 startup keeps its splash free of EC7Wolf initialization text")
if len(re.findall(r'Time\s*=\s*-4', MAPINFO)) != 5 or len(re.findall(r'FadeType\s*=\s*FadeOut', MAPINFO)) < 6:
    raise SystemExit("Corridor 7 definition check failed: credits must hold for four seconds and fade between slides")
require(r'templateTrigger\.arg\[4\]\s*=\s*horizontal', GAMEMAP_PLANES, "door orientation must not overwrite lock IDs")
require(r'!levelInfo->BonusLevel\s*&&\s*gamestate\.killtotal', LNSPEC, "bonus elevators bypass campaign clearance")
require(r'health<=0\s*&&\s*IWad::CheckGameFilter\("Corridor7"\)\s*&&\s*levelInfo->BonusLevel', WL_AGENT, "bonus health expiration is intercepted before death")
require(r'health\s*=\s*mo->health\s*=\s*mo->SpawnHealth\(\).*?playstate\s*=\s*ex_completed', WL_AGENT, "bonus completion revives and advances the travelling pawn")
require(r'levelShotsFired.*?levelShotsHit', WL_AGENT, "save-backed Corridor 7 hit/miss statistics")
require(r'c7/teleport\s+\{\s+C7DS0001\s+C7AL0001\s+C7PC0001\s+\}', SNDINFO, "Corridor 7 vortex completion sound")
require(r'c7/world/oof1\s+\{\s+C7DS0069.*?c7/world/oof2\s+\{\s+C7DS0070.*?'
        r'\$random\s+misc/do_nothing\s+\{\s*c7/world/oof1\s+c7/world/oof2\s*\}',
        SNDINFO, "unusable walls select the released Corridor 7 impact grunts")
require(r'doors/open\s+\{\s+C7DS0010.*?doors/close\s+\{\s+C7DS0011', SNDINFO,
        "door opening and closing use the native Corridor 7 sound IDs")
# DMA-captured original menu behavior (2026-07-17): moves play 9, backing out
# of a submenu plays 33, and the quit/confirm prompt announces itself with 31.
# Main-menu activation is silent; menu/activate only reaches EC7Wolf-specific
# submenu widgets and clicks like the cursor.
require(r'menu/move1\s+\{\s+C7DS0009.*?menu/move2\s+\{\s+C7DS0009.*?'
        r'menu/activate\s+\{\s+C7DS0009.*?menu/escape\s+\{\s+C7DS0033.*?'
        r'c7/menu/prompt\s+\{\s+C7DS0031',
        SNDINFO, "menu movement, cancellation, and the quit prompt use the DMA-confirmed sounds")
require(r'c7/electric/damage\s+\{\s+C7DS0013', SNDINFO,
        "electrified walls use the released contact sound")
require(r'corridor7WallID\s*==\s*6\s*\|\|\s*spot->corridor7WallID\s*==\s*14.*?DamageC7ElectricField',
        WL_AGENT, "original wall IDs 6 and 14 apply electric-fence damage")
require(r'c7/forcefield/deactivate/53\s+\{\s+C7DS0015.*?'
        r'c7/forcefield/deactivate/73\s+\{\s+C7DS0014.*?'
        r'c7/forcefield/deactivate/81\s+\{\s+C7DS0013', SNDINFO,
        "force-field wall families use their executable- and DMA-confirmed sounds")
require(r'Wall_AnimateRemove.*?new\s+C7AnimatedWall\(spot(?:,\s*activating)?\).*?'
        r'case\s+73:.*?case\s+229:.*?deactivate/73.*?case\s+81:.*?deactivate/81.*?'
        r'PlaySoundLocMapSpot\(sound,\s*spot\)', LNSPEC,
        "force-field shutdown dispatch follows its native wall family")
require(r'c7/dispenser/ammo\s+\{\s+C7DS0026.*?c7/dispenser/visor\s+\{\s+C7DS0074',
        SNDINFO, "ammo and visor dispensers use their released sounds")
if "c7/dispenser/healthstart" in SNDINFO or "c7/dispenser/healthstart" in LNSPEC:
    raise SystemExit("Corridor 7 definition check failed: the original health dispenser is silent")
require(r'c7/chamber/activate\s+\{\s+C7DS0018', SNDINFO,
        "health-chamber activation uses the released sound")
require(r'TryUseC7HealthChamber.*?SD_PlaySound\("c7/chamber/activate"\)', PLAYERPAWN,
        "health-chamber activation dispatches its released sound")
require(r':C7Pushwall\s+play\s+c7/world/pushwall\s+end', SNDSEQ,
        "Corridor 7 secret walls play the executable- and DMA-confirmed sample")
require(r'pushwallsoundsequence\s*=\s*"C7Pushwall"', MAPINFO,
        "Corridor 7 selects its native pushwall sequence")
require(r'c7/world/pushwall\s+\{\s+C7DS0017', SNDINFO,
        "Corridor 7 secret walls use released sample 17")
if re.search(r'^world/pushwall\s+\{\s+C7DS0046', SNDINFO, re.MULTILINE):
    raise SystemExit("Corridor 7 definition check failed: sample 46 belongs to the skull apparition, not pushwalls")
require(r'c7/apparition\s+\{\s+C7DS0046', SNDINFO,
        "the red-skull apparition uses the released ominous sound")
require(r'c7/vortex/ambient\s+\{\s+C7DS0065', SNDINFO,
        "the exit vortex uses its released ambient sound")
require(r'actor\s+C7ExitVortex.*?C738\s+A\s+0\s+A_C7VortexSound.*?'
        r'C738\s+A\s+5.*?C739\s+A\s+5.*?C740\s+A\s+5.*?C741\s+A\s+5',
        MONSTERS, "the exit vortex preserves its released four-frame loop")
require(r'ACTION_FUNCTION\(A_C7VortexSound\).*?!SD_AnySoundPlaying\(\).*?'
        r'PlaySoundLocActor\("c7/vortex/ambient",\s*self\)', WL_AGENT,
        "the vortex waits for a prior digitized sample before restarting its ambience")
require(r'actor\s+C7SkullApparition.*?\+MISSILE.*?C718\s+A\s+10.*?C725\s+A\s+1.*?stop',
        STATICS, "the red-skull apparition uses all eight released animation frames")
if re.search(r'actor\s+C7SkullApparition.*?\+(?:COUNTKILL|ISMONSTER|SHOOTABLE)', STATICS, re.DOTALL):
    raise SystemExit("Corridor 7 definition check failed: the red-skull apparition must not count as an alien")
require(r'c7ApparitionTics\s*<=\s*0x800.*?pr_c7apparition\(\)\s*!=\s*0.*?'
        r'2\*TILEGLOBAL.*?Spawn\(apparitionClass.*?0x300.*?SD_PlaySound\("c7/apparition"\)',
        PLAYERPAWN, "the rare red-skull taunt preserves its native timer, chance, placement, speed, and sound")
require(r'C7SkullApparition.*?T_ExplodeProjectile\(self,\s*NULL\).*?return;.*?DamageActor',
        WL_ACT2, "the red-skull apparition vanishes on contact without damaging or stunning the player")
require(r'C7_SOUND_COUNT\s*=\s*100.*?C7_SAMPLE_RATE\s*=\s*9009|C7_SAMPLE_RATE\s*=\s*9009.*?C7_SOUND_COUNT\s*=\s*100', AUDIO_MUS,
        "AUDIOMUS exposes the 100 original 9009 Hz digitized samples")
require(r'lengths\[pageCount\s*-\s*1\]\s*!=\s*C7_SOUND_COUNT\s*\*\s*8.*?C7DS%04u', AUDIO_MUS,
        "AUDIOMUS validates its sound map and publishes named sound lumps")
require(r'painsound\s+"c7/player/pain"', PLAYER, "Corridor 7 player pain audio")
require(r'deathsound\s+"c7/player/death"', PLAYER,
        "Corridor 7 player death uses released sample 6")
require(r'CheckGameFilter\("Corridor7"\)\)\s*\n\s*PlaySoundLocActor\(pickupsound, toucher\)',
        INVENTORY, "native Corridor 7 pickups do not play inherited Wolf sounds")
if re.search(r'c7/mine/arm|C063\s+A\s+12\s+A_PlaySound', PLAYER):
    raise SystemExit("Corridor 7 definition check failed: native mine arming must remain silent")
# Durations are deliberately not pinned here: they are measured (see the
# C7Weapon comment in player.txt) and belong to the timing check below. What
# this guards is that the reload runs C810..C813 and stops before C814.
require(r'actor\s+C7Shotgun.*?C810\s+A\s+\d+.*?C813\s+A\s+\d+.*?goto\s+Ready',
        PLAYER, "Ithaca reload ends before the C814 Tebazile sprite")
shotgun = re.search(r'actor\s+C7Shotgun(.*?)actor\s+C7PlasmaRifle', PLAYER, re.DOTALL)
if shotgun is None or "C814" in shotgun.group(1):
    raise SystemExit("Corridor 7 definition check failed: Ithaca reload leaks into Tebazile art")
require(r'actor\s+C7ProximityMine.*?Spawn:.*?C067\s+A\s+36.*?Armed:.*?C067\s+A\s+1\s+A_C7MineThink',
        PLAYER, "placed mines use the released floor-mine sprite, not the pickup crate")
require(r'actor\s+C7PlasmaBolt.*?speed\s+30.*?deathsound\s+"c7/teleport"'
        r'.*?Spawn:.*?C706\s+A\s+2\s+bright\s+loop.*?Death:.*?'
        r'C707\s+A\s+4\s+bright\s+A_Explode.*?C708\s+A\s+4\s+bright.*?'
        r'C709\s+A\s+4\s+bright',
        PLAYER, "plasma rifle uses the C706 blue bolt and C707-C709 impact sequence")
plasma_bolt = re.search(r'actor\s+C7PlasmaBolt(.*?)(?=\nactor\s+|\Z)', PLAYER, re.DOTALL)
if plasma_bolt is None or re.search(r'C(?:738|739|740|741|742|743|744|745)', plasma_bolt.group(1)):
    raise SystemExit(
        "Corridor 7 definition check failed: player plasma must not use exit-vortex sprites"
    )
require(r'ACTION_FUNCTION\(A_C7MineThink\).*?32\s*\*\s*\(FRACUNIT\s*/\s*64\).*?self->temp1\s*==\s*0.*?self->temp1\s*=\s*1.*?check->player.*?FL_ISMONSTER.*?DamageActor\(self,\s*self->target,\s*self->health\)',
        WL_AGENT, "mines arm persistently and trigger on nearby players or monsters")
require(r'ACTION_FUNCTION\(A_Explode\).*?attacker\s*=\s*self->target.*?XF_HURTSOURCE.*?target\s*==\s*self->target.*?attacker\s*=\s*self.*?DamageActor\(target,\s*attacker',
        THINGDEF_CODEPTR, "source-hurting explosions bypass player self-friendly-fire suppression")
require(r'ACTION_FUNCTION\(A_C7GunAttack\).*?DepleteAmmo.*?if\(!closest\)\s*return\s+true.*?return\s+true', WL_AGENT, "missed Corridor 7 shots consume ammo and finish their weapon state")
gun_attack = re.search(r'ACTION_FUNCTION\(A_C7GunAttack\)(.*?)ACTION_FUNCTION\(A_C7AlienAlarm\)', WL_AGENT, re.DOTALL)
if gun_attack is None or "PlaySoundLocActor" not in gun_attack.group(1):
    raise SystemExit("Corridor 7 definition check failed: Corridor 7 weapon attacks must play their native sounds")
weapon_sounds = {
    "bayonet": 49, "shotgun": 91, "m16": 22, "m343": 64,
    "dualblaster": 41, "plasma": 78, "assault": 23,
    "disintegrator": 50,
}
for name, sound_id in weapon_sounds.items():
    require(rf'c7/weapon/{name}\s+\{{\s+C7DS{sound_id:04d}', SNDINFO,
            f"native Corridor 7 {name} weapon sound mapping")
    require(rf'attacksound\s+"c7/weapon/{name}"', PLAYER,
            f"Corridor 7 {name} native attack sound assignment")
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
require(r'PrintY\s*=\s*62\s*\+\s*18\*i.*?PrintY\s*=\s*62\s*\+\s*18\*n',
        WL_INTER, "high-score rows and name entry use the executable's unclipped coordinates")
require(r'struct\s+FCorridor7PaletteLump.*?BYTE\s+Palette\[768\].*?'
        r'FCorridor7PaletteLump\(const\s+BYTE\s*\*palette\).*?memcpy\(Cache,\s*Palette,\s*LumpSize\).*?'
        r'new\s+FCorridor7PaletteLump\(palette\)',
        VSWAP, "C7PAL reloads use captured data instead of reopening CORR7CD.EXE")
require(r'CONGRATULATIONS!.*?destroyed the vortex.*?Total floors secured', WL_INTER, "Corridor 7 victory presentation")
require(r'IWad::CheckGameFilter\("Corridor7"\).*?HIGH SCORES', WL_INTER, "Corridor 7 high scores avoid Wolf-only art")
require(r'LevelBonus\s*==\s*-1.*?ForceTally.*?!\(IWad::CheckGameFilter\("Corridor7"\)\s*&&\s*levelInfo->BonusLevel\)', WL_INTER, "bonus floors stay out of forty-floor victory averages")
require(r'LatchString\(10,\s*16,\s*2.*?LatchNumber\(30,\s*16,\s*7.*?LatchNumber\(296,\s*16,\s*2', WOLF_SBAR, "released HUD number placement")
require(r'DrawC7Gauge\(97,\s*172,.*?health\s*<\s*32\s*\?\s*80\s*:\s*128\).*?DrawC7Gauge\(97,\s*191,.*?5,\s*56\).*?DrawC7Gauge\(200,\s*172,.*?5,\s*104\).*?DrawC7Gauge\(200,\s*190,.*?5,\s*104\).*?DrawC7Gauge\(149,\s*193,.*?3,\s*56\)', WOLF_SBAR, "released native-index HUD gauge ramps")
require(r'C7G0019.*?C7G0020.*?C7G0021.*?C7G0018.*?256\+\(slot\+\+\)\*8,\s*176', WOLF_SBAR, "released three-slot HUD item graphics")
require(r'component\s*<<\s*2.*?component\s*>>\s*4', VSWAP, "Corridor 7 VGA DAC palette expansion")
require(r'PSPR_CORRIDOR7.*?TopOffset\s*=\s*-54.*?xScale\s*=\s*4\*FRACUNIT/5', WOLF_SHAPE, "native Corridor 7 weapon scale and anchor")
require(r'actor\s+C7M16.*?Ready:\s*C761\s+A\s+1\s+A_WeaponReady', PLAYER, "M-16 uses its released stationary frame")
weapon_blocks = {}
for weapon in (
	"C7Bayonet",
    "C7Shotgun",
    "C7M16",
    "C7M343",
    "C7DualBlaster",
    "C7PlasmaRifle",
    "C7AssaultCannon",
    "C7Disintegrator",
):
    block = re.search(
        rf'actor\s+{weapon}\s*:.*?\{{(.*?)(?=\nactor\s+|\Z)',
        PLAYER,
        re.DOTALL,
    )
    if block is None:
        raise SystemExit(f"Corridor 7 definition check failed: missing {weapon}")
    weapon_blocks[weapon] = block.group(1)
    if "+WEAPON.NOAUTOFIRE" in block.group(1):
        raise SystemExit(
            f"Corridor 7 definition check failed: weapon {weapon} must support held fire"
        )
    if "A_ReFire" not in block.group(1):
        raise SystemExit(
            f"Corridor 7 definition check failed: weapon {weapon} has no held-fire branch"
        )
require(r'actor\s+C7Bayonet.*?Fire:\s*Hold:.*?C746\s+A\s+\d+.*?'
        r'C748\s+A\s+\d+\s+bright\s+A_CustomPunch.*?C749\s+A\s+\d+\s*'
        r'TNT1\s+A\s+0\s+A_ReFire', PLAYER,
        "Taser held fire repeats its complete native attack sequence")
# These check firing SEQUENCE, not duration. Durations are measured and are
# asserted once, below, so a re-measurement does not have to touch every one.
require(r'actor\s+C7M16.*?C756\s+A\s+\d+\s+bright\s+A_C7GunAttack\(2\).*?'
        r'C757\s+A\s+\d+\s+TNT1\s+A\s+0\s+A_ReFire', PLAYER,
        "M-24 held fire draws both released jiggle frames before refiring")
require(r'actor\s+C7M343.*?Fire:\s*Hold:.*?C762\s+A\s+\d+.*?C765\s+A\s+\d+\s*'
        r'TNT1\s+A\s+0\s+A_ReFire', PLAYER,
        "M-343 held bursts replay the muzzle flash and complete barrel cycle")
for weapon, action_frame in {
    "C7DualBlaster": "C773",
    "C7PlasmaRifle": "C781",
    "C7AssaultCannon": "C797",
}.items():
    require(rf'actor\s+{weapon}.*?{action_frame}\s+A\s+\d+(?:\s+bright)?\s*'
            r'TNT1\s+A\s+0\s+A_ReFire', PLAYER,
            f"{weapon} displays its final firing frame before held refire")
require(r'actor\s+C7Disintegrator.*?Fire:.*?C802\s+A\s+\d+.*?C803\s+A\s+\d+.*?'
        r'Hold:.*?C804\s+A\s+\d+\s+bright\s+A_C7GunAttack\(7\).*?'
        r'C805\s+A\s+\d+\s+TNT1\s+A\s+0\s+A_ReFire', PLAYER,
        "Disintegrator holds on its final two firing frames without showing its movement pose")
require(r'actor\s+C7Shotgun.*?Fire:\s*Hold:.*?C810\s+A\s+\d+.*?'
        r'C813\s+A\s+\d+\s+TNT1\s+A\s+0\s+A_ReFire', PLAYER,
        "Ithaca held fire completes every pump frame before repeating")

# Measured from a 70fps capture of the released game holding fire: every weapon
# animation frame dwells exactly 6 tics. DECORATE is authored in Doom's 35Hz and
# doubled at parse time, so that is 3 here. Copying the released 70Hz table
# verbatim -- which these states used to do -- runs the guns at half speed.
# Duration 1 is A_WeaponReady's poll loop, not an animation frame.
# Every duration maps to a released 70Hz tic count: 1 is the A_WeaponReady poll
# loop, 3 is the measured 6-tic firing frame, 6 is the shotgun's 12-tic pump, and
# 10 is the disintegrator/plasma 20-tic peak discharge.
_ALLOWED_WEAPON_DURATIONS = {1: "poll", 3: "6-tic firing frame", 6: "12-tic pump",
                             10: "20-tic peak discharge"}
_weapon_block = re.search(r'actor\s+C7Weapon\s*:(.*)\Z', PLAYER, re.DOTALL).group(1)
_base_frames = 0
for _actor in re.finditer(r'actor\s+(C7\w+)\s*:\s*C7Weapon(.*?)(?=\nactor\s|\Z)',
                          _weapon_block, re.DOTALL):
    _name, _body = _actor.group(1), _actor.group(2)
    for _frame, _dur in re.findall(r'\n\s+(C\d{3}) [A-Z] (\d+)', _body):
        if int(_dur) not in _ALLOWED_WEAPON_DURATIONS:
            raise SystemExit(
                "Corridor 7 definition check failed: %s frame %s has duration %s; "
                "weapon frames are measured, and %s is not one of %s"
                % (_name, _frame, _dur, _dur, sorted(_ALLOWED_WEAPON_DURATIONS)))
        if int(_dur) == 3:
            _base_frames += 1
# A regression that copies the released 70Hz table verbatim shows up as 6 across
# the board, which leaves no frames at the measured base at all.
if _base_frames < 24:
    raise SystemExit(
        "Corridor 7 definition check failed: only %d weapon frames use the measured "
        "3-tic base; the released tables are 6 tics per frame, halved to 3 here"
        % _base_frames)
for weapon, movement_frame in {
    "C7Shotgun": "C790",
    "C7M16": "C758",
    "C7M343": "C766",
    "C7DualBlaster": "C774",
    "C7PlasmaRifle": "C782",
    "C7AssaultCannon": "C798",
    "C7Disintegrator": "C806",
}.items():
    if movement_frame in weapon_blocks[weapon]:
        raise SystemExit(
            f"Corridor 7 definition check failed: {weapon} firing sequence displays movement frame {movement_frame}"
        )
if "C750" in weapon_blocks["C7Bayonet"]:
    raise SystemExit("Corridor 7 definition check failed: Taser firing displays movement frame C750")
# The sway table still gates on a ready frame; C7ApplyWalkPose returns early for
# anything else rather than nesting the body in an if(readyFrame) block.
require(r'0,\s*1,\s*2,\s*3,\s*4,\s*3,\s*2,\s*1,\s*0,\s*-1,\s*-2,\s*-3,\s*-4,\s*-3,\s*-2,\s*-1.*?if\(!readyFrame\)\s*\n\s*return;.*?xoffset\s*\+=\s*corridor7X\[phase\]', WL_DRAW, "released 16-step Corridor 7 stationary-frame weapon bob")
require(r'readyBase\+\(\(phase&4\)\s*\?\s*4\s*:\s*7\).*?spriteOverride\s*=\s*R_GetSprite',
        WL_DRAW, "weapon bob alternates only the moving and stationary pages")
if "corridor7Poses" in WL_DRAW:
    raise SystemExit("Corridor 7 definition check failed: weapon bob must not insert intermediate pose pages")
if "corridor7Frame" in WL_DRAW:
    raise SystemExit("Corridor 7 definition check failed: weapon bob must not copy live Frames")
require(r'C7CycleSpriteColor.*?color\s*>=\s*208\s*&&\s*color\s*<=\s*239.*?'
        r'gamestate\.TimeCount\s*>>\s*C7_RAMP_CYCLE_SHIFT.*?C7ShadePlayerSpriteColor.*?'
        r'color\s*>=\s*208\s*&&\s*color\s*<=\s*239.*?C7CycleSpriteColor\(color\).*?'
        r'luminous\s*\?\s*NormalLight\.Maps\[color\]\s*:\s*colormap\[color\].*?'
        r'R_DrawPlayerSprite.*?C7ShadePlayerSpriteColor\(src\[y>>FRACBITS\],\s*colormap\)',
        R_SPRITES, "weapon instrumentation cycles at full brightness while the gun remains shaded")
require(r'CheckGameFilter\("Corridor7"\).*?virtualEdgeRow.*?80.*?band\s*=\s*virtualEdgeRow/3.*?'
        r'extraLight\s*=\s*MAX\(0,\s*r_extralight\).*?litBand.*?extraLight/8.*?'
        r'virtualX.*?320.*?virtualX>>2.*?virtualEdgeRow%3\s*==\s*1.*?band&1.*?==\s*0',
        FLOOR_CEILING, "Corridor 7 planes reproduce the native three-row/four-column VGA shade pattern")
if "bayer4" in FLOOR_CEILING:
    raise SystemExit("Corridor 7 definition check failed: floor/ceiling shading must not use resolution-dependent Bayer dithering")
if len(re.findall(r'bonuslevel\s*=\s*true', MAPINFO, re.IGNORECASE)) != 6:
    raise SystemExit("Corridor 7 definition check failed: all six bonus maps must use bonus-level rules")
require(r'map\s+"MAP40".*?forcetally\s*=\s*true', MAPINFO, "MAP40 must tally before victory")
require(r"29,\s*18,\s*20,\s*9,\s*2,\s*14,\s*7,\s*8", WL_PLAY, "released music selector table")
require(r'^\s*\{300,\s*C7Semaj,', XLAT, "object 300 Semaj mapping")
require(r'"AILOA1".*?"AILOA8"', CO7MAP, "Ailoprobe directional sprite set")
require(r'"EITKA1".*?"EITKA8"', CO7MAP, "Eitak directional sprite set")
require(r"actor\s+C7Semaj\s*:.*?A_MeleeAttack", MONSTERS, "Semaj melee-only attack")
require(r'actor\s+C7Solrac\s*:.*?A_CustomMissile\("C7BossEnergyBolt"\)', MONSTERS, "Solrac energy projectile")
require(r'actor\s+C7Eniram\s*:.*?Spawn:\s*C665.*?Missile:.*?C669.*?C672.*?A_WolfAttack.*?Pain:.*?C683.*?Death:.*?C684.*?C689',
        MONSTERS, "ordinary Eniram uses its complete C665-C689 cloaking state family")
require(r'actor\s+C7EniramBoss\s*:.*?Spawn:\s*C653.*?Missile:.*?C657.*?C658.*?A_CustomMissile.*?Death:.*?C659.*?C664',
        MONSTERS, "golden-horned Eniram Boss uses C653-C664 and never uses cloak frames")
require(r'actor\s+C7Rodex\s*:.*?Missile:.*?C233.*?C236.*?Pain:.*?C225.*?C226',
        MONSTERS, "Rodex attack no longer reuses its hurt frames")
require(r'A_PlaySound\("c7/monster/attack/class20"\).*?A_CustomMissile\("C7BossEnergyBolt"\)',
        MONSTERS, "Solrac plays its released class-17 projectile sound")
require(r'actor\s+C7Tymok.*?activesound\s+"c7/monster/active/class25".*?'
        r'A_PlaySound\("c7/weapon/plasma"\).*?A_CustomMissile\("C7BossPlasmaBolt"\).*?'
        r'A_PlaySound\("c7/monster/attack/class25"\)', MONSTERS,
        "the purple boss preserves its controlled-trace active and two attack sounds")
require(r'^\s*\{196,\s*C7EniramBoss,.*?actor\s+C7EniramBoss.*?'
		r'activesound\s+"c7/monster/active/class21".*?C653.*?C664',
        XLAT + MONSTERS,
        "object 196 uses the golden-horned C653 Eniram Boss and class-21 audio")
for object_id, actor in {
	142: "C7Eniram", 179: "C7Tymok", 214: "C7Solrac",
	224: "C7Tenaj", 232: "C7Mechanoid", 270: "C7Ttocs",
	278: "C7Otrebor", 300: "C7Semaj", 324: "C7Nerraw",
	328: "C7Eitak", 336: "C7Tebazile",
}.items():
	require(rf'^\s*\{{{object_id},\s*{actor},', XLAT,
			f"native object {object_id} maps to {actor}")
require(r'c7/monster/active/class6\s+\{\s+C7DS0055.*?'
        r'c7/monster/active/class13\s+\{\s+C7DS0057.*?'
        r'c7/monster/active/class20\s+\{\s+C7DS0068.*?'
        r'c7/monster/active/class21\s+\{\s+C7DS0068.*?'
        r'c7/monster/active/class25\s+\{\s+C7DS0021', SNDINFO,
        "original class-specific alien active sounds")
require(r'CheckGameFilter\("Corridor7"\).*?pr_chase\(7\)\s*==\s*0.*?'
        r'class13Active.*?pr_chase\(9\)\s*==\s*0', WL_ACT2,
        "original active-sound random cadence")
if '"c7/monster/attack"' in MONSTERS or '"c7/monster/death"' in MONSTERS:
    raise SystemExit(
        "Corridor 7 definition check failed: aliens must not use guessed generic combat sounds"
    )
require(r'A_FireCustomMissile.*?C7PlasmaBolt.*?c7MuzzleFlashTics\s*=\s*5',
        WL_AGENT, "the player plasma projectile has original muzzle lighting")
require(r'action\s+native\s+A_C7AlienAlarm', NATIVE_ACTORS,
        "the Ailoprobe alarm action is registered")
require(r'P_AlertCorridor7MonstersNear.*?12\*TILEGLOBAL', WL_AGENT,
		"ordinary alien alarms wake a local group instead of the whole floor")
require(r'TileBlocksSight.*?CheckGameFilter\("Corridor7"\).*?return\s+true.*?'
		r'else if \(TileBlocksSight\(spot\)\)', WL_STATE,
		"Corridor 7 glass remains opaque to alien line-of-sight")
require(r'C7VisorCanSeeActor.*?C7Eniram.*?infrared',
		R_SPRITES, "infrared reveals cloaked Eniram actors")
# A controlled DOSBox run shows the decorative statics (C010 posts, C011
# rods, C012 strands) plainly in normal visor mode, so those classes may not
# be gated on the visor. The strategy guide's "Infrared Invisible Barrier"
# is the laser barrier static pair (map objects 28/84 = C7Static005 and
# C7Static061): walk-through, drawn only under infrared, and 10 points of
# contact damage on a cooldown.
for cls in ("C7DamageField", "C7Static011", "C7Static009"):
	if re.search(r'C7VisorCanSeeActor.*?FindClass\("%s"\).*?return\s+infrared' % cls, R_SPRITES, re.S):
		raise SystemExit(
			"Corridor 7 definition check failed: %s statics must remain visible in every visor mode" % cls)
WL_DRAW = (ROOT / "src/wl_draw.cpp").read_text()
if re.search(r'Corridor7IsLaserWall|C7LaserBarrierHidden', WL_DRAW):
	raise SystemExit(
		"Corridor 7 definition check failed: masked walls must not be visor-gated (the laser barrier is the object 28/84 static pair)")
require(r'Corridor7IsLaserBarrierActor.*?FindClass\("C7Static005"\).*?FindClass\("C7Static061"\)',
		R_SPRITES, "the laser barrier is the object 28/84 static pair")
require(r'C7VisorCanSeeActor.*?Corridor7IsLaserBarrierActor\(actor\)\s*\)\s*return\s+infrared',
		R_SPRITES, "the laser barrier statics render only under the infrared visor")
# The barrier's energy is the artwork plus the DAC, not a drawing special case.
# C006 and C062 are painted entirely in indices 232-239 -- one of the four ramps
# the released game rotates -- which are black in the base palette and a
# 32..255 red sweep under infrared. Reintroducing a per-texel override here
# throws that away: the previous hashed dissolve replaced the sprite with
# speckled white and lost both the travelling sweep along C006's rods and the
# ring's shape. The ordinary sprite path already cycles and full-brights the
# ramp, so there must be nothing barrier-specific left in either scaler.
for name in ("C7LaserDissolveLit", "laserColor", "laserBarrier"):
	if name in R_SPRITES:
		raise SystemExit(
			"Corridor 7 definition check failed: %s -- the laser barrier must draw as an "
			"ordinary sprite and take its animation from the 232-239 DAC ramp" % name)
if "c7LaserLit" in (ROOT / "src/render/opengl/r_glworld.cpp").read_text():
	raise SystemExit(
		"Corridor 7 definition check failed: the GL shader must not special-case the laser barrier")
require(r'luminous\s*=\s*color == GPalette\.Remap\[15\].*?GPalette\.Remap\[208\].*?GPalette\.Remap\[239\].*?C7CycleSpriteColor',
		R_SPRITES, "world sprites cycle and full-bright the four rotating ramps, which is what animates the barrier")
for cls in ("C7Static005", "C7Static061"):
	if re.search(r'actor\s+%s\s*\{[^}]*?\+SOLID' % cls, STATICS, re.S):
		raise SystemExit(
			"Corridor 7 definition check failed: %s must not block movement (the released game lets the player walk through the beams)" % cls)
	require(r'actor\s+%s\s*\{[^}]*?radius\s+32' % cls, STATICS,
			"the laser barrier %s keeps its touch-zone radius" % cls)
require(r'DamageC7LaserBarrier.*?TakeDamage\(10,\s*NULL\)', WL_AGENT,
		"beam barrier contact deals the executable's 10 points on a cooldown")
require(r'Corridor7IsLaserBarrierActor\(check\).*?DamageC7LaserBarrier', WL_AGENT,
		"pressing into the beam barrier zaps the player")
# ...and standing still in one keeps zapping. TryMove is only reached from
# Thrust, which only runs while an input is moving the player, so the movement
# path cannot be the whole story: a player who stepped in and stopped took one
# zap and then nothing, and one warped in took none at all. Both paths funnel
# through DamageC7LaserBarrier so its cooldown still sets the rate.
require(r'void C7TouchLaserBarriers.*?Corridor7IsLaserBarrierActor\(check\).*?'
		r'check->radius \+ pawn->radius.*?DamageC7LaserBarrier\(pawn\)', WL_AGENT,
		"the beam barrier retests overlap independently of movement")
require(r'C7TouchLaserBarriers\(this\);', PLAYERPAWN,
		"the player tests for beam-barrier contact every tic, not only when moving")
require(r'"Drop Mine".*?"Visor Mode"', WL_PLAY, "configuration-safe Corridor 7 control labels")
require(r'const fixed distance = 40 \* \(FRACUNIT / 64\);', PLAYERPAWN,
        "proximity-mine drop distance uses Corridor 7 world-unit scaling")
require(r'IsValidTileCoordinate\(mineX >> FRACBITS,\s*mineY >> FRACBITS, 0\)',
        PLAYERPAWN, "proximity-mine spawn coordinates are map-bounds checked")

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
    "C7Tenaj": "50, 50, 150, 300",
    "C7Bandor": "25, 25, 50, 100",
    "C7Rodex": "25, 25, 50, 100",
    "C7Ttocs": "50, 50, 150, 300",
    "C7Eniram": "50, 50, 200, 500",
    "C7Otrebor": "50, 50, 200, 300",
    "C7Semaj": "25, 25, 50, 100",
    "C7Nerraw": "25, 25, 50, 100",
    "C7Eitak": "75, 75, 225, 450",
    "C7EniramBoss": "1000, 1500, 2000, 4000",
    "C7Tymok": "1000, 1500, 2000, 4000",
    "C7Mechanoid": "500, 500, 1000, 1500",
    "C7Solrac": "1000, 1500, 3000, 5000",
    "C7Tebazile": "5000, 6000, 7000, 9000",
}.items():
    require(
        rf"actor\s+{actor}\s*:.*?\{{.*?health\s+{re.escape(health)}",
        MONSTERS,
        f"{actor} health table",
    )

require(r'actor\s+C7Tebazile.*?TransformEniram:.*?C822.*?C827.*?'
		r'TransformTymok:.*?C828.*?C833.*?TransformSolrac:.*?C834.*?C839.*?'
		r'TransformFinal:.*?C840.*?C845.*?Death:.*?C846.*?C857',
		MONSTERS, "Tebazile plays all native transformation and final-death frames")
require(r'actor\s+C7Mechanoid.*?C690.*?A_PlaySound.*?C692.*?A_PlaySound.*?'
		r'Missile:.*?C694.*?C696.*?A_WolfAttack.*?C697.*?C696.*?A_WolfAttack',
		MONSTERS, "Mechanoid has booming steps and two range-falling attacks")

print("Corridor 7 definition checks passed")
