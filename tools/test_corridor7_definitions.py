#!/usr/bin/env python3
"""Validate the released Corridor 7 pickup and weapon-definition contract."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
XLAT = (ROOT / "wadsrc/static/xlat/corridor7.txt").read_text()
PLAYER = (ROOT / "wadsrc/static/actors/corridor7/player.txt").read_text()
STATICS = (ROOT / "wadsrc/static/actors/corridor7/statics.txt").read_text()


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

require(r"actor\s+C7Static003\s*\{", STATICS, "object 26 must not be a key")
require(r'player\.startitem\s+"C7Bayonet"', PLAYER, "Bayonet starting weapon")
require(r'player\.startitem\s+"C7M16"', PLAYER, "M-16 starting weapon")
require(r'player\.startitem\s+"C7Bullets",\s*100', PLAYER, "100 starting bullets")
require(r"actor\s+C7Bullets\s*:\s*Ammo.*?inventory\.maxamount\s+200", PLAYER, "200 bullet maximum")

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

print("Corridor 7 definition checks passed")
