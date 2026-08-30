#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Gallery half of `tools/c7assets.py`. Not runnable on its own.

`tools/c7assets.py` is a single file on purpose: its whole promise is that you
drop it beside the game data and run it, with nothing to install. That promise
used to be paid for with a second copy of every decoder, which is how two
implementations of the same format end up disagreeing about a bug fix.

So the decoders live once, in `ec7edit_core`, and the shipped single file is
*generated* by `build_c7assets.py`, which inlines them ahead of this template.
Edit this file or the core modules; never edit `tools/c7assets.py`, which is
overwritten and whose contents are gated.

The marker below is where the inlined modules land.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import zipfile
import zlib
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# EC7EDIT-INLINE


# --------------------------------------------------------------------------
# Adapters: the shapes this gallery grew up with, over the canonical codecs
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GameMap:
    """The flat view of a map this gallery was written against."""

    index: int
    name: str
    width: int
    height: int
    planes: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]


def parse_maps(data: bytes) -> list[GameMap]:
    """Read MAPTEMP through the production codec, then flatten it."""
    return [
        GameMap(
            record.number - 1,
            record.name.text,
            record.width,
            record.height,
            record.planes.planes,
        )
        for record in parse_archive(data)
    ]


def parse_actors(pk3: zipfile.ZipFile) -> dict[str, ActorInfo]:
    """DECORATE actors from an already-open pk3, for the browser's sprite join."""
    actors: dict[str, ActorInfo] = {}
    for source in SOURCES:
        try:
            raw = pk3.read(f"actors/corridor7/{source}.txt")
        except KeyError:
            continue
        actors.update(parse_decorate(raw.decode("latin-1"), source))
    return resolve_roles(actors)


# Curated knowledge base (from the Technical & Strategy Compendium + repo docs)
# --------------------------------------------------------------------------

ENEMY_MANUAL = [
    # name, type, health, damage, levels, score, notes
    ("Alioprobe", "Guard / sentry", "25", "Low", "20-39", "100",
     "Slow alarm unit, dangerous in packs; clear quickly before it draws traffic."),
    ("Animated Probe", "Centurion", "100", "Low", "1-40", "400",
     "Extremely fast, sound-reactive, sometimes ambush placed; electronic whine."),
    ("Bandor", "Guard / morpher", "50", "High", "5-39", "500",
     "Disguises as furniture/plants; morph sound; other Bandors may rush a kill site."),
    ("Eitak", "Guard", "100", "Medium", "30-40", "800",
     "Primary alien-world guard; accurate in groups; use sustained fire and open space."),
    ("Eniram", "Warrior / cloaked", "200", "Medium", "2-40", "1,000",
     "Invisible until firing; infrared or proximity map required; distinct decloak sound."),
    ("Eniram Boss", "Boss", "2,000", "Very high", "5 and 30", "2,500",
     "Solid / non-cloaking; Plasma Rifle; avoid narrow corridors."),
    ("Mechanoid Warrior", "Boss", "1,000", "Very high", "10-40", "2,500",
     "Slow, audible footsteps, brutal close-range fire; may drop Dual Blaster."),
    ("Otrebor", "Sub-boss / technician", "200", "High", "24-40", "700",
     "Usually alone; evil laugh; burst down from range."),
    ("Rodex", "Centurion", "50", "Medium", "2-40", "700",
     "Pack attacker; may retreat/turn away; distinctive squeal."),
    ("Semaj", "Low-floor predator", "100", "Low", "31-40", "100",
     "Purple slime that attacks legs; no ranged weapon; easy to miss in larger fights."),
    ("Solrac", "Leader / boss", "3,000", "Very high", "25 and 30", "2,500",
     "Eye-energy attack; apparitions elsewhere are untouchable; alien weapons preferred."),
    ("Tebazile", "Guardian boss", "1,000 x5", "High", "40", "10,000",
     "Five-stage morph: Tebazile -> Eniram Boss -> Tymok -> Solrac -> Tebazile."),
    ("Tenaj", "Technician", "150", "Medium", "6-40", "700",
     "Smart, quick, ambush-prone; often turns away; may drop charge packs."),
    ("Ttocs", "Warrior", "150", "Medium", "14-40", "700",
     "Slow and not bright, but durable; maintain distance; squishy alert sound."),
    ("Tymok", "Boss", "2,000", "Very high", "15-39", "2,500",
     "Fast dodger with Plasma Rifle; works alone; keep moving and mine approach lanes."),
    ("Nerraw", "Surprise", "Unknown", "Extremely lethal", "31-39", "-",
     "Small and apparently harmless; can kill a strong Marine in seconds. First seen on 31."),
]

