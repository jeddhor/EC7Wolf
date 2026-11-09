"""Runtime regression for issue 14; invoked by test_corridor7_alien_counter.sh."""
from dataclasses import replace
from pathlib import Path
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib

build, data, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "editor"))
from ec7edit_core.archive import read_archive, encode_archive
from ec7edit_core.planes import MapPlanes

lab = work / "lab"
lab.mkdir()
(work / "saves").mkdir()
for path in [*data.glob("*.CO7"), data / "CORR7CD.EXE"]:
    shutil.copyfile(path, lab / path.name)
source = list(read_archive(data / "MAPTEMP.CO7").records)
env = dict(os.environ, SDL_AUDIODRIVER="dummy", SDL_VIDEODRIVER="x11")


def fixture(weapon="C7M343", base="C7MorphChair", health=1, keepers=2,
            corpse=True):
    records = source.copy()
    for level in (0, 1):
        walls, things = [1] * 4096, [18] * 4096
        for y in range(9, 12):
            for x in range(4, 30):
                walls[y * 64 + x] = 256
        # An ordinary quota-gated elevator behind the player; live guards
        # behind the partition prevent completion after the visible kill.
        walls[10 * 64 + 3] = 63
        for y in range(9, 12):
            walls[y * 64 + 15] = 1
        things[10 * 64 + 4] = 20
        if level == 0:
            things[10 * 64 + 6] = 108
            for i in range(keepers):
                things[(9 + i // 10) * 64 + 18 + i % 10] = 112
        records[level] = replace(records[level], planes=MapPlanes(
            64, 64, (tuple(walls), tuple(things), (0,) * 4096)))
    (lab / "MAPTEMP.CO7").write_bytes(encode_archive(records))
    with zipfile.ZipFile(build / "ec7wolf.pk3") as src, zipfile.ZipFile(lab / "ec7wolf.pk3", "w") as dst:
        for info in src.infolist():
            blob = src.read(info)
            if info.filename == "actors/corridor7/player.txt":
                blob = blob.replace(b'player.startitem "C7Bayonet"', b'')
                blob = blob.replace(b'player.startitem "C7M16"', f'player.startitem "{weapon}"'.encode())
            if info.filename == "actors/corridor7/monsters.txt":
                blob += f'''
actor C7CounterTarget : {base}
{{
 health {health}
 speed 0, 0
 points 3217
 dropitem "C7CounterDrop", 256
 {'' if corpse else 'states { Death: TNT1 A 0 stop }'}
}}
actor C7CounterGuard : C7ProbeEye
{{
 health 100000
 states {{ Spawn: PROB A -1 stop }}
}}
actor C7CounterDrop
{{
 +ISMONSTER
 states {{ Spawn: C059 A -1 stop }}
}}
'''.encode()
            if info.filename == "xlat/corridor7.txt":
                blob = blob.replace(b"{108, C7OrganicEye,", b"{108, C7CounterTarget,")
                blob = blob.replace(b"{112, C7OrganicEye,", b"{112, C7CounterGuard,")
            if info.filename == "mapinfo/corridor7.txt":
                blob = re.sub(rb'(map "MAP01"[^\n]*\n\{)', rb'\1\n nointermission', blob)
            dst.writestr(info, blob)


def run(label, extra=(), skill=4, level="MAP01", tics=100, fire=True):
    args = [str(build / "ec7wolf"), "--data", "CO7", "--nowait", "--no-upscale",
            "--vid-renderer", "software", "--res", "320", "200", "--tedlevel", level,
            "--skill", str(skill), "--config", str(work / (label + ".cfg")),
            "--savedir", str(work / "saves"), "--capture-rngseed", "1",
            "--capture-killstats", "--capture-actors", str(work / (label + ".actors")),
            "--capture-checksum", str(work / (label + ".crc")), "--capture-maxtics", str(tics)]
    if fire:
        args += ["--capture-hold-button", "attack", "20", "1"]
    args += list(extra)
    with (work / (label + ".log")).open("w") as log:
        subprocess.run(args, cwd=lab, env=env, stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=45)
    text = (work / (label + ".log")).read_text()
    stats = [dict((k, int(v)) for k, v in re.findall(r"(\w+)=(-?\d+)", line))
             for line in text.splitlines() if line.startswith("killstats tic=")]
    assert stats, (label, text[-2000:])
    actors = [line.split() for line in (work / (label + ".actors")).read_text().splitlines()
              if line and not line.startswith("#")]
    return text, stats, actors


def one_death(label, result, total):
    _, stats, actors = result
    assert stats[-1]["killed"] == 1 and stats[-1]["living"] == total - 1, (label, stats)
    assert stats[-1]["total"] == total and stats[-1]["score"] == 3217, (label, stats)
    last = max(int(row[0]) for row in actors)
    drops = sum(row[1] == "C7CounterDrop" for row in actors if int(row[0]) == last)
    assert drops == 1, (label, "repeated/missing drop", drops)


# Exercise the shipped firing states and real damage action for every disguise
# and an ordinary alien, including a target that survives the first hit.
for weapon in ("C7M343", "C7AssaultCannon"):
    for base in ("C7MorphChair", "C7MorphFile", "C7MorphPlant", "C7MorphBarrel", "C7ProbeEye"):
        for health in (1, 250):
            label = f"{weapon}-{base}-{health}"
            fixture(weapon, base, health)
            one_death(label, run(label), 3)
        print("PASS", weapon, base, "one kill, score award and drop per lethal burst", flush=True)

# Single-hit, projectile, and explosive paths still kill normally.
for weapon in ("C7M16", "C7Shotgun", "C7PlasmaRifle"):
    fixture(weapon)
    one_death(weapon, run(weapon, tics=200), 3)
    print("PASS", weapon, "control", flush=True)
fixture()
one_death("mine", run("mine", ("--capture-mine-at", "6", "10", "20"), fire=False, tics=180), 3)
print("PASS mine blast control", flush=True)

# Repeated runs must consume deterministic weapon/world RNG identically.
fixture()
run("repeat-a")
run("repeat-b")
assert (work / "repeat-a.crc").read_bytes() == (work / "repeat-b.crc").read_bytes()
print("PASS repeatable world checksums", flush=True)

# Mutate only the kill counter in a valid save. The archive prefix is checked
# before editing; this reproduces both a premature 100% and a subtler overcount
# below the total, without shipping game data or a prebuilt legacy executable.
def corrupt_counter(source_name, dest_name, kills):
    raw_png = (work / "saves" / source_name).read_bytes()
    output, p = bytearray(raw_png[:8]), 8
    while p < len(raw_png):
        size = struct.unpack_from(">I", raw_png, p)[0]
        tag, payload = raw_png[p + 4:p + 8], raw_png[p + 8:p + 8 + size]
        if tag == b"snAp":
            assert payload[:4] == b"FLZL"
            compressed, expanded = struct.unpack_from(">II", payload, 4)
            raw = bytearray(zlib.decompress(payload[12:]) if compressed else payload[12:])
            assert len(raw) == expanded
            assert raw[2:12] == b"\x01\x09C7Player" and struct.unpack_from(">I", raw, 12)[0] == 1
            assert struct.unpack_from(">h", raw, 20)[0] == 1
            struct.pack_into(">h", raw, 20, kills)
            packed = zlib.compress(raw)
            payload = b"FLZL" + struct.pack(">II", len(packed), len(raw)) + packed
        output += struct.pack(">I", len(payload)) + tag + payload
        output += struct.pack(">I", zlib.crc32(tag + payload))
        p += size + 12
    (work / "saves" / dest_name).write_bytes(output)


for keepers in (2, 9):
    fixture(keepers=keepers)
    run("save", ("--capture-save", "60", "healthy.ecs"))
    text, stats, _ = run("healthy-load", ("--capture-load", "10", "healthy.ecs"), fire=False)
    assert "Repaired Corridor 7 alien count" not in text and stats[-1]["killed"] == 1
    corrupt_counter("healthy.ecs", "corrupt.ecs", 3)
    text, stats, _ = run("corrupt-load", ("--capture-load", "10", "corrupt.ecs",
        "--capture-place", "170", "4.5", "10.5", "180", "--capture-use", "175", "4"),
        fire=False, tics=200)
    assert "Repaired Corridor 7 alien count: 3 -> 1" in text, text[-2000:]
    assert stats[-1]["killed"] == 1 and stats[-1]["living"] == keepers
    assert stats[-1]["clearance"] == 0 and stats[-1]["secured"] == 0
    assert "Elevator clearance denied" in text and "MAP02 - " not in text, text[-2000:]
    print("PASS save repair and real elevator denial, total", keepers + 1, flush=True)

fixture(corpse=False)
run("removed-corpse", ("--capture-save", "60", "removed.ecs"))
corrupt_counter("removed.ecs", "removed-corrupt.ecs", 3)
text, stats, _ = run("unsupported-load", ("--capture-load", "10", "removed-corrupt.ecs"), fire=False)
assert "Repaired Corridor 7 alien count" not in text and stats[-1]["killed"] == 3
print("PASS corpse-removing mod skips reconciliation", flush=True)

for skill in range(1, 6):
    fixture()
    text, stats, _ = run(f"quota-{skill}", ("--capture-place", "65", "4.5", "10.5", "180",
        "--capture-use", "70", "4"), skill=skill, tics=120)
    # Retain the existing rank thresholds: the two easiest ranks need 10%,
    # Captain 75%, and Major/President 100%.
    if skill <= 2:
        assert "MAP02 - " in text, text[-2000:]
    else:
        assert "Elevator clearance denied" in text and "MAP02 - " not in text
    fixture(keepers=0)
    text, stats, _ = run(f"secured-{skill}", ("--capture-place", "65", "4.5", "10.5", "180",
        "--capture-use", "70", "4"), skill=skill, tics=120)
    assert any(r["killed"] == r["total"] == 1 and r["secured"] for r in stats), stats
    assert "MAP02 - " in text and stats[-1]["killed"] == stats[-1]["total"] == 0
    print("PASS rank", skill, "clearance and 100% completion, next-floor counters reset", flush=True)

# Retail floors must include disguised Bandors in the original population and
# retain their exact counters across a healthy save/load, without fixture actors.
shutil.copyfile(data / "MAPTEMP.CO7", lab / "MAPTEMP.CO7")
shutil.copyfile(build / "ec7wolf.pk3", lab / "ec7wolf.pk3")
for level in ("MAP05", "MAP06"):
    text, stats, actors = run(level, ("--capture-save", "10", "floor.ecs",
        "--capture-load", "30", "floor.ecs"), level=level, tics=60, fire=False)
    assert all(r["killed"] == 0 and r["living"] == r["total"] for r in stats), stats
    assert any(row[1].startswith("C7Morph") for row in actors)
    assert "Repaired Corridor 7 alien count" not in text
    print("PASS retail", level, "Major population and save/load", stats[-1]["total"], flush=True)
