# Android

ECWolf has an Android port. This fork has never built it, and the parts that
would are eleven years old: they target an SDK from 2015, expect a support
library that was deleted from Google's repository, and reach for SDL sources at
a path that does not exist in this tree.

Nothing about the *game* is the obstacle. The engine is ours and already knows
Corridor 7; the pieces that have rotted are all on the Android side of the
fence. This is the plan to bring them back and put Corridor 7 on a phone.

**The goal is parity.** Everything that works on desktop Linux and Windows
works on Android -- including the OpenGL renderer, which is the point of having
written it. A modern phone has a GPU that will not notice this workload; giving
it the software renderer because the port was easier that way would be a
strange thing to do on purpose.

---

## What is already true

Established by reading the tree and checking each claim against the SDK on this
machine, rather than assumed.

**The port is real and complete in outline.** `docs/changelog` records "Android
support is now merged" in ECWolf 1.3.1. `android-libs/` holds Emile Belanger's
`TouchControls` library and a stripped-down Java launcher from his Wolf3D Touch
lineage, plus `libpng`, `sigc++` and `TinyXML` for the NDK side. The top-level
`CMakeLists.txt` pulls all five in behind `if(ANDROID)`, `src/android/` carries
the JNI glue, and the launcher's own CMake assembles a real APK with
`aapt`/`d8`/`apksigner` and offers a `runadb` target that installs it, launches
it and tails logcat.

**The licence permits it.** `android-libs/launcher/License.txt` is explicit:
the front end is GPLv2, and "ECWolf and products deriving from it are allowed
to use this code under the terms of the LGPLv2.1". This fork is such a
derivative.

**The native entry point is small and already does the right thing.**
`SDL_main` in `android-jni.cpp` takes `argv[1]` as a game directory, sets it as
`HOME` and `XDG_CONFIG_HOME`, `chdir`s into it, takes `argv[2]` as the
touch-control graphics path, and hands everything after that to `WL_Main`. So
where the game data lives is a decision the Java side makes and passes in --
which is the whole of the scoped-storage problem, and means it can be solved
without touching the engine.

**The IWAD picker is generic.** `wl_iwad_picker_android.cpp` and
`NativeLib.pickIWad` present whatever list the engine hands them. Corridor 7 is
already a game this engine knows, so nothing about game *identification* should
need Android-specific work.

**The renderer has a fallback, and we are not going to use it.** Our OpenGL
backend is compiled only when desktop OpenGL and libepoxy are found, and
Android has neither -- so the probe fails, CMake warns, and the build falls
back to the software renderer. That is a good safety net and a poor
destination: the phone this is aimed at has a GPU that would not notice the
work. The backend is ported to OpenGL ES instead, in M1.

### What has rotted

| Thing | State | Why it matters |
| --- | --- | --- |
| `deps/SDL` | Missing. `android-libs/launcher/src/org/libsdl/app` is a **broken symlink** into it | This is how the SDL Java glue is kept in step with the native SDL. Vendoring SDL 2.32.10 there -- the version the desktop build already uses -- fixes the symlink and guarantees the two match |
| `minSdkVersion 14`, `targetSdkVersion 22` | Android 4.0 and 5.1, both from 2015 | NDK r27 and later refuse API levels below 21. The NDK here is r30 |
| `support-v4-13.0.0.jar` | Hardcoded to a path in the deleted `extras/android/m2repository` | The SDK here has 23.1.0 and 23.3.0 in that repository, not 13.0.0. The dependency may be removable entirely |
| `WRITE_EXTERNAL_STORAGE` + a directory chooser | Predates scoped storage | On Android 11 and later this is not how an app reads a folder of game data |
| `com.beloko.wolf3dhg`, Wolf3D strings and art | Another game's identity | **Done in M6:** `org.ec7wolf.EC7Wolf`, generated from `versiondefs.cmake` |
| Touch controls | Authored for Wolf3D's verbs | Corridor 7 adds the visor cycle, proximity mines and the floor-map panel |

### What this machine has

