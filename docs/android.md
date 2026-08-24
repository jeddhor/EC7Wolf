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

### M2 — An APK that assembles

* The launcher's CMake brought up to a modern SDK: `aapt`, `d8`, `apksigner`,
  and the `support-v4` dependency either repointed or removed.
* Manifest raised to a supported API level.
* Both ABIs packaged into one APK.

*Exit:* a gate that builds the APK and reads it back with `aapt dump badging`
-- package, version, ABIs and permissions all as intended -- and verifies the
signature with `apksigner verify`.

### M3 — It starts

* Installs on the emulator and reaches the engine rather than dying in the
  launcher.
* The C7 data placed where `argv[1]` can be pointed at it.

*Exit:* a gate that installs on the attached phone, launches, and captures a
screenshot of the Corridor 7 title screen, with logcat showing MAP01 loaded.
This is the milestone that proves the whole idea, and it proves it on hardware.

### M4 — Data, the way a person would do it

* An install path that does not involve `adb` -- the game's files have to get
  onto a phone somehow, and "push it with developer tools" is not an answer.
* Scoped storage handled properly: app-specific external storage, or the
  Storage Access Framework for picking a folder once.
* The `.pk3` shipped inside the APK rather than expected beside the data.

*Exit:* a gate that installs the APK on a clean emulator with no data pushed,
drives the in-app import, and reaches MAP01.

### M5 — Controls a person can play with

* Touch controls covering Corridor 7's verbs: move, turn, strafe, fire, open,
  weapon cycle, **visor mode**, **drop mine**, **floor map**.
* The existing control editor kept working, since it is already better than
  anything worth writing from scratch.
* Gamepad support confirmed, given `GenericAxisValues` and friends are already
  in the launcher.

*Exit:* a gate that drives synthetic touch events through `adb shell input` and
asserts, from the player trace, that each verb did what it should.

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
