# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Map packs: a bounded campaign schema, the MAPINFO it generates, and a manifest.

Everything up to here exports a *preview*: markers and PLANES, nothing else, so
the engine plays your map in a stock slot with the stock level's name, music and
routing. A pack is the other thing an author eventually wants -- several maps
that are a campaign of their own, with their own names and their own order.

That needs metadata, and metadata for this engine means MAPINFO. Three facts
about how the engine reads it decide the whole design:

**Later wins, and it wins completely.** `G_ParseMapInfo` parses the iwad's own
mapinfo first, then every lump named MAPINFO in load order. A `map` block does
`LevelInfo newMap = defaultMap; ...; existing = newMap` -- an assignment, not a
merge. So a block for a slot the stock game defines does not adjust that level,
it replaces it, starting from whatever `defaultmap` held. Which is why the
default here is to build on MAP61 and up: the stock game defines MAP01..MAP60,
so a pack above that line cannot regress a stock level however wrong it is.

**A campaign ends by naming it.** `next = "EndTitle"` is matched by name in
`wl_game.cpp` and runs the victory path -- fade, the SEQFOUR cinematic, the
tally, the victory page. It needs no intermission block, which is just as well:
Corridor 7 defines exactly one (`DemoLoop`), so `EndSequence, "..."` has nothing
to point at here and is not offered.

**Strings escape three ways and no more.** `Scanner::Unescape` knows `\\\\`, `\\"`
and `\\n`; every other byte is itself. So a name is escaped for the first two,
and anything that cannot survive the round trip -- a control byte, something
outside ASCII the engine has no glyph for -- is refused rather than written and
hoped for. A level name is not a place to find out that a quote ended a block
early.

The one piece of routing that is not obvious: Corridor 7 has no secret-exit
tile. `Exit_Normal` takes `ex_secretlevel` when `arg0 == 2`, and no translator
entry sets that. What sets it is plane 1: `gamemap_planes.cpp` promotes the
trigger on a wall-63 cell to `arg0 = 2` when the object value 99 sits on it. So
`secretnext` routes for real, and a pack that declares one is told where the
marker goes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .archive import MAX_MAPS
from .errors import Diagnostic, ExportError, Severity, export_error
from .wad import WadLump, encode_planes_lump, encode_wad, validate_marker

#: Slots the stock Corridor 7 mapinfo defines. A pack entry at or below this
#: replaces a shipped level rather than adding one.
STOCK_SLOTS = 60

#: The name `wl_game.cpp` compares against to end a campaign.
END_OF_CAMPAIGN = "EndTitle"

#: Lump names. MAPINFO is the one the engine reads; PACKINFO is inert, and
#: carries the manifest so a pack that arrives without its README still says
#: what it is and what it needs.
MAPINFO_LUMP = "MAPINFO"
MANIFEST_LUMP = "PACKINFO"

#: Bounds. Not engine limits -- the engine would take longer strings -- but the
#: point of a bounded schema is that every value has a stated ceiling.
MAX_TITLE = 64
MAX_LEVEL_NAME = 64
MAX_ENTRIES = 60
MAX_PAR = 60 * 60 * 24

#: A music lump name: what the engine can actually look up. Corridor 7's own
#: are C7MUS00..C7MUS33.
_MUSIC = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,7}$")

#: Printable ASCII. Deliberately not "anything that is not a control byte": the
#: engine's fonts are built from the game's own glyph pages, and a name it
#: cannot draw is a name the author will not see.
#:
#: `\A`/`\Z`, not `^`/`$`. `$` also matches immediately before a trailing
#: newline, so "\n" on its own satisfied this pattern -- which meant a name
#: containing a newline was correctly refused and then could not say which
#: character was wrong, because the search for the offender found none.
_PRINTABLE = re.compile(r"\A[\x20-\x7e]*\Z")


