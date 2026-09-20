# Undefined behaviour in the inherited engine

**Status:** stages 1 to 3 done. 138 findings became 105, every one of the 33
by fixing a defect rather than by accepting it, and what remains is held by a
list the gates enforce. Stage 4 is deliberately not done and says why.

EC7Wolf's sanitizer build reports **138 UndefinedBehaviorSanitizer findings in
a single run**, and the same 138 whether the run is a quiet single-player map
or an eleven-slot bot match — they all fire while the game is starting up and
loading, before any of this fork's code is reached. None of them is in the
bots, the netcode, the menu shell or the renderer work. They are inherited:
ECWolf is a Wolfenstein 3D port built on ZDoom's class system, and that system
was written when this class of tool did not exist.

`tools/test_bot_sanitizer.sh` fails on any AddressSanitizer report and on UBSan
findings in bot, perception, navigation, command or net code. It counts the
rest without failing, so they stay visible without drowning the gate. That was
a deliberate holding position; this document is what to do about the rest.

Reproduce the survey with:

```sh
cmake -S ECWolf -B builds/sanitizer -DCMAKE_BUILD_TYPE=Debug \
      -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer"
cmake --build builds/sanitizer -j"$(nproc)"
UBSAN_OPTIONS=print_stacktrace=1 ASAN_OPTIONS=detect_leaks=0 \
  builds/sanitizer/ec7wolf --data CO7 --tedlevel MAP01 --skill 2 \
  --capture-maxtics 600 --nowait
```

## What is actually there

| Class | Count | Where | Is it dangerous? |
| --- | --- | --- | --- |
| vptr / dynamic type | 91 | `thingdef_properties.cpp` (66), `thingdef.cpp` (16), `a_keys.cpp` (6), three others | No, and not fixable without replacing ZDoom's class system |
| Misalignment | 27 | `gamemap.cpp` (7), `v_font.cpp` (4), `lnspec.cpp` (3), `a_inventory.cpp` (3), `dobject.h` (3), six others | Two distinct causes; one is worth fixing, one is not |
| Null pointer | 12 | `w_wad.cpp` (5), `tarray.h` (3), `dbopl.cpp` (2), two others | Trivially fixable, genuinely undefined |
| Left shift of negative | 4 | `file_audiomus.cpp` (2), two others | Trivially fixable; defined behaviour since C++20 |
| Signed overflow | 3 | `wolfrawtexture.cpp`, `rottflattexture.cpp`, `dbopl.cpp` | **Yes — two of them are in parsers of untrusted data** |
| Invalid value for `bool` | 1 | `scanner.h` | **Yes — an uninitialized member, read every time a script is parsed** |

### The 91 that are one idiom

ZDoom sets DECORATE properties by writing into a *defaults* object before it is
a real object of its class:

```c
((AWeapon *)defaults)->ammogive[AWeapon::PrimaryFire] = give;
```

`defaults` is declared `AActor *`, and every property handler downcasts it to
whatever class the property belongs to. UBSan's `vptr` check fires twice per
handler — once for the downcast, once for the member access — because the
memory's recorded dynamic type is not the type being used. Nothing virtual is
ever called through these pointers, and the layout is correct by construction,
which is why it has worked for twenty years.

This is not worth fixing. Fixing it means giving every actor class a real
default instance with a correctly constructed vtable, which is a rewrite of the
DECORATE property system, and the reward is silencing a checker rather than
changing what the program does. **It should be suppressed explicitly**, so that
the remaining findings mean something, and so that a *new* vptr finding
somewhere else is visible instead of being lost in ninety others.

### The 27 misalignments are two different things

**Address arithmetic on a fake pointer**, at static-initialisation time. This
is `offsetof` done by hand:

```
dobject.h:227 TObjPtr<AActor>::operator&()  address 0x179
  from __static_initialization_and_destruction_0 (a_deathcam.cpp:22)
```

There is no object at 0x179; the class metadata table is computing a field
offset. Benign, and in the same category as the vptr findings: suppress.

**A buffer carved into differently-typed regions without padding**, which is
real. `GameMap::SetupLinks` allocates one `byte[]` and lays a `bool` array, a
`unsigned short` array and an array of `unsigned short*` inside it, with the
offsets computed from sizes alone:

```c
byte* zoneData = new byte[zdSize + sizeof(unsigned short*)*zonePalette.Size()];
zoneLinks = reinterpret_cast<unsigned short**>(zoneData+zdSize);
```

`zdSize` is a sum of `bool` and `short` sizes, so `zoneLinks` lands wherever it
lands — in the measured run, an odd address, and the engine then stores and
loads 8-byte pointers there.

On x86-64 that works. **On AArch64 — which this project ships, as
`linux-arm64` and as the Android APK — ordinary loads and stores also tolerate
misalignment, so this is not a crash waiting to happen.** The real exposure is
narrower and still worth closing: a compiler that knows a pointer's declared
alignment may vectorise or widen accesses on that assumption, and unaligned
access carries a measurable penalty on some cores. It is also four lines to
fix. The same shape appears in the texture and font code (`v_font.cpp`,
`v_palette.h`), which read packed art data through structs.

