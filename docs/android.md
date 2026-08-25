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
| `com.beloko.wolf3dhg`, Wolf3D strings and art | Another game's identity | This is EC7Wolf |
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

### M6 — It is EC7Wolf

* Package name, application id, label, and the icon set that already exists for
  five other platforms.
* The launcher's Wolf3D strings, about box and art replaced.
* Nothing left claiming to be somebody else's app.

*Exit:* the badging gate from M1 extended to assert identity, and a screenshot
of the launcher.

### M7 — Fast enough to play

* Measure the GL renderer on the phone: frame times at its real resolution,
  which is a great many more pixels than a 1994 raycaster was written for.
* Compare against the software fallback, so the choice of default is a
  measurement rather than an assumption.
* A documented resolution and scaling default that is playable.

*Exit:* a benchmark gate recording frame times at the shipped default, and a
figure written down here.

### M8 — Shipping

* A build script, and the suite extended to cover the Android build.
* README section: what it needs, how to install it, where the data goes.
* Honest limits recorded, including the API level and what that means for
  distribution.

*Exit:* the whole suite green with the Android gates in it.

---

## What is not in this plan

* **Google Play.** A targetSdk this old could not be published, and raising it
  far enough is a separate project involving scoped storage, permissions and
  privacy declarations. Sideloading is the target.
* **iOS.** Nothing in the tree suggests it, and nothing here would carry over.
* **Multiplayer on Android.** It should work -- it is the same engine over UDP
  -- but it is not what any of the gates above test, and claiming it without
  testing it would be the sort of thing this port's documentation exists to
  avoid.

## Risks, honestly

| Risk | Why it matters | What reduces it |
| --- | --- | --- |
| ~~The software renderer is too slow on a phone~~ | *Retired by M1.* The GL backend builds for GLES 3.0, so the phone's GPU does the work | -- |
| Eleven-year-old Java against a 2025 SDK | The launcher may need more than repointing; `aapt` v1 is deprecated and could vanish from a future build-tools | It builds against what is on this machine, and the fallback is `aapt2`, which is present |
| The emulator is x86_64 and phones are arm64 | A gate that passes on the emulator says nothing about the device that matters | Both ABIs are built from M0; arm64-v8a is the one that is tested on hardware, and the badging gate checks both are packaged |
| Scoped storage | The most likely place for this to become tedious | The engine takes its directory as an argument, so this is entirely a Java-side decision |
| ~~Nobody to test on real hardware~~ | *Retired before the work started.* A Galaxy S25 Ultra on Android 16 is attached over wireless debugging, so every milestone can end on the device it is meant for | -- |
| Android 16 is the newest there is | The launcher was written for Android 5. Everything between then and now -- scoped storage, runtime permissions, background limits, install-time targetSdk floors -- lands at once | Better to find out on the device than to ship for an emulator two versions behind |
