# Continuous integration

`tools/run_gates.sh` is the gate suite. It is what CI runs and what you should
run locally; there is deliberately only one definition of "green".

```sh
tools/run_gates.sh                       # build dir and data dir default to builds/
tools/run_gates.sh -b build -d /path/to/co7
tools/run_gates.sh gl_ laser             # substring match: just those gates
tools/run_gates.sh --list
```

It prints one line per gate with a pass/fail and a duration, tails the log of
anything that failed, and exits non-zero if anything did.

## Why CI cannot run most of it

EC7Wolf needs the commercial Corridor 7 data files to start. They are not in the
repository and never will be, so a hosted GitHub runner has no game to drive —
and almost every gate works by driving the game and photographing the result.

The suite therefore splits, and `.github/workflows/ci.yml` has a job for each.

**`build` — runs on every push and pull request, stock `ubuntu-latest`.**
Compiles the tree and runs the gates that need no data:

* `definitions` — the source-contract check. Not a small thing: it is the gate
  that keeps catching refactors which quietly changed a measured constant, and
  it has done so three times.
* `corridor7_flic` — `--flictest` decodes a FLIC before any game data is
  opened, so the CD cinematics' decoder is gated everywhere. The animation it
  decodes is built by the test, which also computes what every frame must
  contain, so it is two implementations agreeing on the pixels rather than a
  decoder compared against its own last output.
* `installer` — the installer's core is a headless library precisely so it can
  be gated; the dependency scan, the remedy text and the default destination are
  all checked with nothing installed. Where a Corridor 7 disc image is present
  it goes further and performs a complete install, starts the game out of it,
  and uninstalls it again.
* `gl_selftest` — `--gltest` is handled before the IWAD is opened, so it runs
  with no game at all. It creates a GL 3.3 core context, compiles the shaders,
  and verifies all 256 palette indices resolve to the exact RGB. Worth having
  because **a broken shader still links** — nothing else in a data-free build
  would notice.

The build step runs `cmake --build` twice on purpose: `gitinfo.h` is regenerated
after `gitinfo.cpp` compiles, so a single pass embeds the previous commit's
version string.

**`gates` — the whole suite, on a self-hosted runner that owns the data.**
Never scheduled unless such a runner exists, so the workflow still goes green on
the build job alone. This is the job that runs determinism, GL parity, the
visibility superset check and the rest.

## Registering the data-carrying runner

On a machine that has the Corridor 7 files, from the repository's Settings →
Actions → Runners → New self-hosted runner, then:

```sh
./config.sh --url https://github.com/<owner>/EC7Wolf \
            --labels self-hosted,corridor7-data
```

The `corridor7-data` label is what the `gates` job selects on. Then turn the job
on:

```sh
gh variable set HAVE_CORRIDOR7_RUNNER --body true
```

That switch is not redundant with the label. A job whose labels match no
registered runner is **not skipped** — it queues forever and its check never
reports, which is worse than not having the job at all. The variable is what
keeps the workflow honest before a runner exists.

Give the runner the data path in its environment — in `.env` beside `run.sh`, or
in the service unit:

```sh
CORRIDOR7_DATA=/path/to/corridor7/data
```

That path never enters the repository. The job passes `--require-data`, so a
runner that has lost its data fails rather than reporting a green run that
quietly tested nothing.

The runner also needs the same packages the hosted job installs, plus a working
GL: `xvfb`, `x11-utils`, `imagemagick`, `python3`, `libgl1-mesa-dri`. (`x11-utils`
supplies `xdpyinfo`, which the gates that manage their own display use to wait
for it — there is a fallback, but without it that wait is a guess again.) Software rendering
(llvmpipe) is fine and is what the numbers in the phase documents were measured
on; a real GPU is faster but not required.

## What a full run costs

About twenty minutes on this hardware, dominated by the gates that capture many
frames — `gl_parity`, `gl_visibility`, `corridor7_invulnerability` and
`corridor7_release_startup`. Run a subset by name while iterating and the whole
suite before pushing.

## Cutting a release

`.github/workflows/release.yml` runs on a `v*` tag. It builds the engine for
Linux x64, Linux arm64 and Windows x64, freezes the Windows installer, packages
the source and the standalone installer -- and builds the **Android APK**, which
is published alongside the desktop downloads as `EC7Wolf-<version>-android.apk`.

The Android job is the only one that cross-compiles. It installs a JDK and the
host tools, fetches SDL and the Vorbis encoder with
`tools/fetch_android_deps.sh`, runs `tools/build_android.sh` for both ABIs, and
then runs `tools/test_android_apk.sh` against what came out. That gate is the
reason the job exists rather than a bare build step: it is the check that both
architectures are present, that every native library made it into the archive,
and that the thing is signed. It exits 0 when it decides to skip, so the job
greps its output for `SKIP` and fails -- an unchecked APK must not reach a
release wearing a green tick.

**Signing.** Set `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASS` and
`ANDROID_KEYSTORE_ALIAS` as repository secrets and every release is signed with
the same key, so players upgrade in place. Without them the build generates a
throwaway key: the APK works, but the next release will not install over it, and
uninstalling to get past that deletes the player's imported game data along with
the app. The workflow passes which of the two happened through to the release
notes rather than leaving anyone to find out.

No artifact contains game data, and the publish job proves it before creating
the release -- including inside the APK, which is a zip that `dist/*.zip` does
not match.