WEAPON_MANUAL = [
    ("1", "Taser", "None", "Short", "0-255", "Unlimited but slow; emergency fallback."),
    ("2", "Assault Shotgun", "5 std/shot", "Medium", "25-350", "CD-only; strongest at close range."),
    ("3", "M-24 C.A.W.", "1 std/shot", "Medium", "0-255", "Fast automatic; the Marine's starter."),
    ("4", "M-343 Tribarrel", "1 std/round, 3-round burst", "Long", "(0-255) x3", "Preferred human weapon at distance."),
    ("5", "Alien Dual Blaster", "2 energy/shot", "Medium", "0-255", "Economical alien sidearm."),
    ("6", "Alien Plasma Rifle", "3-5 net energy/shot", "Short-med", "(0-255)+25 splash", "Traveling plasma; ~10ft blast; can detonate mines."),
    ("7", "Alien Assault Cannon", "0-2 energy/burst", "Long", "0-255", "Four-round burst; very efficient; CD-only."),
    ("8", "Alien Disintegrator", "44-46 energy/shot", "Long", "1,000", "Boss/emergency weapon; enormous energy cost; CD-only."),
    ("M", "Proximity Mine", "1 mine", "Triggered", "(2-400)+100", "15ft blast; lethal to the Marine; max 25 carried."),
]

# Plane-0 (map geometry) semantics, keyed by the raw map word.
WALL_CODE_NOTES = {
    63: "Player-use normal elevator switch.",
    105: "Sight-transparent special wall page.",
    107: "Sight-transparent special wall page.",
    251: "Door (axis inferred from map topology).",
    252: "Door requiring the RED access card.",
    253: "Door requiring the BLUE access card.",
    254: "Door (axis inferred from map topology).",
}

# Plane-1 static object table: map word -> static index (word 23 == static 0).
STATIC_WORD_BASE = 23


# --------------------------------------------------------------------------
# Catalog assembly
# --------------------------------------------------------------------------


@dataclass
class Asset:
    id: str
    category: str
    subcategory: str
    name: str
    width: int
    height: int
    kind: str  # png | wav
    meta: dict
    search: str
    blank: bool = False