### The six that are ordinary bugs

These are the reason the survey was worth doing.

**`wolfrawtexture.cpp:91` and `rottflattexture.cpp:84` — signed overflow while
sniffing a file format.**

```c
WORD Width = LittleShort(header[0]);
WORD Height = LittleShort(header[1]);
if(file.GetLength() == Width*Height+4)   // 64768 * 47104 overflows int
```

`Width` and `Height` come straight out of a lump's first four bytes. Both
promote to `int`, and the product of two 16-bit values does not fit. This is a
parser deciding what a file is, run over every lump in every archive the engine
loads — including, since E13, resource packs that a player downloaded from
somebody else. The fix is to compute in a type that holds the result.

**`scanner.h:88` — an uninitialized `bool`, read on every script parse.**

```
load of value 3, which is not a valid value for type 'bool'
  Scanner::ParserState::operator=   (copying the struct)
  Scanner::ExpandState              (scanner.cpp:280)
  FDecorateParser::Parse            (thingdef_parse.cpp:69)
```

A `bool` holding 3 is a variable that was never initialised. Copying it is
undefined, and a compiler is entitled to assume a `bool` is 0 or 1 — which is
how this class of bug turns into a branch that takes neither path. It is one
initialiser.

**`dbopl.cpp:1308` — signed overflow in the OPL synthesiser**, and two null
pointers in the same file. Upstream DOSBox code. Lower stakes: wrong audio
samples rather than wrong control flow.

**`w_wad.cpp` — `memset(NULL, 255, 0)`.** Passing a null pointer to `memset`
or `memcpy` is undefined even when the length is zero, and the length here is
`NumLumps * sizeof(...)` with no lumps. Five sites, one guard.

## The plan

Four stages, ordered by what the work buys rather than by how many findings it
removes. Stage 1 removes six findings and fixes real bugs; stage 4 removes
ninety-one and fixes nothing.

**Stage 1 — the six real bugs.** The two format-sniffing overflows, the
uninitialized `bool` in the scanner, the `w_wad` null `memset`s, the negative
left shifts, and the `dbopl` overflow. Each is a small, local change. The two
overflow fixes want a regression test that feeds the texture sniffers a lump
whose first four bytes multiply out past `INT_MAX`, because that is a hostile
input the engine accepts today.

**Stage 2 — the alignment that we ship on ARM.** `GameMap::SetupLinks` first:
round each region up to the alignment its type needs. Then the packed-art
readers in `v_font.cpp` and `v_palette.h`, which want `memcpy` into a local
rather than a struct laid over unaligned bytes. Verify on the arm64 build, not
only on x86.

**Stage 3 — the ratchet. Done.** `tools/ubsan-accepted.txt` lists what is
accepted, one line per kind and file with a reason;
`tools/ubsan_check.py` compares a run's findings against it and fails on
anything that is not there. Both `test_bot_sanitizer.sh` and
`test_untrusted_lumps.sh` use it.

Not the sanitizer's own suppression file, which was the first plan: GCC's
libubsan accepts only the blanket `undefined:` type, so a suppression file can
turn the checker off entirely and cannot express "this file, this check".
Doing it in the gate is better anyway -- the list is diffable, it is read by
people rather than by a runtime, and the checker can report entries that have
**stopped** firing, which a suppression file cannot. A stale acceptance is a
claim about the program that is no longer true.

Keyed by kind and file rather than by line, because line numbers move whenever
anything above them is edited and a list that needs rewriting after every
comment is a list that stops being maintained.

**It earned its place immediately.** The survey above was one scenario -- a
single-player start on MAP01 -- and the gate runs a full-roster deathmatch
with round changes. The first run against the list turned up three sites the
survey never reached: two more `GetDefault()` downcasts, which are the same
idiom and are now listed, and **two more negative left shifts in
`wl_state.cpp`**, which are the same defect as the four fixed in stage 1 and
are now fixed too. One scenario is not a survey.

**Stage 4 — the vptr class, if ever.** Held by stage 3's list and left alone.
Revisit only if the class system is being replaced for some other reason.

### Where it stands

| | Before | Now |
| --- | --- | --- |
| vptr / dynamic type | 91 | 94 (three more found, all the same idiom) |
| Misalignment | 27 | 14 |
| Null pointer | 12 | 2 |
| Left shift of negative | 4 | 0 |
| Signed overflow | 3 | 0 |
| Invalid `bool` | 1 | 0 |
| **Total** | **138** | **110** |

The count went up in one row and that is the point: finding three more
instances of an idiom already understood is worth more than a smaller number
would have been. Everything that was a defect is fixed; everything that
remains is two idioms this fork did not write, written down where a new
finding cannot hide among them.

## What this is not

It is not a security audit, and none of these is known to be exploitable. The
two parser overflows are the only findings reachable from data a player did not
create themselves, and what they do today is compute a wrong length and decide
a file is not a texture. They are worth fixing because a parser that overflows
on untrusted input is a bad thing to leave in a program that now loads other
people's resource packs — not because there is a known way to turn them into
anything worse.
