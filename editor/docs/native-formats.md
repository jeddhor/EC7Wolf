# Corridor 7 native formats, as implemented

Every layout here was verified against the engine that loads it and, where
noted, against the 60-map archive on the CD. Offsets are decimal, all
multi-byte fields are little-endian, and `u16`/`u32` mean unsigned.

The authorities are [`file_gamemaps.cpp`](../../src/resourcefiles/file_gamemaps.cpp)
(`FGamemaps::Open`, `ValidateTed5RLEW`),
[`wolfmapcommon.cpp`](../../src/resourcefiles/wolfmapcommon.cpp)
(`FMapLump::FillCache`) and
[`gamemap_planes.cpp`](../../src/gamemap_planes.cpp) (`GameMap::ReadPlanesData`).
Where this document and those files disagree, they are right and this is a bug.

---

## 1. The archive: `MAPTEMP.CO7`

A self-contained TED5 file. Unlike Wolfenstein's `MAPHEAD`/`GAMEMAPS` pair it
holds headers and plane data together, and — this is the part that surprises
everyone who reads the field list first — **each header is followed
immediately by its own three plane streams**, not by the next header.

```
first record (46 bytes)
  0   12  "TED5v1.0.\0\0\0"
 12    8  u32 x2   absolute offsets of planes 1 and 2
 20    6  u16 x3   compressed byte length of planes 0, 1, 2
 26    4  u16 x2   width, height
 30   16  char     name
 46   ..           plane 0 stream, then plane 1, then plane 2

later record (42 bytes)
  0    4  "!ID!"
  4   12  u32 x3   absolute offsets of planes 0, 1 and 2
 16    6  u16 x3   compressed byte lengths
 22    4  u16 x2   width, height
 26   16  char     name
 42   ..           the three plane streams

terminator
       4  "!ID!"   with nothing after it
```

### The implicit first offset

The first record stores **two** plane offsets, not three. Plane 0's is not
written anywhere: its stream begins at byte 46, immediately after the header,
and the engine hardcodes exactly that:

```cpp
headers[0].PlaneOffset[0] = sizeof(first);   // 46
headers[0].PlaneOffset[1] = ReadLittleLong(&first[12]);
```

This is why the first record is 46 bytes and not the 50 that "three offsets,
three lengths, two dimensions, a name and a signature" would give. Getting it
wrong produces a header that looks right and an archive nothing can read.

### Acceptance rules

Reproduced from `FGamemaps::Open` rather than invented, because an editor that
is stricter than the engine refuses maps the game plays, and one that is looser
writes files the game rejects.

| Rule | Consequence |
| --- | --- |
| At least one map | An empty or marker-only file is refused |
| At most 100 maps | `headers[MAX_TED5_MAPS]` is a fixed array |
| `1 <= width, height <= 181` | Zero or 182 is refused |
| Plane range inside the file | `offset + length <= file size` |
| Plane 0 at or after its own header | `offset + 46` or `offset + 42` |
| Planes 1 and 2 not overlapping the previous | `start >= previous end` |
| Each stream valid RLEW of exactly `width*height*2` bytes | See below |
| File ends exactly where the last plane does | Trailing bytes are refused |

The terminator is only read when **exactly four bytes remain**. Anything else
after the last plane is the beginning of a record that is not there, and is
refused as such. An archive whose last plane ends at EOF with no terminator is
loaded by the engine and by this editor, with `C7E-NATIVE-005`; the canonical
writer always emits one.

### The name field

Sixteen bytes, fixed. Display stops at the first NUL. **The bytes after the
terminator are not always zero**: in the shipped archive, maps 47 to 50 each
carry a stray `0x31` (`'1'`) in the tail. They are probably meaningless — those
four slots are the unused ones — but an editor does not get to decide that, so
an imported name keeps all sixteen bytes and reports `C7E-NATIVE-007`. Only a
deliberate rename replaces the field, and a rename must be at most 15 printable
ASCII bytes so the terminator has somewhere to go (`C7E-NATIVE-004` otherwise).