def quote(text: str, where: str = "") -> str:
    """One MAPINFO string literal, escaped the way the scanner unescapes.

    `Scanner::Unescape` walks its table in order with `\\\\` first so it does not
    re-escape its own output; this does the same for the same reason.
    """
    if not _PRINTABLE.match(text):
        bad = next(ch for ch in text if not 0x20 <= ord(ch) <= 0x7e)
        raise export_error(
            "C7E-PACK-002",
            f"{text!r} contains {bad!r}, which MAPINFO cannot carry; use printable ASCII",
            where,
        )
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass(frozen=True)
class Route:
    """Where a level goes when it is finished.

    `slot` is a map, `None` is the end of the campaign. There is no third case:
    a route to a level outside the pack is what a dangling reference would be,
    and the validator refuses it rather than emitting a `next` the engine will
    resolve to a level the pack does not carry.
    """

    slot: int | None = None

    @property
    def ends(self) -> bool:
        return self.slot is None

    def mapinfo_value(self) -> str:
        return quote(END_OF_CAMPAIGN) if self.ends else quote(f"MAP{self.slot:02d}")

    def to_json(self):
        return None if self.ends else self.slot

    @classmethod
    def from_json(cls, raw, where: str) -> "Route":
        if raw is None:
            return cls(None)
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise export_error("C7E-PACK-001", f"a route is a slot number or null, not {raw!r}", where)
        return cls(raw)


