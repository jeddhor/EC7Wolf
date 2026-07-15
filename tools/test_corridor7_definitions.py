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
require(r'player\.startitem\s+"C7Bayonet"', PLAYER, "Bayonet starting weapon")
require(r'player\.startitem\s+"C7M16"', PLAYER, "M-16 starting weapon")
require(r'player\.startitem\s+"C7Bullets",\s*100', PLAYER, "100 starting bullets")
require(r"actor\s+C7Bullets\s*:\s*Ammo.*?inventory\.maxamount\s+200", PLAYER, "200 bullet maximum")
require(r"actor\s+C7EnergyCapacity\s*:\s*Ammo.*?inventory\.amount\s+100", PLAYER, "alien energy capacity")
require(r"ConsumeC7AlienCharge\(self,\s*33,\s*4\)", (ROOT / "src/wl_agent.cpp").read_text(), "plasma 33/4 charge model")
require(r"clearance\[4\]\s*=\s*\{\s*10,\s*75,\s*100,\s*100\s*\}", LNSPEC, "rank clearance quotas")
require(r'args\[0\]\s*==\s*1\s*&&\s*gamestate\.killtotal', LNSPEC, "clearance applies only to elevator exits")
require(r'skill\s*=\s*MIN<unsigned int>\(gamestate\.difficulty->SpawnFilter,\s*3\)', LNSPEC, "zero-based rank clearance index")
require(r'tile\s+105\s*\{.*?sighttransparent\s*=\s*true', XLAT, "wall 105 is sight-transparent but solid")
require(r'tile\s+107\s*\{.*?sighttransparent\s*=\s*true', XLAT, "wall 107 is sight-transparent but solid")
require(r'bool\s+sightTransparent', GAMEMAP_H, "sight-transparent solid wall property")
require(r'else if \(!spot->tile->sightTransparent\)', WL_STATE, "sight checks pass through Corridor 7 screens")
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