Every other byte of both record layouts is accounted for. There are no unknown
or reserved fields.

---

## 2. RLEW

Each stored plane is a 16-bit expanded-size prefix followed by a word stream:

```
u16 expanded_bytes            width * height * 2
then, until expanded_bytes have been produced:
  w != 0xABCD                 one literal word
  0xABCD, u16 n, u16 v        n copies of v
```

A literal that happens to equal `0xABCD` has no short form and must use the
triple. The stream must end exactly as the last word is produced: the engine
checks both that the output is complete and that the input is exhausted, so
trailing words are an error rather than padding.

### The run threshold is four

A run of three words costs six bytes as a triple and six bytes as three
literals. The choice is free on size, and **the original TED5 encoder spent it
on literals**: across all 180 planes of the shipped archive it never once emits
a run shorter than four.

That is not trivia. Matching it makes a re-encode byte-identical:

| Threshold | Planes reproducing the retail bytes |
| --- | --- |
| 3 | 74 / 180 |
| **4** | **180 / 180** |
| 5 | 77 / 180 |

At threshold 4 the whole 298 090-byte archive round-trips exactly, so an
archive this editor rewrites differs from the one that shipped only where the
author actually edited it. `test_ec7edit_override.sh` asserts this on every
run. A codec that merely decoded correctly would have passed every other test
in the suite and still produced a diff on all 60 maps.

### Zero-count runs

`0xABCD, 0, v` consumes six bytes and produces nothing. The engine tolerates it
— the run loop advances the input unconditionally, so the stream still
terminates — and so does this decoder, reporting `C7E-NATIVE-006`. The writer
never emits one.

---

## 3. The `PLANES` lump (WDC 3.1)

What the engine synthesises for each archive record, and therefore what an
override has to look like.

```
  0    6  "WDC3.1"
  6    4  u32   map count (always 1)
 10    2  u16   plane count (3)
 12    2  u16   name length (16)
 14   16  char  name
 30    2  u16   width
 32    2  u16   height
 34   ..        three uncompressed planes, width*height u16 each
```

The reader seeks straight to offset 10 and never looks at bytes 6 to 9;
`FMapLump::FillCache` leaves them uninitialised. This writer puts the
documented map count there, so a byte-for-byte comparison with an
engine-produced lump is meaningful **from offset 10 onward and nowhere
earlier**.

Header size is 34 only because the name length is 16. The reader computes the
dimensions' position from the name length it just read, so the two are locked
together.

---

## 4. The preview WAD

An ordinary PWAD. The engine already exposes each archive record as a
zero-length `MAPxx` marker followed by a `PLANES` lump, and a WAD given later
on the command line wins by name, so a preview WAD is not a special format —
it is the same pair of lumps, in a file the engine loads last.

```
  0    4  "PWAD"
  4    4  u32   lump count
  8    4  u32   directory offset
 12   ..        lump data, in order, no padding
  ..   16 each  directory: u32 position, u32 size, char[8] name
```

Fixing "no padding, lumps in declaration order, directory last" is what makes
an export digest reproducible; nothing in the format requires it.

A preview holds nothing but marker/PLANES pairs. Markers are `MAP01` to
`MAP100` — the engine formats with `%02d`, which widens rather than truncates
at the hundredth slot, and `MAP100` still fits the eight-byte name field.

Loading one:

```
ec7wolf --data CO7 --tedlevel MAP01 --file preview.wad
```

---

## 5. Coordinates

Frozen in [`planes.py`](../ec7edit_core/planes.py) so nothing else has an
opinion:

* `(0, 0)` is the native top-left cell;
* `x` grows right, `y` grows down;
* the linear index is `y * width + x`;
* plane order is 0, 1, 2.

The canvas may draw compass north upward. Raw coordinates never rotate to suit
a view — the moment they do, an exported map stops matching the one on screen
in a way no test would catch.