class Library:
    def __init__(self, root: Path):
        self.root = root
        self.media: dict[str, bytes] = {}
        self.assets: dict[str, Asset] = {}
        self.order: list[str] = []
        self._load()

    # -- helpers ----------------------------------------------------------
    def _read(self, name: str) -> bytes:
        return (self.root / name).read_bytes()

    def _add(self, asset: Asset, media: bytes) -> None:
        self.assets[asset.id] = asset
        self.media[asset.id] = media
        self.order.append(asset.id)

    # -- loading ----------------------------------------------------------
    def _load(self) -> None:
        exe = self._read("CORR7CD.EXE")
        palette = load_palette(exe)

        maps = parse_maps(self._read("MAPTEMP.CO7"))
        actors = {}
        try:
            with zipfile.ZipFile(self.root / "ecwolf.pk3") as pk3:
                actors = parse_actors(pk3)
        except (FileNotFoundError, KeyError, zipfile.BadZipFile):
            actors = {}

        # Cross-reference tables from the maps.
        wall_usage: dict[int, Counter] = defaultdict(Counter)  # wall page -> {map_index: cells}
        object_usage: dict[int, Counter] = defaultdict(Counter)  # plane1 word -> {map_index: cells}
        for gm in maps:
            for word in gm.planes[0]:
                if 1 <= word <= 250:
                    wall_usage[word - 1][gm.index] += 1
            for word in gm.planes[1]:
                if word != 18:
                    object_usage[word][gm.index] += 1

        # sprite page -> list of (actor, role, states)
        sprite_actors: dict[int, list[ActorInfo]] = defaultdict(list)
        for info in actors.values():
            for page in info.sprites:
                sprite_actors[page].append(info)

        self._load_walls(palette, wall_usage, maps)
        self._load_sprites(palette, sprite_actors, object_usage, maps)
        self._load_pictures(palette)
        self._load_maps(maps, palette)
        self.maps = maps

    def _load_walls(self, palette, wall_usage, maps):
        data = self._read("GFXTILES.CO7")
        h = parse_gfx_header(data)
        self._gfx = h
        self._gfx_data = data
        self._palette = palette
        for i in range(h.sprite_start):
            page = data[h.offsets[i] : h.offsets[i] + h.lengths[i]]
            rgb = wall_rgb(page, palette)
            r, g, b = average_color(rgb)
            used_in = sorted(wall_usage.get(i, {}).keys())
            total = sum(wall_usage.get(i, {}).values())
            note = WALL_CODE_NOTES.get(i + 1, "")
            meta = {
                "GFXTILES page": i,
                "Map word (plane 0)": i + 1,
                "Avg color": f"#{r:02x}{g:02x}{b:02x}",
                "Cells placed": total,
                "Appears in levels": [maps[m].name for m in used_in] if used_in else [],
                "Note": note,
            }
            asset = Asset(
                id=f"wall-{i:03d}",
                category="Walls",
                subcategory="Doors & Elevators" if note else ("In use" if total else "Unused"),
                name=f"Wall {i:03d}",
                width=64, height=64, kind="png",
                meta=meta,
                search=f"wall {i} {note}".lower(),
            )
            self._add(asset, encode_png(64, 64, rgb, alpha=False))

    def _load_sprites(self, palette, sprite_actors, object_usage, maps):
        h = self._gfx
        data = self._gfx_data
        role_to_sub = {
            "enemy": "Enemies",
            "decoration": "Decorations",
            "item": "Items & Pickups",
            "effect": "Effects & Projectiles",
            "player": "Player",
        }
        for i in range(h.sprite_start, h.sound_start):
            page = data[h.offsets[i] : h.offsets[i] + h.lengths[i]]
            sub_index = i - h.sprite_start  # C### number
            infos = sprite_actors.get(sub_index, [])
            # choose the most descriptive owner: enemy > item > decoration > effect
            priority = {"enemy": 0, "item": 1, "decoration": 2, "player": 3, "effect": 4}
            infos_sorted = sorted(infos, key=lambda a: priority.get(a.role, 9))
            owner = infos_sorted[0] if infos_sorted else None
            blank = False
            try:
                rgba = sprite_rgba(page, palette)
                if not any(rgba[3::4]):
                    blank = True
            except Exception:
                rgba = bytes(64 * 64 * 4)
                blank = True

            role = owner.role if owner else "decoration"
            subcategory = role_to_sub.get(role, "Uncategorized")
            if not owner:
                subcategory = "Uncategorized"

            name = f"C{sub_index:03d}"
            title = name
            if owner:
                title = f"{name} · {_pretty_actor(owner.name)}"

            meta = {
                "Sprite name": name,
                "GFXTILES chunk": i,
                "Owner actor": owner.name if owner else "(none identified)",
                "Role": role.title() if owner else "Unidentified",
                "Also used by": [a.name for a in infos_sorted[1:]] if len(infos_sorted) > 1 else [],
                "Appears in states": sorted(owner.states.get(sub_index, [])) if owner else [],
                "Actor note": owner.note if owner and owner.note else "",
            }
            asset = Asset(
                id=f"sprite-{sub_index:03d}",
                category="Sprites",
                subcategory=subcategory,
                name=title,
                width=64, height=64, kind="png",
                meta=meta,
                search=f"{name} {owner.name if owner else ''} {role} {subcategory}".lower(),
                blank=blank,
            )
            self._add(asset, encode_png(64, 64, rgba, alpha=True))

    def _load_pictures(self, palette):
        pics = extract_vga(
            self._read("VGADICT.CO7"),
            self._read("VGAHEAD.CO7"),
            self._read("VGAGRAPH.CO7"),
            palette,
        )
        for picture in pics:
            w, h, rgb, chunk_id = picture.width, picture.height, picture.rgb, picture.number
            name = f"C7G{chunk_id:04d}"
            sub = "HUD & Status" if 23 <= chunk_id <= 74 else "Screens & UI"
            meta = {
                "Picture id": name,
                "VGAGRAPH chunk": chunk_id,
                "Dimensions": f"{w} x {h}",
            }
            asset = Asset(
                id=f"pic-{chunk_id:04d}",
                category="Pictures",
                subcategory=sub,
                name=name,
                width=w, height=h, kind="png",
                meta=meta,
                search=f"{name} picture vga".lower(),
            )
            self._add(asset, encode_png(w, h, rgb, alpha=False))

    def _load_maps(self, maps, palette):
        for gm in maps:
            png, census = render_map(gm, self)
            enemies = sum(c for w, c in census.items() if w >= 108)
            statics = sum(c for w, c in census.items() if 23 <= w <= 105)
            meta = {
                "Internal name": gm.name,
                "Level number": gm.index + 1,
                "Dimensions": f"{gm.width} x {gm.height}",
                "Wall cells": sum(1 for v in gm.planes[0] if 1 <= v <= 250),
                "Door cells": sum(1 for v in gm.planes[0] if 251 <= v <= 254),
                "Object placements": statics,
                "Actor/enemy markers": enemies,
            }
            low = gm.name.lower()
            if "secret" in low:
                sub = "Secret / Bonus Floors"
            elif "network" in low:
                sub = "Network Levels"
            else:
                sub = "Campaign Floors"
            asset = Asset(
                id=f"map-{gm.index:02d}",
                category="Maps",
                subcategory=sub,
                name=f"{gm.index + 1:02d} · {gm.name}",
                width=gm.width, height=gm.height, kind="png",
                meta=meta,
                search=f"map level {gm.index + 1} {gm.name}".lower(),
            )
            self._add(asset, png)

    # -- serialization ----------------------------------------------------
    def catalog(self) -> dict:
        cats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        items = []
        for aid in self.order:
            a = self.assets[aid]
            cats[a.category][a.subcategory] += 1
            items.append({
                "id": a.id,
                "category": a.category,
                "subcategory": a.subcategory,
                "name": a.name,
                "w": a.width,
                "h": a.height,
                "blank": a.blank,
                "search": a.search,
            })
        categories = []
        for cat, subs in cats.items():
            categories.append({
                "name": cat,
                "count": sum(subs.values()),
                "subcategories": [{"name": s, "count": n} for s, n in subs.items()],
            })
        return {
            "title": "Corridor 7: Alien Invasion",
            "categories": categories,
            "items": items,
            "reference": {
                "enemies": ENEMY_MANUAL,
                "weapons": WEAPON_MANUAL,
            },
        }

    def detail(self, aid: str) -> dict | None:
        a = self.assets.get(aid)
        if not a:
            return None
        return {
            "id": a.id,
            "name": a.name,
            "category": a.category,
            "subcategory": a.subcategory,
            "w": a.width,
            "h": a.height,
            "blank": a.blank,
            "kind": a.kind,
            "meta": a.meta,
        }


