# EC7Edit — E2 evidence ledger

Milestone E2: shared asset decoders and the semantic catalogue. Grades as in
[E0](e0-evidence-ledger.md): **A** proven against running code or the shipped
data, **B** owned-data fact, **C** inferred, **D** unresolved.

---

## 1. One decoder, not two

`tools/c7assets.py` promises you can drop one file beside the game data and run
it with nothing installed. That promise used to be paid for with a second copy
of every decoder inside it — and E1 had just finished measuring what two
implementations of one format cost, so leaving a third in place was not an
option.

The decoders now live once, in `ec7edit_core`, and the shipped single file is
**generated**: `scripts/build_c7assets.py` inlines the modules ahead of
`scripts/c7assets_gallery.py`, stripping relative imports because everything
lands in one namespace. Nothing else is transformed. The gate rebuilds and
diffs, so the file cannot drift, and rebuilding twice is byte-identical.

Equivalence was measured before the switch, against the retail data:

| Container | Result |
| --- | --- |
| Palette | identical, 256 entries |
| GFXTILES directory | identical offsets and lengths |
| 256 wall pages | **256/256** byte-identical RGB |
| 858 sprite pages | **858/858** byte-identical RGBA |
| 72 VGAGRAPH pictures | identical dimensions and pixels |
| 60 maps | identical planes, names, dimensions |

Grade **A**. The rebuilt gallery was then run: it serves 1246 assets and its
PNGs render.

The map codec inside it is gone too — the gallery now calls E1's
`parse_archive` through a five-line adapter rather than carrying its own RLEW.

## 2. Three findings from making the catalogue

The catalogue is generated from the engine's own translation and actor
definitions. Building it surfaced three things about the data that a
hand-written table would have quietly encoded wrong.

**A plane-0 value can be two things at once.** Value 9 both paints wall page 8
*and* is the access terminal; every door is a tile with a texture as well as a
trigger. Twelve values are both. They belong in Doors & Specials, not in the
wall palette — painting a corridor with "wall 9" would scatter working
terminals down it. This is what plan §E2's "separate ordinary wall paint from
structural/special raw codes" turns out to mean concretely.

**Transporters are zones that also teleport.** Values 279–286 are declared both
as `zone` and as `Teleport_Relative` triggers. The trigger owns the value and
the pair lives under Zones & Transporters, matching §8.6.

**The shipped maps use values the translation ignores.** Plane-1 words 86–88
configure a masked wall in the DOS engine rather than spawning anything, and
99 and 103–105 hit nothing in the executable's object switch at all. They are
not palette items — but they are *in the data*, and an editor with no entry for
them would show an imported map as having cells it could not name or put back.
They are now Raw entries marked imported-only: visible, preserved, explained,
and not offered for new work.

All three were found by a test asserting that every value in the shipped maps
resolves to exactly one entry. Before that test, all three looked fine.

## 3. The catalogue

457 entries across the tabs §8.6 defines:

| Category | Entries |
| --- | --- |
| walls | 243 ordinary materials |
| objects | 69 |
| enemies | 65 |
| zones | 31 areas and transporters |
| specials | 17 doors, switches, dispensers, exits |
| starts | 2 |
| raw | 30 imported-only |

Properties held by test:

* every raw value the translation can produce resolves to exactly one entry;
* no two entries claim the same value on the same plane;
* keys are unique and stable;
* every enemy has a sprite page, and every sprite reference is inside GFXTILES;
* generation is deterministic, and the JSON round-trips;
* the committed file matches its inputs, checked by regenerating and diffing.

Grade **A** for the join; **B** for the curated identities, which come from the
strategy compendium and the repository's own comments, each recorded with its
evidence in `resources/catalog_sources.json`.

Two identities are named outright by the engine's source rather than inferred:
`C7OrganicEye` is the Alioprobe and `C7ProbeEye` the Animated Probe
(`monsters.txt:15` and `:62`), and the access cards are settled by
`lnspec.cpp:366` mapping door argument 1 to `C7Static001` — red — and 2 to
`C7Static002` — blue.

## 4. Unresolved joins, reported not guessed

Six actors are defined in DECORATE with a sprite, are not a base class, and no
map word places them:

`C7AmmoClip`, `C7Bayonet`, `C7M16`, `C7MedicPack`, `C7ScoreBonus`,
`C7VisorBattery`.

Either they are dead weight in the pk3 or a translator entry is missing. E2
does not decide which; the gate prints them on every run so the question stays
visible. Grade **D**, owned by whoever next touches the translation.

## 5. Commercial content

No pixels are serialised anywhere. The catalogue records *which* sprite or wall
page to draw; the artwork is decoded from the user's own copy at run time,
which is exactly what makes the catalogue distributable when the artwork is
not. A test greps the committed file for image markers.

Every fixture is generated — a synthetic executable carrying a six-bit palette,
column-major wall pages, and a column-post sprite built to the documented
layout rather than captured. The sprite decodes to exactly the 768 opaque
pixels its construction implies, which is the useful kind of agreement: the
decoder matches the format, not one sample of it.

The owned-data gate asserts counts, a recomputed digest and a coverage figure —
facts about the data rather than the data itself — and compares the whole data
set's SHA-256 before and after.

## 6. Memory

`ImageCache` is an LRU bounded by **bytes**, not entries. Entry count is the
wrong unit: a 320×200 picture is fifty times a wall page, so a hundred-entry
cache is somewhere between 1 MB and 60 MB depending on what the user clicked.
Default budget 32 MB. An item larger than the whole budget is not cached at
all, since caching it would evict everything and then itself.

No disk cache. §8.5 permits a private one; E2 does not need it and an
unbounded cache of decoded retail artwork is a copy of the game with all the
licensing that implies.

## 7. What E2 did not do

No palette widgets, no thumbnail pipeline into Qt, no composite prefabs, no
disk cache. `ActorInfo.blocking` is inferred from role and is grade **C** — the
real footprint data is in the executable's static table, which E6 will need.