@dataclass(frozen=True)
class CampaignEntry:
    """One level's metadata. Nothing here touches map geometry."""

    slot: int
    name: str
    next: Route = field(default_factory=Route)
    secret: Route | None = None
    music: str = ""
    par: int = 0
    floor_number: int = 0
    #: The tally screen between this level and the next. On by default, which
    #: is what the stock game does. A campaign that runs its floors together --
    #: or one whose levels are short -- turns it off, and then the level change
    #: needs no keypress at all, which is also the only way an automated test
    #: can watch a route being taken.
    intermission: bool = True

    @property
    def lump_name(self) -> str:
        return f"MAP{self.slot:02d}"

    def to_json(self) -> dict:
        return {
            "slot": self.slot,
            "name": self.name,
            "next": self.next.to_json(),
            "secret": None if self.secret is None else self.secret.to_json(),
            "has_secret": self.secret is not None,
            "music": self.music,
            "par": self.par,
            "floor_number": self.floor_number,
            "intermission": self.intermission,
        }

    @classmethod
    def from_json(cls, raw: dict, where: str) -> "CampaignEntry":
        if not isinstance(raw, dict):
            raise export_error("C7E-PACK-001", "a campaign entry is an object", where)
        allowed = {"slot", "name", "next", "secret", "has_secret", "music", "par",
                   "floor_number", "intermission"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise export_error("C7E-PACK-001", f"unknown campaign keys {unknown}", where)
        # `has_secret` rather than "secret is not None": a secret route to the
        # end of the campaign is a real thing to want, and is also null.
        secret = Route.from_json(raw.get("secret"), where) if raw.get("has_secret") else None
        return cls(
            slot=_require_int(raw, "slot", where),
            name=_require_str(raw, "name", where),
            next=Route.from_json(raw.get("next"), where),
            secret=secret,
            music=str(raw.get("music", "")),
            par=int(raw.get("par", 0) or 0),
            floor_number=int(raw.get("floor_number", 0) or 0),
            intermission=bool(raw.get("intermission", True)),
        )


def _require_int(raw: dict, key: str, where: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise export_error("C7E-PACK-001", f"{key} must be an integer, not {value!r}", where)
    return value


def _require_str(raw: dict, key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise export_error("C7E-PACK-001", f"{key} must be a string, not {value!r}", where)
    return value


@dataclass(frozen=True)
class Campaign:
    """A pack's whole metadata surface. Deliberately this small."""

    title: str = "Untitled campaign"
    #: The episode's menu hotkey. One character, because that is what the
    #: episode block's `key` is.
    key: str = "C"
    entries: tuple[CampaignEntry, ...] = ()

    @property
    def start(self) -> int | None:
        return self.entries[0].slot if self.entries else None

    def entry_for(self, slot: int) -> CampaignEntry | None:
        for entry in self.entries:
            if entry.slot == slot:
                return entry
        return None

    def to_json(self) -> dict:
        return {
            "title": self.title,
            "key": self.key,
            "entries": [entry.to_json() for entry in self.entries],
        }

    @classmethod
    def from_json(cls, raw, where: str = "campaign") -> "Campaign":
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise export_error("C7E-PACK-001", "the campaign block is an object", where)
        unknown = sorted(set(raw) - {"title", "key", "entries"})
        if unknown:
            raise export_error("C7E-PACK-001", f"unknown campaign keys {unknown}", where)
        raw_entries = raw.get("entries") or []
        if not isinstance(raw_entries, list):
            raise export_error("C7E-PACK-001", "campaign entries are a list", where)
        return cls(
            title=str(raw.get("title", "Untitled campaign")),
            key=str(raw.get("key", "C")),
            entries=tuple(
                CampaignEntry.from_json(entry, f"{where} entry {index}")
                for index, entry in enumerate(raw_entries)
            ),
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
#
# Codes, so the GUI and the tests agree on what each problem is:
#
#   C7E-PACK-001  the campaign block is malformed (raised, not reported)
#   C7E-PACK-002  a string MAPINFO cannot carry
#   C7E-PACK-003  the graph is broken: a route with nowhere to go
#   C7E-PACK-004  an entry has no map, or a map has no entry
#   C7E-PACK-005  a slot the stock game already defines
#   C7E-PACK-006  a value outside this schema's stated bounds
#   C7E-PACK-007  no route reaches the end of the campaign
#   C7E-PACK-008  a secret route with no marker-99 elevator to fire it
#   C7E-PACK-009  the pack would redistribute retail map data


def _problem(code: str, severity: Severity, message: str, where: str = "",
             detail: str = "") -> Diagnostic:
    return Diagnostic(code, severity, message, where, detail=detail)


def _secret_elevator_cells(document) -> list[tuple[int, int]]:
    """Cells that fire a secret exit: object 99 on a wall-63 elevator switch.

    Mirrors `gamemap_planes.cpp`, which promotes that cell's `Exit_Normal`
    trigger from arg0 1 to 2. Both planes have to agree; 99 anywhere else is an
    ignored object, and a 63 without it is the ordinary elevator.
    """
    found = []
    for y in range(document.height):
        for x in range(document.width):
            if document.cell(0, x, y) == 63 and document.cell(1, x, y) == 99:
                found.append((x, y))
    return found


def validate(campaign: Campaign, documents) -> list[Diagnostic]:
    """Everything wrong with a pack, as data. Errors block a build; warnings do not."""
    problems: list[Diagnostic] = []
    by_slot = {document.slot: document for document in documents}

    if not campaign.entries:
        problems.append(_problem(
            "C7E-PACK-004", Severity.ERROR,
            "the campaign has no levels; add one for each map the pack ships"))
        return problems

    if len(campaign.entries) > MAX_ENTRIES:
        problems.append(_problem(
            "C7E-PACK-006", Severity.ERROR,
            f"{len(campaign.entries)} levels; this schema carries at most {MAX_ENTRIES}"))

    for text, what, limit in ((campaign.title, "the campaign title", MAX_TITLE),
                              (campaign.key, "the episode key", 1)):
        try:
            quote(text, what)
        except ExportError as error:
            problems.append(error.diagnostic)
        if len(text) > limit:
            problems.append(_problem(
                "C7E-PACK-006", Severity.ERROR,
                f"{what} is {len(text)} characters; the limit is {limit}", what))
    if not campaign.key:
        problems.append(_problem(
            "C7E-PACK-006", Severity.ERROR,
            "the episode needs a menu key, one character", "the episode key"))

    seen: set[int] = set()
    for entry in campaign.entries:
        where = entry.lump_name
        if entry.slot in seen:
            problems.append(_problem(
                "C7E-PACK-004", Severity.ERROR,
                f"two campaign levels claim {where}", where))
        seen.add(entry.slot)

        if not 1 <= entry.slot <= MAX_MAPS:
            problems.append(_problem(
                "C7E-PACK-006", Severity.ERROR,
                f"slot {entry.slot} is outside MAP01..MAP{MAX_MAPS}", where))
            continue

        if entry.slot not in by_slot:
            problems.append(_problem(
                "C7E-PACK-004", Severity.ERROR,
                f"{where} is in the campaign but the project has no map in that slot", where))

        if entry.slot <= STOCK_SLOTS:
            problems.append(_problem(
                "C7E-PACK-005", Severity.WARNING,
                f"{where} is a stock Corridor 7 level; a pack block replaces it "
                f"rather than adding to the game. Slots above MAP{STOCK_SLOTS} are free",
                where))

        try:
            quote(entry.name, where)
        except ExportError as error:
            problems.append(error.diagnostic)
        if not entry.name.strip():
            problems.append(_problem(
                "C7E-PACK-006", Severity.ERROR, f"{where} has no name", where))
        elif len(entry.name) > MAX_LEVEL_NAME:
            problems.append(_problem(
                "C7E-PACK-006", Severity.ERROR,
                f"{where}'s name is {len(entry.name)} characters; the limit is "
                f"{MAX_LEVEL_NAME}", where))

        if entry.music and not _MUSIC.match(entry.music):
            problems.append(_problem(
                "C7E-PACK-006", Severity.ERROR,
                f"{entry.music!r} is not a lump name; music is up to eight "
                "characters, letters, digits and underscores", where))
        if not 0 <= entry.par <= MAX_PAR:
            problems.append(_problem(
                "C7E-PACK-006", Severity.ERROR,
                f"par {entry.par} is outside 0..{MAX_PAR} seconds", where))

        for route, what in ((entry.next, "next"), (entry.secret, "secretnext")):
            if route is None or route.ends:
                continue
            if route.slot not in seen | {e.slot for e in campaign.entries}:
                problems.append(_problem(
                    "C7E-PACK-003", Severity.ERROR,
                    f"{where}'s {what} goes to MAP{route.slot:02d}, which this "
                    "campaign does not define", where))

        if entry.secret is not None and entry.slot in by_slot:
            if not _secret_elevator_cells(by_slot[entry.slot]):
                problems.append(_problem(
                    "C7E-PACK-008", Severity.WARNING,
                    f"{where} declares a secret exit, but nothing in the map can "
                    "fire one: put object 99 on an elevator switch (wall 63) to "
                    "make that switch the secret elevator", where))

    orphans = sorted(set(by_slot) - seen)
    for slot in orphans:
        problems.append(_problem(
            "C7E-PACK-004", Severity.WARNING,
            f"the project's MAP{slot:02d} is not in the campaign, so the pack "
            "ships a map no route reaches", f"MAP{slot:02d}"))

    if not _reaches_end(campaign):
        problems.append(_problem(
            "C7E-PACK-007", Severity.ERROR,
            "no route from the first level reaches the end of the campaign; "
            f"one level's next must be the end (\"{END_OF_CAMPAIGN}\")"))

    for entry in campaign.entries:
        document = by_slot.get(entry.slot)
        if document is not None and document.source is not None and document.source.identified:
            problems.append(_problem(
                "C7E-PACK-009", Severity.ERROR,
                f"{entry.lump_name} was imported from {document.source.display_path or 'a retail archive'} "
                "and its map data is Corridor 7's, not yours; a pack is made to be "
                "handed to other people, and that data is not yours to hand over",
                entry.lump_name,
                detail=document.source.sha256))

    return problems


def _reaches_end(campaign: Campaign) -> bool:
    """Can the campaign be finished, following routes from the first level?

    A campaign whose every route is a cycle starts and never ends, which the
    engine will happily run forever. Both routes are followed, because a secret
    branch is a legitimate way to reach the ending.
    """
    entries = {entry.slot: entry for entry in campaign.entries}
    start = campaign.start
    if start is None:
        return False
    stack, seen = [start], set()
    while stack:
        slot = stack.pop()
        if slot in seen:
            continue
        seen.add(slot)
        entry = entries.get(slot)
        if entry is None:
            continue
        for route in (entry.next, entry.secret):
            if route is None:
                continue
            if route.ends:
                return True
            stack.append(route.slot)
    return False


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

#: Bumped when the generated layout changes in a way a reader should notice.
GENERATOR_VERSION = 1


def generate_mapinfo(campaign: Campaign, translator: str = "") -> str:
    """The MAPINFO lump for a pack. Deterministic, so a pack has one digest.

    `clearepisodes` before the episode is the difference between a pack that
    replaces the campaign the menu offers and one that quietly adds a second
    entry the player has to know to pick. A pack is a campaign; it says so.
    """
    lines = [
        "// Generated by EC7Edit. Metadata only -- no game content is in this lump.",
        f"// generator {GENERATOR_VERSION}",
        "",
        "clearepisodes",
        f"episode {quote(campaign.entries[0].lump_name)}",
        "{",
        f"\tname = {quote(campaign.title)}",
        f"\tkey = {quote(campaign.key)}",
        "}",
        "",
    ]
    for entry in campaign.entries:
        lines.append(f"map {quote(entry.lump_name)} {quote(entry.name)}")
        lines.append("{")
        lines.append(f"\tnext = {entry.next.mapinfo_value()}")
        if entry.secret is not None:
            lines.append(f"\tsecretnext = {entry.secret.mapinfo_value()}")
        if entry.music:
            lines.append(f"\tmusic = {quote(entry.music)}")
        if entry.par:
            lines.append(f"\tpar = {entry.par}")
        if entry.floor_number:
            lines.append(f"\tfloornumber = {entry.floor_number}")
        # A flag, not a value: the engine's key is the negative one, and it is
        # written only when the author turned the tally off.
        if not entry.intermission:
            lines.append("\tnointermission")
        if translator:
            # Per map, never in gameinfo: a translator named there would apply
            # to the whole game, and the point of a generated one is that it
            # applies to this floor and leaves Corridor 7 alone.
            lines.append(f"\ttranslator = {quote(translator)}")
        lines.append("\tcluster = 1")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


MANIFEST_HEADER = "EC7Wolf map pack"


def generate_manifest(campaign: Campaign, documents, *, project_name: str = "",
                      author: str = "") -> str:
    """What the pack is, what it needs, and what it deliberately does not contain.

    Written for the person who receives the file, not for a parser. The one
    thing it must be unambiguous about is the last section: a pack is metadata
    and map geometry, it is not the game, and it does not work without the
    recipient's own Corridor 7 CD.
    """
    by_slot = {document.slot: document for document in documents}
    lines = [
        MANIFEST_HEADER,
        "=" * len(MANIFEST_HEADER),
        "",
        f"Campaign:  {campaign.title}",
    ]
    if project_name:
        lines.append(f"Project:   {project_name}")
    if author:
        lines.append(f"Author:    {author}")
    lines += [
        f"Levels:    {len(campaign.entries)}",
        f"Starts at: {campaign.entries[0].lump_name if campaign.entries else '(none)'}",
        "",
        "Levels and routing",
        "------------------",
    ]
    for entry in campaign.entries:
        document = by_slot.get(entry.slot)
        size = f"{document.width}x{document.height}" if document else "no map"
        destination = "end of campaign" if entry.next.ends else f"MAP{entry.next.slot:02d}"
        lines.append(f"  {entry.lump_name}  {entry.name}  ({size})")
        lines.append(f"      exit    -> {destination}")
        if entry.secret is not None:
            secret = "end of campaign" if entry.secret.ends else f"MAP{entry.secret.slot:02d}"
            lines.append(f"      secret  -> {secret}")
        if entry.music:
            lines.append(f"      music      {entry.music}")

    lines += [
        "",
        "What you need to play it",
        "------------------------",
        "  * EC7Wolf.",
        "  * Your own copy of Corridor 7: Alien Invasion. This pack contains no",
        "    part of that game -- no art, no sounds, no music, no level data from",
        "    it -- and cannot be played without it. Nothing here replaces buying",
        "    or owning the original.",
        "",
        "  Put the .wad beside your game data and add it to the command line:",
        "",
        "      ec7wolf --data CO7 --file <this pack>.wad",
        "",
        "What is in the file",
        "-------------------",
        "  Two lumps per level -- an empty MAPxx marker and the PLANES the editor",
        "  wrote from the map you see in it -- plus one MAPINFO lump of generated",
        "  metadata and this text. Nothing else. No textures, no sounds, no",
        "  DECORATE, no palette: a pack cannot change how the game behaves, only",
        "  which levels it offers and the order they come in.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Building, and proving what was built
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PackAudit:
    """What a built pack turned out to contain, read back from the bytes.

    Produced by reading the WAD, never by remembering what was written: "the
    package contains only what it should" is a claim about a file, and a claim
    about a file is checked by opening it.
    """

    markers: tuple[str, ...]
    lump_names: tuple[str, ...]
    metadata_bytes: int
    map_bytes: int
    unexpected: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.unexpected

    def describe(self) -> str:
        return (
            f"{len(self.markers)} level(s), {len(self.lump_names)} lumps, "
            f"{self.map_bytes} bytes of map data, {self.metadata_bytes} bytes of metadata"
        )


@dataclass(frozen=True)
class Pack:
    """A built pack: the file, the text beside it, and the audit of both."""

    wad: bytes
    manifest: str
    mapinfo: str
    audit: PackAudit
    problems: tuple[Diagnostic, ...] = ()


def build_pack(campaign: Campaign, documents, *, project_name: str = "",
               author: str = "", allow_warnings: bool = True) -> Pack:
    """Build a pack, refusing rather than guessing when the campaign is wrong."""
    problems = validate(campaign, documents)
    blocking = [p for p in problems if p.severity >= Severity.ERROR]
    if blocking:
        raise export_error(
            blocking[0].code,
            f"{blocking[0].message} ({len(blocking)} problem(s) block this pack)",
            blocking[0].where,
        )
    if not allow_warnings:
        warnings = [p for p in problems if p.severity == Severity.WARNING]
        if warnings:
            raise export_error(
                warnings[0].code,
                f"{warnings[0].message} ({len(warnings)} warning(s), and warnings "
                "were asked to block)",
                warnings[0].where,
            )

    by_slot = {document.slot: document for document in documents}
    mapinfo = generate_mapinfo(campaign)
    manifest = generate_manifest(campaign, documents, project_name=project_name, author=author)

    lumps: list[WadLump] = []
    for entry in campaign.entries:
        marker = validate_marker(entry.lump_name)
        lumps.append(WadLump(marker, b""))
        lumps.append(WadLump("PLANES", encode_planes_lump(by_slot[entry.slot].to_record())))
    lumps.append(WadLump(MAPINFO_LUMP, mapinfo.encode("ascii")))
    lumps.append(WadLump(MANIFEST_LUMP, manifest.encode("ascii")))

    blob = encode_wad(lumps)
    return Pack(
        wad=blob,
        manifest=manifest,
        mapinfo=mapinfo,
        audit=audit_pack(blob),
        problems=tuple(problems),
    )


def audit_pack(data: bytes) -> PackAudit:
    """Read a pack back and account for every lump in it.

    A pack is a thing an author hands to someone else, so the interesting
    question is not "did the writer behave" but "what is actually in this
    file". Anything that is not a marker, its PLANES, the MAPINFO or the
    manifest is reported by name -- that is the whole content audit, and it
    fails loudly rather than describing a file it did not understand.
    """
    from .wad import decode_wad  # local: audit is also used on foreign files

    lumps = decode_wad(data)
    markers: list[str] = []
    unexpected: list[str] = []
    metadata = 0
    map_bytes = 0

    index = 0
    while index < len(lumps):
        lump = lumps[index]
        if lump.name in (MAPINFO_LUMP, MANIFEST_LUMP):
            metadata += len(lump.data)
            index += 1
            continue
        try:
            validate_marker(lump.name)
        except ExportError:
            unexpected.append(lump.name)
            index += 1
            continue
        except Exception:
            unexpected.append(lump.name)
            index += 1
            continue
        if lump.data:
            unexpected.append(f"{lump.name} (marker is not empty)")
        following = lumps[index + 1] if index + 1 < len(lumps) else None
        if following is None or following.name != "PLANES":
            unexpected.append(f"{lump.name} (no PLANES follows it)")
            index += 1
            continue
        markers.append(lump.name)
        map_bytes += len(following.data)
        index += 2

    return PackAudit(
        markers=tuple(markers),
        lump_names=tuple(lump.name for lump in lumps),
        metadata_bytes=metadata,
        map_bytes=map_bytes,
        unexpected=tuple(unexpected),
    )


__all__ = [
    "Campaign", "CampaignEntry", "END_OF_CAMPAIGN", "GENERATOR_VERSION",
    "MANIFEST_LUMP", "MAPINFO_LUMP", "MAX_ENTRIES", "MAX_LEVEL_NAME",
    "MAX_TITLE", "Pack", "PackAudit", "Route", "STOCK_SLOTS", "audit_pack",
    "build_pack", "generate_manifest", "generate_mapinfo", "quote", "validate",
]