def _pretty_actor(name: str) -> str:
    n = re.sub(r"^C7", "", name)
    n = re.sub(r"(?<!^)(?=[A-Z])", " ", n)
    return n.strip()


def render_map(gm: GameMap, lib: "Library") -> tuple[bytes, Counter]:
    """Render a schematic top-down automap and return (png, object census)."""
    scale = max(3, min(8, 640 // max(gm.width, gm.height)))
    w, h = gm.width, gm.height
    img = bytearray(w * scale * h * scale * 3)

    def put(cx, cy, color):
        for dy in range(scale):
            for dx in range(scale):
                px = cx * scale + dx
                py = cy * scale + dy
                d = (py * w * scale + px) * 3
                img[d], img[d + 1], img[d + 2] = color

    plane0, plane1 = gm.planes[0], gm.planes[1]
    for idx, v in enumerate(plane0):
        cx, cy = idx % w, idx // w
        if 1 <= v <= 250:
            color = (150, 150, 160)  # wall
        elif 251 <= v <= 254:
            color = (220, 180, 60)   # door
        elif v == 63:
            color = (80, 220, 120)   # elevator
        elif 256 <= v <= 287:
            color = (26, 30, 40)     # area / floor
        else:
            color = (12, 14, 18)
        put(cx, cy, color)

    census: Counter = Counter()
    for idx, v in enumerate(plane1):
        if v == 18:
            continue
        census[v] += 1
        cx, cy = idx % w, idx // w
        if 19 <= v <= 22:
            dot = (255, 255, 255)   # player start
        elif v >= 108:
            dot = (235, 70, 70)     # actor / enemy
        elif 23 <= v <= 105:
            dot = (70, 200, 235)    # static object
        else:
            continue
        # small centered dot
        for dy in range(max(1, scale - 2)):
            for dx in range(max(1, scale - 2)):
                px = cx * scale + 1 + dx
                py = cy * scale + 1 + dy
                d = (py * w * scale + px) * 3
                img[d], img[d + 1], img[d + 2] = dot

    return encode_png(w * scale, h * scale, bytes(img), alpha=False), census


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    library: Library = None  # set on the class before serving

    def log_message(self, *args):  # keep the console quiet
        pass

    def _send(self, code, body, ctype, cache=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/catalog":
            body = json.dumps(self.library.catalog()).encode("utf-8")
            self._send(200, body, "application/json")
        elif path.startswith("/api/asset/"):
            detail = self.library.detail(path[len("/api/asset/"):])
            if detail is None:
                self._send(404, b"{}", "application/json")
            else:
                self._send(200, json.dumps(detail).encode("utf-8"), "application/json")
        elif path.startswith("/media/"):
            aid = path[len("/media/"):].rsplit(".", 1)[0]
            blob = self.library.media.get(aid)
            if blob is None:
                self._send(404, b"", "text/plain")
            else:
                self._send(200, blob, "image/png", cache=True)
        else:
            self._send(404, b"not found", "text/plain")


def main():
    ap = argparse.ArgumentParser(description="Corridor 7 asset gallery")
    ap.add_argument("--dir", type=Path, default=Path(__file__).resolve().parent,
                    help="directory containing the Corridor 7 release files")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    print(f"Loading Corridor 7 assets from {args.dir} ...")
    library = Library(args.dir)
    print(f"  decoded {len(library.assets)} assets into memory")
    Handler.library = library
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Serving the Corridor 7 asset browser at {url}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


# --------------------------------------------------------------------------
# Front-end (single embedded page)
# --------------------------------------------------------------------------

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Corridor 7 — Asset Browser</title>
<style>
  :root{
    --bg:#0c0e13; --panel:#141821; --panel2:#1b2130; --line:#262d3d;
    --text:#e6e9f0; --dim:#8a93a6; --accent:#38e1b0; --accent2:#5aa9ff;
    --danger:#ff5a5a;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
    font:14px/1.5 "Inter",system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  a{color:var(--accent2);text-decoration:none}
  header{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:18px;
    padding:14px 22px;background:linear-gradient(180deg,#11141c,#0c0e13);
    border-bottom:1px solid var(--line)}
  header h1{font-size:16px;margin:0;letter-spacing:.5px;font-weight:700}
  header h1 span{color:var(--accent)}
  .tag{font-size:11px;color:var(--dim);border:1px solid var(--line);
    padding:2px 8px;border-radius:20px}
  #search{margin-left:auto;background:var(--panel2);border:1px solid var(--line);
    color:var(--text);padding:9px 14px;border-radius:8px;width:280px;outline:none}
  #search:focus{border-color:var(--accent)}
  .layout{display:flex;min-height:calc(100vh - 55px)}
  nav{width:220px;flex:none;border-right:1px solid var(--line);padding:14px 10px;
    background:var(--panel)}
  .cat{margin-bottom:6px}
  .cat>button{width:100%;text-align:left;background:none;border:none;color:var(--text);
    font-size:13px;font-weight:600;padding:8px 10px;border-radius:7px;cursor:pointer;
    display:flex;justify-content:space-between;align-items:center}
  .cat>button:hover{background:var(--panel2)}
  .cat.active>button{background:var(--panel2);color:var(--accent)}
  .cat .n{color:var(--dim);font-weight:500;font-size:11px}
  .subs{margin:2px 0 6px 6px;display:none}
  .cat.open .subs{display:block}
  .subs button{width:100%;text-align:left;background:none;border:none;color:var(--dim);
    font-size:12px;padding:5px 10px;border-radius:6px;cursor:pointer;
    display:flex;justify-content:space-between}
  .subs button:hover{background:var(--panel2);color:var(--text)}
  .subs button.active{color:var(--accent)}
  main{flex:1;padding:18px 22px;overflow:auto}
  .crumbs{color:var(--dim);font-size:12px;margin-bottom:14px}
  .crumbs b{color:var(--text)}
  .grid{display:grid;gap:12px;
    grid-template-columns:repeat(auto-fill,minmax(108px,1fr))}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:8px;cursor:pointer;transition:.12s;display:flex;flex-direction:column;gap:6px}
  .card:hover{border-color:var(--accent);transform:translateY(-2px)}
  .thumb{width:100%;aspect-ratio:1;background:
      linear-gradient(45deg,#0a0c10 25%,transparent 25%,transparent 75%,#0a0c10 75%) 0 0/16px 16px,
      linear-gradient(45deg,#0a0c10 25%,#111 25%,#111 75%,#0a0c10 75%) 8px 8px/16px 16px;
    border-radius:6px;display:flex;align-items:center;justify-content:center;overflow:hidden}
  .thumb img{max-width:100%;max-height:100%;image-rendering:pixelated}
  .card .lbl{font-size:11px;color:var(--dim);white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis}
  .card.blank .thumb::after{content:"empty";color:#3a4256;font-size:10px}
  .count{color:var(--dim);font-size:12px;margin-bottom:10px}
  /* modal */
  .overlay{position:fixed;inset:0;background:rgba(4,6,10,.72);backdrop-filter:blur(3px);
    display:none;align-items:center;justify-content:center;z-index:50;padding:24px}
  .overlay.show{display:flex}
  .modal{background:var(--panel);border:1px solid var(--line);border-radius:14px;
    width:min(860px,100%);max-height:90vh;overflow:auto;display:grid;
    grid-template-columns:340px 1fr}
  .preview{background:#07090d;border-right:1px solid var(--line);padding:22px;
    display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px}
  .preview .stage{width:280px;height:280px;display:flex;align-items:center;justify-content:center;
    background:
      linear-gradient(45deg,#0a0c10 25%,transparent 25%,transparent 75%,#0a0c10 75%) 0 0/24px 24px,
      linear-gradient(45deg,#0a0c10 25%,#101319 25%,#101319 75%,#0a0c10 75%) 12px 12px/24px 24px;
    border-radius:10px;overflow:hidden}
  .preview .stage img{image-rendering:pixelated;max-width:100%;max-height:100%}
  .zoomrow{display:flex;gap:8px;align-items:center;color:var(--dim);font-size:12px}
  .zoomrow input{flex:1}
  .details{padding:22px}
  .details h2{margin:0 0 2px;font-size:20px}
  .details .sub{color:var(--accent);font-size:12px;margin-bottom:16px}
  table.meta{width:100%;border-collapse:collapse;font-size:13px}
  table.meta td{padding:7px 4px;border-bottom:1px solid var(--line);vertical-align:top}
  table.meta td.k{color:var(--dim);width:150px}
  table.meta a.chip,span.chip{display:inline-block;background:var(--panel2);border:1px solid var(--line);
    border-radius:5px;padding:1px 7px;margin:2px 3px 0 0;font-size:11px;color:var(--text)}
  .close{position:absolute;top:18px;right:22px;background:var(--panel2);border:1px solid var(--line);
    color:var(--text);width:32px;height:32px;border-radius:8px;cursor:pointer;font-size:16px}
  .lore{margin-top:16px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;
    padding:14px;font-size:13px}
  .lore h3{margin:0 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:1px;color:var(--dim)}
  .manual{overflow:auto}
  .manual table{width:100%;border-collapse:collapse;font-size:12px}
  .manual th,.manual td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left}
  .manual th{color:var(--dim);position:sticky;top:0;background:var(--panel)}
  .empty{color:var(--dim);padding:40px;text-align:center}
</style>
</head>
<body>
<header>
  <h1>CORRIDOR&nbsp;<span>7</span> · Asset Browser</h1>
  <span class="tag" id="assetcount">…</span>
  <input id="search" placeholder="Search all assets…" autocomplete="off">
</header>
<div class="layout">
  <nav id="nav"></nav>
  <main id="main"><div class="empty">Loading assets…</div></main>
</div>

<div class="overlay" id="overlay">
  <div class="modal" id="modal"></div>
  <button class="close" id="closebtn" style="display:none">✕</button>
</div>

<script>
let CATALOG=null, STATE={cat:null,sub:null,query:""};

async function boot(){
  CATALOG = await (await fetch('/api/catalog')).json();
  document.getElementById('assetcount').textContent = CATALOG.items.length + ' assets';
  STATE.cat = CATALOG.categories[0].name;
  renderNav(); renderGrid();
}

function renderNav(){
  const nav=document.getElementById('nav');
  nav.innerHTML='';
  for(const c of CATALOG.categories){
    const div=document.createElement('div');
    div.className='cat'+(c.name===STATE.cat?' active open':'');
    const subs=c.subcategories.map(s=>
      `<button data-sub="${s.name}" class="${STATE.cat===c.name&&STATE.sub===s.name?'active':''}">
         <span>${s.name}</span><span class="n">${s.count}</span></button>`).join('');
    div.innerHTML=`<button data-cat="${c.name}">
        <span>${c.name}</span><span class="n">${c.count}</span></button>
        <div class="subs">${subs}</div>`;
    div.querySelector('[data-cat]').onclick=()=>{
      STATE.cat=c.name; STATE.sub=null; STATE.query=''; document.getElementById('search').value='';
      renderNav(); renderGrid();
    };
    div.querySelectorAll('[data-sub]').forEach(b=>b.onclick=e=>{
      e.stopPropagation();
      STATE.cat=c.name; STATE.sub=b.dataset.sub; STATE.query='';
      document.getElementById('search').value='';
      renderNav(); renderGrid();
    });
    nav.appendChild(div);
  }
  // reference manuals entry
  const ref=document.createElement('div');
  ref.className='cat';
  ref.innerHTML=`<button data-ref="1"><span>📖 Field Manual</span></button>`;
  ref.querySelector('button').onclick=()=>{STATE.cat='__manual';STATE.sub=null;renderNav();renderManual();};
  nav.appendChild(ref);
}

function filtered(){
  const q=STATE.query.trim().toLowerCase();
  return CATALOG.items.filter(it=>{
    if(q) return it.search.includes(q)||it.name.toLowerCase().includes(q);
    if(it.category!==STATE.cat) return false;
    if(STATE.sub && it.subcategory!==STATE.sub) return false;
    return true;
  });
}

function renderGrid(){
  const main=document.getElementById('main');
  const items=filtered();
  const where = STATE.query ? `Search “${STATE.query}”`
      : `<b>${STATE.cat}</b>${STATE.sub?' › '+STATE.sub:''}`;
  let html=`<div class="crumbs">${where}</div>
            <div class="count">${items.length} asset${items.length!==1?'s':''}</div>`;
  if(!items.length){ main.innerHTML=html+`<div class="empty">Nothing here.</div>`; return; }
  html+='<div class="grid">';
  for(const it of items){
    html+=`<div class="card${it.blank?' blank':''}" data-id="${it.id}">
      <div class="thumb">${it.blank?'':`<img loading="lazy" src="/media/${it.id}.png">`}</div>
      <div class="lbl" title="${it.name}">${it.name}</div>
    </div>`;
  }
  html+='</div>';
  main.innerHTML=html;
  main.querySelectorAll('.card').forEach(c=>c.onclick=()=>openAsset(c.dataset.id));
}

function renderManual(){
  const main=document.getElementById('main');
  const e=CATALOG.reference.enemies, w=CATALOG.reference.weapons;
  const erows=e.map(r=>`<tr><td><b>${r[0]}</b></td><td>${r[1]}</td><td>${r[2]}</td>
     <td>${r[3]}</td><td>${r[4]}</td><td>${r[5]}</td><td>${r[6]}</td></tr>`).join('');
  const wrows=w.map(r=>`<tr><td><b>${r[0]}</b></td><td>${r[1]}</td><td>${r[2]}</td>
     <td>${r[3]}</td><td>${r[4]}</td><td>${r[5]}</td></tr>`).join('');
  main.innerHTML=`<div class="crumbs"><b>Field Manual</b> · from the Technical &amp; Strategy Compendium</div>
    <div class="lore manual"><h3>Alien roster (16 CD-edition actors)</h3>
      <table><tr><th>Actor</th><th>Type</th><th>Health</th><th>Damage</th>
      <th>Levels</th><th>Score</th><th>Behavior / counterplay</th></tr>${erows}</table></div>
    <div class="lore manual"><h3>Weapons &amp; mines</h3>
      <table><tr><th>Key</th><th>Weapon</th><th>Consumption</th><th>Range</th>
      <th>Guide damage</th><th>Operational role</th></tr>${wrows}</table></div>`;
}

async function openAsset(id){
  const d=await (await fetch('/api/asset/'+id)).json();
  const modal=document.getElementById('modal');
  let rows='';
  for(const [k,v] of Object.entries(d.meta)){
    let val=v;
    if(Array.isArray(v)){
      if(!v.length) continue;
      val=v.map(x=>`<span class="chip">${x}</span>`).join('');
    } else if(v===''||v===null){ continue; }
    rows+=`<tr><td class="k">${k}</td><td>${val}</td></tr>`;
  }
  modal.innerHTML=`
    <div class="preview">
      <div class="stage"><img id="stageimg" src="/media/${d.id}.png"></div>
      <div class="zoomrow" style="width:280px">
        <span>zoom</span><input type="range" min="1" max="8" value="4" id="zoom">
      </div>
      <div style="color:var(--dim);font-size:12px">${d.w}×${d.h}px · ${d.category}</div>
    </div>
    <div class="details">
      <h2>${d.name}</h2>
      <div class="sub">${d.subcategory}</div>
      <table class="meta">${rows}</table>
    </div>`;
  const img=modal.querySelector('#stageimg');
  const base=Math.min(280/d.w,280/d.h);
  const zoom=modal.querySelector('#zoom');
  const apply=()=>{const s=base*zoom.value/4*d.w;img.style.width=Math.min(280,s*(280/(base*d.w)))+'px';};
  zoom.oninput=()=>{img.style.width=(d.w*zoom.value)+'px';img.style.height=(d.h*zoom.value)+'px';};
  document.getElementById('overlay').classList.add('show');
  document.getElementById('closebtn').style.display='block';
}
function closeModal(){document.getElementById('overlay').classList.remove('show');
  document.getElementById('closebtn').style.display='none';}
document.getElementById('closebtn').onclick=closeModal;
document.getElementById('overlay').onclick=e=>{if(e.target.id==='overlay')closeModal();};
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
document.getElementById('search').addEventListener('input',e=>{
  STATE.query=e.target.value; if(STATE.query){STATE.cat=null;STATE.sub=null;}
  renderGrid();
});
boot();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