`aapt` (v1, which the launcher's CMake wants) survives in build-tools 34
through 37, alongside `aapt2`, `d8` and `apksigner`. NDK r30 is installed.
Platforms 34 to 36.1 are present. There is an x86_64 Android 36 system image
and a working emulator.

**And a real phone**, attached over wireless debugging: a Galaxy S25 Ultra,
`SM-S938U1`, **Android 16, SDK 36, arm64-v8a**. That makes arm64-v8a the ABI
that matters and the emulator the convenience, rather than the other way round,
and it means acceptance is a thing that can actually be done rather than
something to apologise for at the end.

It also imposes a hard constraint that settles one of the questions above.
Android has refused to *install* apps below a minimum `targetSdkVersion` since
Android 14, and the bar has risen since. A manifest declaring `targetSdkVersion
22` will not go onto this phone at all -- so raising it is not tidying, it is
the difference between having an app and not. The exact floor gets measured in
M1 rather than guessed at.

---

## Milestones

Each ends with a gate that can be run from a terminal, as the multiplayer work
did. A milestone is not done because it looks done.

### M0 — A native library — **done**

* SDL 2.32.10 vendored at `deps/SDL`, resolving the launcher's symlink.
* The engine and its bundled dependencies cross-compiling under NDK r30 for
  **x86_64** and **arm64-v8a**.
* Whatever minimum API level the NDK insists on, applied consistently.

*Exit:* a script that produces `libecwolf.so` for both ABIs from a clean tree,
and a gate that checks each one is a valid shared object for the architecture
it claims, exports `SDL_main`, and links nothing the device will not have.

**Done.** `libec7wolf.so` builds for both ABIs, 14.6MB for arm64, exporting
`SDL_main` and needing nothing the phone does not have.

Three dependencies rather than one. `LocateSDL2.cmake` wants `deps/SDL`,
`deps/SDL_mixer` and `deps/SDL_net`, so `tools/fetch_android_deps.sh` fetches
all three, pinned to exactly the versions the desktop build links -- 2.32.10,
2.8.1 and 2.2.0 -- so that a bug found on a phone can be reproduced on a
workstation rather than blamed on a version nobody wrote down. They are
gitignored: 136MB is not worth committing for one platform.

**SDL_mixer needs no external codecs at all**, which was not obvious. It stops
during configure asking for sources under `external/` that nothing fetches, and
the reflex is to run its download script and pull in ogg, vorbis, flac, mpg123,
opus and the rest. None of them are wanted here: Corridor 7's digitised sound
is decoded by the engine, its music is synthesised by the engine's OPL, and the
CD soundtrack is Ogg Vorbis -- which SDL_mixer decodes with stb_vorbis, built
in, no dependency. FLAC, Opus, MOD, WavPack, GME and MIDI are off.

Four things had to be fixed, and each was a build that stopped with a message
about something other than the actual problem:

* **The cross-compile needs a native build first.** Nothing can run `zipdir` to
  make the pk3 on the host it is not built for, so a `TOOLS_ONLY` build exports
  the host tools and the Android configure imports them. Without it CMake says
  `include could not find requested file: IMPORTFILE-NOTFOUND`, which mentions
  neither tools nor cross-compiling.
* **`std::auto_ptr`**, in the vendored sigc++ that TouchControls uses. C++17
  removed it and the NDK's libc++ does not provide it. It appears exactly once,
  taking ownership of a pointer and deleting it at the end of a scope, with no
  copying anywhere -- so `std::unique_ptr` is what it always meant. Fixed there
  rather than by pinning the whole library to C++14, since it is one line and
  nothing else in it uses a removed API.
* **`SDL_SendKeyboardKey`**, which the touch-control input path called to inject
  keys. It is internal to SDL, declared by hand in `in_android.cpp`, and
  resolved only because SDL used to be compiled into the same binary. Against
  SDL as a library it is an undefined symbol at the final link. `SDL_PushEvent`
  is the public equivalent; the only thing it does not do is update the array
  behind `SDL_GetKeyboardState`, which this engine never reads -- `id_in.cpp`
  keeps its own `Keyboard[]` and fills it from the events.
* The OpenGL backend, as predicted, finds neither desktop GL nor libepoxy,
  warns, and builds without it. **The software renderer is what runs on the
  phone**, and nothing had to be done to arrange that.

The gate checks four things per ABI, none of which is "a file appeared": the
right machine, an exported `SDL_main`, every `NEEDED` library either shipped or
present on a device, and the API level recorded in `.note.android.ident`. That
last one was written first as a pattern match on a label `llvm-readelf` does
not print, so it silently never ran -- the note is raw bytes, and the API level
is the first of them, little endian.

### M1 — The renderer, on the GPU — **done**

Parity means the OpenGL backend, not the fallback.

* The backend building against OpenGL ES 3.0.
* Desktop unaffected: the same source, the same gates, the same output.

*Exit:* the native gate asserts the Android libraries link GLES and contain the
backend, and every desktop GL gate still passes.

**Done, and it was much smaller than expected.** The measurement is the reason
to record it: of the **sixty-five distinct GL entry points** the backend calls,
exactly **one** is outside core GLES 3.0 -- `glDebugMessageCallback`, a
development aid. Every GLSL feature in use is core GLES 3.0 too: `texelFetch`,
`usampler2D`, `textureSize`, `gl_VertexID`, explicit attribute locations. There
was no rewrite to do because desktop GL 3.3 core and GLES 3.0 are, for a
renderer of this shape, the same thing wearing different headers.

What actually differed:

* **Where the headers live and who loads them.** `render/opengl/r_glcompat.h`
  includes `<GLES3/gl3.h>` on Android and `<epoxy/gl.h>` everywhere else, and
  supplies the two epoxy functions the backend uses -- `epoxy_gl_version` and
  `epoxy_has_gl_extension`. Android needs no loader at all: it links the entry
  points. The extension query has to use the indexed form, because the single
  `GL_EXTENSIONS` string was removed in GLES 3.0 and asking for it returns
  NULL, which would report every extension as absent rather than fail.
* **The version directive and precision.** Desktop wants `#version 330 core`;
  GLES wants `#version 300 es` *and* a fragment shader that states its own
  precision, since there is no default for float and a shader without one does
  not compile. Rather than fork nine shader sources, `GLShader::Build` now owns
  the preamble: it strips whatever version line a shader carried and prepends
  the right one. One place decides the dialect, and the desktop gates prove the
  change is invisible there.
* **`GL_MULTISAMPLE` does not exist in GLES**, because multisampling is a
  property of the framebuffer rather than a switch. The enable and disable are
  compiled out; an MSAA framebuffer simply resolves as one.
* **The debug callback** is compiled out on Android. KHR_debug's entry points
  are not declared by the GLES headers and would need `eglGetProcAddress`,
  which is loader machinery for a development aid -- and the `glGetError` path
  beside it already does the job.

The context request differs by three lines: `SDL_GL_CONTEXT_PROFILE_ES` and 3.0
instead of core and 3.3, with the same version test against a floor of 30
rather than 33.

The native gate now asserts both that the libraries link GLES v3 and that the
backend's symbols are present, because the fallback is silent by design: a
missing GLES library would produce a perfectly working build that had quietly
lost the renderer.

### M2 — An APK that assembles — **done**

* The launcher's CMake brought up to a modern SDK: `aapt`, `d8`, `apksigner`,
  and the `support-v4` dependency either repointed or removed.
* Manifest raised to a supported API level.
* Both ABIs packaged into one APK.

*Exit:* a gate that builds the APK and reads it back with `aapt dump badging`
-- package, version, ABIs and permissions all as intended -- and verifies the
signature with `apksigner verify`.

**Done.** 19MB, both ABIs, five native libraries each, the game data, and a
valid v1/v2/v3 signature. `tools/build_android.sh` builds it end to end.

**support-v4 was removed rather than repointed.** The launcher imported exactly
one class from it -- `FragmentActivity` -- and never used it: every fragment in
`EntryActivity` is a framework fragment (`android.app.Fragment`,
`getFragmentManager`). Extending `Activity` instead deletes the dependency, and
with it the pinned path into a repository Google deleted.

**The manifest targets 36 rather than the lowest that installs.** Android has
enforced a rising `targetSdkVersion` floor at install time since Android 14, so
22 was not merely dated -- a modern phone refuses it. Targeting just over the
floor would buy the same migration again in a year. The usual reason to stay
low is scoped storage, and that does not apply here: the game's files go in
app-specific external storage, which needs no permission on any version. So
`WRITE_EXTERNAL_STORAGE` is gone as well, since at this target it grants
nothing. `minSdk` is 21, the NDK's floor. GLES 3.0 is declared as required,
which is now true.

Four things were broken in ways that produce a *working build* and a broken
app, which is the reason the gate reads the finished archive rather than
trusting the build:

* **Three of the five native libraries were not being packaged.**
  `libec7wolf.so` needs SDL2, SDL2_mixer and SDL2_net; the packaging step
  copied only the engine and the touch controls. Nothing checks a native
  dependency until the loader goes looking for it at launch.
* **The Java asked for a library nobody builds.** `Game.java` loaded `"ecwolf"`
  and `libecwolf.so`; this fork builds `ec7wolf`. The gate now reads the name
  out of `Game.java` and checks the archive contains that, because these two
  have already disagreed once.
* **`find_file` cannot see the SDK from an NDK build.** The toolchain sets
  `CMAKE_FIND_ROOT_PATH_MODE_*` to `ONLY`, which is right for everything being
  cross-compiled and wrong for host tools: `android.jar`, `aapt`, `d8` and
  `apksigner` are all on the host. The failure arrives much later as ninja
  looking for a file called `ANDROID_SDK_JAR-NOTFOUND`. They also needed
  `NO_DEFAULT_PATH`, or the build picks up Debian's `aapt v0.2-debian` from the
  PATH instead of the one beside the `d8` it is paired with.
* **CMake caches a failed `find_file`.** A build directory first configured
  without the SDK paths keeps the `NOTFOUND` for ever, so the build script
  clears those entries before configuring.

The APK is assembled around the primary ABI and the others are added to the
archive afterwards, because CMake configures one ABI per build directory and no
single configure can see them all. Signing happens last, since adding to an
archive invalidates whatever signature was on it.

Signed with a generated debug key kept out of the repository. It exists because
Android will not install an unsigned APK; a release key is a decision for
whoever ships this.

### M3 — It starts — **done**

Corridor 7 runs on a Galaxy S25 Ultra: title screen, then MAP01 drawn by the
GL renderer at 3120x1440, with the C7 status bar over it.

Two things were in the way, and both were the same mistake seen from
different angles -- the touch controls build GL textures, and they were being
built on a thread that had no GL context.

* `Android_SetScreenSize` was called from an SDL window-event watcher, and a
  watcher runs on whichever thread pushed the event. On Android a resize comes
  from the Java main thread. The GL context belongs to the SDL thread, so the
  texture loader took a failure path and threw, and the exception unwound out
  through SDL into the JNI trampoline where there is no handler: SIGSEGV at
  `0xebad8084`, one frame of backtrace, nothing to read. `Android_SetScreenSize`
  now only records the size; `frameControls` applies it, on the SDL thread with
  the context current, inside a `try`.
* Before that, the display settling from portrait to landscape at start-up ran
  two `initControls` calls at once over shared globals -- the control list, the
  texture cache, the PNG reader's file handle. It crashed in `vsnprintf`, which
  is not where anybody would look for a threading bug. Serialised with a mutex.

The library itself was ES 1.x fixed-function code running against an ES 3.0
context (`-DUSE_GLES2`, link `GLESv2`), and `loadShader` read an uninitialised
info-log length. Fixed, but the controls are still M5's job; `frameControls`
returns early until they exist, so the engine no longer depends on them.

*Exit:* `tools/test_android_device.sh` installs on the attached phone, drives
the launcher, and checks the engine found the C7 data, chose the OpenGL
renderer, reached the game loop, loaded MAP01, drew a frame that is not black,
and crashed at no point. It skips cleanly with no phone attached.

The gate steers with `--tedlevel MAP01` through the launcher's extra-args box,
found by resource id rather than by screen position. The `Game` activity is
not exported, so that box is the only way to pass an argument in from outside
the app.

### M4 — Data, the way a person would do it — **done**

The player supplies Corridor 7 themselves, through the launcher, with no
developer tools. Both ways in are implemented and both were driven end to end
on the phone from a wiped app:

* **From a zip** -- entries are matched on their base name, so it does not
  matter what the folder inside the archive is called.
* **From a folder** -- the Storage Access Framework, walked with
  `DocumentsContract` (there is no androidx in this build). It descends up to
  three levels, because a disc is usually unpacked into a directory of its own
  and the player will point at the parent.

Both pick up the CD extras when they are alongside the game: the cinematics go
to `video/` and a ripped soundtrack to `cdaudio/`, which is where the engine
looks. A phone installed this way gets the animations and the music that this
project's own desktop install went without for weeks.

The `.pk3` was already shipping inside the APK and is copied out on launch.

**The required-file list was wrong, and the way it was wrong is worth keeping.**
It was derived from `BaseFileNames` in `wl_iwad.cpp`, which gives seven files
for Corridor 7. Import exactly those and the launcher says the data is present
and the engine then refuses to start, reporting

    Can not find base game data. (*.wl6, *.wl1, *.sdm, *.sod, *.n3d)

which names five extensions that have nothing to do with Corridor 7 and does
not name the file it actually wants. The missing file is **`CORR7CD.EXE`**:
Corridor 7 keeps its palette inside its own executable, and
`file_vswap.cpp` reads `C7PAL` out of it at offset `0x2FFC0`, trusting it only
when the file is exactly 250,776 bytes. `C7PAL` is in the iwad's `MustContain`,
so without the executable the whole install is rejected. The launcher now asks
for it by name, and says so specifically when the executable is present but is
a different build.

The launcher also refuses to start the game when data is missing, instead of
launching into a black screen with no explanation, and the first-run text no
longer tells the player to copy `*.WL6` files to `/sdcard/Beloko/`, a path that
has not existed since M2 moved to scoped storage.

The pickers open at Downloads. Left to itself the folder picker starts at the
root of storage, which the SAF refuses to grant, so the first thing the player
saw was "To protect your privacy, choose another folder" -- which reads as a
refusal rather than as an instruction to go somewhere else.

*Exit:* `tools/test_android_import.sh` clears the app, pushes a zip to
Downloads, and drives the launcher: it checks the data is reported missing,
that `CORR7CD.EXE` is named, that the game **cannot** be started, then imports,
checks the extras landed in their own directories with no `.part` files left
behind, and finally plays MAP01 with the cinematics and soundtrack found.

### M5 — Controls a person can play with — **done**

Corridor 7 is playable by hand on the phone: two sticks, fire, use, weapon
cycling, and the three verbs Wolfenstein does not have -- **visor**, **drop
mine**, **floor map**. Each one is checked by pressing it and reading the
result out of the simulation.

**The controls had never been drawn once since the renderer cutover.**
`frameControls()` was called from inside `if (UsingRenderer)` -- the SDL_Renderer
path -- and Phase 11 replaced that with the GL backend. So from the cutover
until now the overlay was not initialised and not drawn, on the one platform
with no keyboard. It is now called in the GL present path, between
`R_GLLivePresent` and `SDL_GL_SwapWindow`.

Four separate faults sat behind that, each of which produced a working-looking
build that drew nothing:

* **ES 1.x against an ES 3.0 context.** `openGLStart` set up the overlay with
  `glMatrixMode`, `glOrthof`, `glEnableClientState` and `glTexEnvf`, and the
  engine linked `GLESv1_CM`. None of that exists in the context the engine
  actually creates. The library's ES2 path bakes its vertices into clip space
  and wants no projection at all -- only the viewport, blending, and the depth
  test out of the way. The engine now links `GLESv2` and builds with
  `USE_GLES2`, so both sides resolve the same headers.
* **Thirteen non-void functions with no return**, including every control's
  `initGL`. That is undefined behaviour, clang compiles it to a trap, and the
  crash lands in `_Unwind_Resume` and the allocator -- nowhere near the cause.
  Fixed, and the library now builds with `-Werror=return-type` so it cannot
  come back.
* **Texture names invented rather than generated.** The loader counted up from
  20000 and handed the result to `glBindTexture`, which ES 2 tolerated and ES 3
  rejects with `GL_INVALID_VALUE`. It also risked colliding with the renderer's
  own textures, since the overlay now shares its context.
* **GL objects outliving their context.** Android drops a context with its
  surface; the programs and textures made before that are dead names, and
  `glUseProgram` returns `GL_INVALID_VALUE` for a program that linked perfectly.
  The overlay now notices the context has changed and rebuilds.

The overlay also saves and restores the state it touches. Leaving depth writes
disabled was enough to render the entire world black on the next frame while
the controls themselves looked perfect.

**Taps were being lost.** Touch events arrive on the event thread; the game
samples buttons once a tic. A quick tap begins and ends inside one of those
gaps and the simulation never sees it -- on a keyboard nobody presses a key for
four milliseconds, on a touchscreen that is how people press things. Each press
is now held until it has been sampled at least once.

`--capture-verbs` was added for the gate: it prints Corridor 7's verb state
whenever it changes. Screenshots cannot do this job -- the level's textures
animate on their own, so two frames of a completely idle game differ in nearly
every pixel.

**Gamepad support is not confirmed.** The bindings exist -- `wl_play.cpp` puts
Drop Mine, Visor Mode and Floor Map on pad buttons 2, 3 and 4 -- and the
launcher carries Beloko's gamepad plumbing, but there is no pad here to test
with, so this milestone claims nothing about it.

*Exit:* `tools/test_android_controls.sh` starts a level with the trace on and
presses each control in turn, asserting that firing spends ammunition, the
visor button changes visor mode, the floor map button raises the panel, the
sticks move and turn the player, and the mine button spends a mine. The mine
goes last, because a proximity mine dropped at your feet is a proximity mine
dropped at your feet.

### M6 — It is EC7Wolf — **done**

The app was somebody else's: application id `com.beloko.wolf3dhg`, label
"ECWolf", version 1.0, another game's icon, and its data in a directory called
`Wolf3d`. It is now `org.ec7wolf.EC7Wolf`, labelled EC7Wolf, versioned
`1.0-beta140` (code 140), with this project's own icon and its data in
`Corridor7`.

**The identity is generated, not written down twice.** `AndroidManifest.xml.in`
is configured from `src/versiondefs.cmake`, which is where `PRODUCT_IDENTIFIER`,
`PRODUCT_NAME` and the version already lived for the other five platforms. The
version code counts commits since the beta anchor, so it rises on its own and
never needs maintaining. The gate reads the same file, so editing one side alone
fails the build rather than shipping a mismatch.

The icon comes from the existing five-platform icon set rather than being drawn
again, and now covers xxhdpi and xxxhdpi as well -- those densities postdate this
launcher, and without them Android upscales a 96-pixel icon onto a modern screen.

**One thing deliberately not renamed:** the entry activity is still the class
`com.beloko.wolf3d.EntryActivity`. That is Beloko's launcher code, which this
fork uses and credits in the about text. Renaming the Java packages would churn
thirty-odd files, show a player nothing, and make the borrowing harder to see
rather than easier. The gate checks the application id, the label and the
launcher entry's label -- what a person actually sees -- and excludes the class
name explicitly so that the exemption is written down rather than accidental.

Changing the application id makes this a different app to Android, which is the
point: `com.beloko.wolf3dhg` may well be the ECWolf a player bought from Beloko,
and this must not install over it. It also means the data directory moves, so
the import in M4 has to be done once more after upgrading from an earlier build.

*Exit:* `tools/test_android_apk.sh` asserts the application id and label match
`src/versiondefs.cmake`, that the version is not the placeholder 1.0, that the
version code is not 1, that a launcher icon exists at every density from mdpi to
xxxhdpi, and that nothing a player sees names another app.

### M6.5 — The whole disc, ripped on the device — **done**

Point the importer at a folder holding a `.cue` and its `.bin` and it takes the
disc apart: the game data, the three cinematics the installer leaves behind, and
the soundtrack that nothing else ever copies off the disc.

**How it is put together.** The reading is Java, in `DiscImport`, because all of
it is arithmetic over a stream and a `content://` URI opened as a file
descriptor seeks -- so a 316 MB image is read in place rather than copied first.
The data track is MODE1/2352 (16 bytes of header, 2048 of data, 288 of error
correction) with ISO 9660 underneath, walked directly; the audio tracks are
already raw CD audio, so ripping them is a byte copy.

Encoding is the one thing Java has no answer for, and it is the whole reason
`android-libs/c7rip` exists: this project's SDL_mixer decodes Ogg with
**stb_vorbis**, which cannot write one. `libc7rip.so` is libogg plus the encoder
half of libvorbis plus about a hundred lines of JNI, 1.7 MB, and it is its own
small library because the launcher runs in a different process from the game and
has no business loading the engine, SDL and the touch controls to compress audio.
It streams: the longest track is 636 seconds, which is 112 MB of PCM for a file
that lands around 7 MB, and none of it is written to disc as samples.

Both dependencies are fetched, not vendored -- `tools/fetch_android_deps.sh`
takes ogg v1.3.5 and vorbis v1.3.7, both BSD-licensed. Neither is built with its
own CMakeLists: libogg's asks for `cmake_minimum_required(2.8.12)`, which current
CMake refuses outright, and libvorbis's does `find_package(Ogg REQUIRED)` and
cannot see a sibling target. Both are two dozen source files, so they are
compiled directly and `config_types.h` is written from known answers rather than
probed for.

**What is verified.** The disc arithmetic, against the real image, by mirroring
the implementation and comparing results:

* 18 files found on the data track; **all 12 that also exist in an installed copy
  are byte-identical**, and the three `SEQ*.CO7` cinematics are found at the
  right sizes.
* The audio track boundaries produce 636.080, 347.573, 183.400 and 381.653
  seconds -- **exactly** the durations recorded for the desktop rip. That is the
  pregap trap this plan warned about, and it is not present: INDEX 01 to the next
  INDEX 01 is the right span for this cue.
* `libc7rip.so` is packaged and its three JNI entry points carry names matching
  the Java class that declares them, which `test_android_apk.sh` now checks --
  a rename on either side would otherwise fail only when somebody imported a
  disc.

**Confirmed on the tablet**, by hand: a `.cue` and a `.bin` in a folder, nothing
else, and the game starts on MAP01 with the cinematics and the soundtrack
playing. The encoder's output measured `duration=183.400000` for track 7 against
a recorded 183.400 -- so the ripped audio is not merely present but the right
length to the millisecond.

**It also turned up a bug that had nothing to do with ripping.** The soundtrack
would not play, with

    Unable to load music file ./cdaudio/track03.ogg: Couldn't open '...'

while the engine's own file layer had already counted `4 of 4` in that same
directory. `Mix_LoadMUS` goes through `SDL_RWFromFile`, and **on Android a path
that does not begin with `/` is not a filesystem path at all** -- SDL hands it to
the asset manager and looks inside the APK. The engine reaches its game data
through a relative path, so every track failed to open no matter how it got
there. `SD_StartMusicFile` resolves to an absolute path now. This was never a
disc-import fault: adb-pushed soundtrack files failed exactly the same way, and
"CD audio: playing track 03" was printed on both sides of it, which is why it
went unnoticed through M4.

**A zip may hold the disc image**, which is how the disc path became testable.
The image is unpacked into the game directory first -- ISO 9660 means seeking
and a zip stream does not seek -- and removed again whether the rip works or
not. It checks for room before it starts: a few hundred megabytes on a phone
that is routinely close to full is not a safe assumption, and running out
halfway leaves a truncated image and an error from somewhere much further in.

*Exit:* `test_android_import.sh` covers both, and drives neither through the
file picker. See "Importing without the picker" below.

### Importing without the picker

Both import gates hand the archive to the app as an **intent** rather than
driving the Storage Access Framework picker.

This is not a way around the feature. "Open with EC7Wolf" is a road a player
actually takes -- a zip downloaded in a browser, a file tapped in a file manager
-- and arguably a friendlier one than hunting through a folder picker. The
launcher declares `ACTION_VIEW` and `ACTION_SEND` for zip archives and imports
whatever it is handed, disc image included.

It is also the only road a test can drive. This tablet's DocumentsUI ignores
injected input completely: not taps on rows in list or grid view, not held
presses, not `input touchscreen`, not DPAD focus plus Enter, with a fresh picker
and a fresh app, having ruled out touch filtering by an obscuring window. It
worked exactly once and never again. A gate resting on that tests Google's UI on
a good day and nothing at all on a bad one.

The one wrinkle is getting a `content://` URI from a shell script, since adb
cannot mint one. It can look one up, because a file put in Downloads is indexed
by MediaStore:

    content query --uri content://media/external/downloads --projection _id:_display_name
    am start -a android.intent.action.VIEW -t application/zip \
        -d content://media/external/downloads/<id> --grant-read-uri-permission

`--grant-read-uri-permission` is what lets the app read it.

Driving the picker itself would need a real UiAutomator instrumentation APK,
which injects through `UiAutomation` rather than `adb shell input` and is not
subject to whatever this device is doing. That is worth building the day the
picker interaction is itself the thing under test; it is not worth it to reach
code that an intent reaches directly.

### Import speed, and clearing up afterwards

**Where a disc import's time goes**, measured on the Tab S5e rather than guessed:

| phase | time |
|---|---|
| unpacking the 316 MB image out of the zip | 11.2 s |
| walking ISO 9660 and extracting the game data and cinematics | 1.3 s |
| encoding the four soundtrack tracks | **41.5 s** |

Encoding is 77% of it, and the four tracks have nothing to do with each other,
so they are encoded at once on a pool bounded by the core count. That takes a
disc import from **57-62 seconds to 26-33**. Each worker opens its own reader
over the image: a `FileChannel` has one shared position, and sharing one would
have four encoders seeking over each other.

Two things measured and kept even though they changed nothing: buffering the
copies at a megabyte and reading the data track sixty-four sectors at a time
rather than one seek and one allocation per 2352-byte sector. The extraction
they speed up is 1.3 seconds of a minute, so there was nothing there to win --
that is worth writing down so the next person does not try it again expecting
more. The progress reporting added alongside them **is** worth having: unpacking
316 MB in silence is indistinguishable from a hang, and people force-stop apps
that look hung.

**Clearing up.** After a successful import the app offers to delete what it
imported from -- a 316 MB disc image is not something to leave in Downloads.
Three routes, because which one works depends on where the file came from:

* a Storage Access Framework document, from the picker or a file manager's
  "open with": deleted outright, the app holds a grant for it;
* a MediaStore *media* item: the system asks the player itself, and that prompt
  is the confirmation;
* **a non-media file another app owns -- a zip a browser downloaded -- cannot be
  deleted at all** on Android 11 and later, read access or not. `MediaStore`
  answers `All requested items must be Media items` and there is no way round it
  short of `MANAGE_EXTERNAL_STORAGE`, which is not a permission a game should
  hold.

So the offer is honest rather than a promise: it says which of the three
happened, and when Android refuses it says so and suggests removing the file by
hand, instead of doing nothing and leaving somebody wondering whether the button
worked.

### M7 — Fast enough to play — **done**

Measured on the target: a Galaxy Tab S5e, Snapdragon 670, **Adreno 615**,
2560x1600 screen, MAP01, 400 frames.

| render resolution | ms/frame | fps | present |
|---|---|---|---|
| **640x480 (the shipped default)** | **5.8** | **172** | -- |
| 640x400 | 6.0 | 166 | 55% |
| 1280x800 | 12.9 | 78 | 76% |
| 1920x1200 | 26.2 | 38 | 85% |
| 2560x1600 (native) | 39.0 | 26 | 89% |

**The default is fine and the ceiling is not.** As shipped the game renders at
640x480 and the compositor scales that to the native window, which is 172 fps
on this tablet. Raising the render resolution to the panel's native 2560x1600
costs about seven times the frame time and lands at 26 fps. Anybody who does
that and finds the game crawling is not seeing a broken port; they are seeing a
1994 game asked to draw 64 times as many pixels as it was written for.

**Where the time goes.** `present` -- the compositor -- is 89% of a frame at
native, while the 3D world it composites costs 0.45 ms. So this is not the
renderer being slow at rendering. Each pixel of the composite does a dependent
texture fetch: an 8-bit index, then a palette lookup keyed by it. That pattern
misses the texture cache, and the miss rate rises with the size of the index
texture, which is why the cost tracks the render resolution even though the
window is always native.

That fetch cannot simply be removed. The palette is animated -- the visor, the
damage flashes, Corridor 7's rotating DAC ramp -- so the frame has to stay
indexed until the palette is applied. See [[c7-gl-filtering-msaa]] for the same
constraint in a different guise.

**What was tried, and what it was worth.** The compositor allocated two
screen-sized buffers, filled them a byte at a time, and created *and destroyed*
two GL textures, every frame. At 2560x1600 that is 8 MB of allocation and two
4 MB texture creations per frame. Making all of it persistent is worth about
**6% on the Adreno** (41.6 -> 39.0 ms) and nothing measurable on a desktop
GPU. It is kept because it removes obvious waste, not because it rescued
anything.

Two things that looked like wins and were not, both measured:

* Uploading the 8-bit layer straight from the frame buffer with
  `GL_UNPACK_ROW_LENGTH`, avoiding the packed copy entirely: **3.4 ms a frame
  slower**. The strided upload path is not the fast one.
* Uploading only the dirty rectangle of the opacity plane: **1.9 ms slower**,
  for the same reason, and the "dirty rectangle" is the view -- most of the
  screen.

Skipping the per-pixel key-test loop entirely made no measurable difference,
and skipping both texture uploads saved only 2.2 ms of the 37. The remaining
cost is the fragment work, which is why the resolution is the lever and
micro-optimising around it is not.

**Two measurement traps, both of which cost real time here.**

* **Xvfb has no GPU.** It gives llvmpipe, and a full-screen shader pass on a
  software rasteriser tells you nothing about a renderer. An A/B run under it
  showed no difference between two versions that differ by 6% on real hardware,
  because llvmpipe's fill swamped both. `tools/bench_gl.sh` uses SDL's
  `offscreen` driver, which is the real GPU with no window.
* **One run is not a measurement.** Repeats of identical code varied by 25% on
  a desktop sharing its GPU with a session -- larger than most changes worth
  making. The benchmark takes a median of several runs, and an A/B done any
  other way should be disbelieved.

*Exit:* `tools/test_gl_bench.sh` records the median frame time at the shipped
default and fails past a deliberately generous 33 ms ceiling -- the point is to
catch a structural regression, not to police tuning on whatever machine the
suite happens to run on.

### M8 — Shipping — **done**

`tools/build_android.sh` builds both ABIs into a signed APK; five gates cover
Android and run from `tools/run_gates.sh` like everything else. The README has a
route 7 that says what a device needs, how to install it, all three ways to get
the game data in, where that data lives, what the controls do, what raising the
resolution costs, how to build it, and what this port does not claim.

**Honest limits, recorded rather than glossed:**

* **Gamepads are unverified.** The bindings exist and the launcher carries
  Beloko's plumbing; nobody here has a pad. M5 claimed nothing about it and
  neither does the README.
* **Multiplayer on Android is untested.** Same engine, same UDP, the libraries
  are in the APK -- and nothing exercises it, so that is where the claim stops.
* **Deleting an imported archive is best-effort.** Android 11 and later refuse
  to let an app delete a non-media file another app owns, whatever access it was
  granted. The app says which happened instead of failing quietly.
* **The system file picker cannot be driven by the test harness** on at least
  one device. Both imports are gated through the intent route instead, which is
  a road players take anyway.
* **Debug-signed.** Fine for sideloading, and the only thing standing between
  that and a release key is somebody deciding to have one.
* **Play Protect interrupts the install.** An APK Google has never seen makes
  the device ask to upload it for a security check, *in front of* the installer
  -- so `adb install` blocks with no output until somebody looks at the tablet.
  One gate run sat on a 19 MB install for fourteen minutes before anyone did.
  `tools/android_install.sh` now answers it (with **Don't send**: a test run is
  not a reason to upload a private build to Google) and gives up after five
  minutes rather than stalling the suite. The README warns players about the
  same prompt.

*Exit:* met -- **43 passed, 0 failed, 0 skipped** on a Galaxy Tab S5e over
wireless debugging, the five Android gates contributing 76 assertions
(native 12, apk 26, device 12, controls 8, import 18).

---

## What is not in this plan

* **Google Play.** Not for the reason this plan first gave -- M6 put the
  targetSdk at 36 and M2 moved everything to scoped storage, so the technical
  barrier is gone. The remaining ones are that Play wants a developer account, a
  review and a privacy policy for an app that collects nothing, and that
  Corridor 7 is commercial software this project has no right to distribute --
  so any listing would be an empty shell that refuses to run until the player
  supplies their own copy. Sideloading is the honest model for a source port of
  a game you already own.
* **iOS.** Nothing in the tree suggests it, and nothing here would carry over.
* **Multiplayer on Android.** It should work -- it is the same engine over UDP
  -- but it is not what any of the gates above test, and claiming it without
  testing it would be the sort of thing this port's documentation exists to
  avoid.

## Risks, honestly

| Risk | Why it matters | What reduces it |
| --- | --- | --- |
| ~~The software renderer is too slow on a phone~~ | *Retired by M1.* The GL backend builds for GLES 3.0, so the phone's GPU does the work | -- |
| Eleven-year-old Java against a 2025 SDK | The launcher may need more than repointing; `aapt` v1 is deprecated and could vanish from a future build-tools | *Held so far.* It builds against build-tools 36 with `aapt` v1; the fallback is still `aapt2`, and the day v1 goes the manifest and resource steps are the only things that move |
| The emulator is x86_64 and phones are arm64 | A gate that passes on the emulator says nothing about the device that matters | Both ABIs are built from M0; arm64-v8a is the one that is tested on hardware, and the badging gate checks both are packaged |
| Scoped storage | The most likely place for this to become tedious | *It was.* Resolved in M2 and M4: app-specific storage needs no permission, and the importer exists precisely because Android 11 hid that directory from file managers |
| ~~Nobody to test on real hardware~~ | *Retired before the work started.* A Galaxy S25 Ultra on Android 16 is attached over wireless debugging, so every milestone can end on the device it is meant for | -- |
| Android 16 is the newest there is | The launcher was written for Android 5. Everything between then and now -- scoped storage, runtime permissions, background limits, install-time targetSdk floors -- lands at once | Better to find out on the device than to ship for an emulator two versions behind |
