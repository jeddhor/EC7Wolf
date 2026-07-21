#!/usr/bin/env bash
# Build a portable EC7Wolf Release inside an Ubuntu 20.04 container.
#
# Why 20.04?  A binary is linked against its build host's glibc.  Building on a
# very recent distro (e.g. Ubuntu 26.04) produces a binary whose required glibc
# symbol versions are too new to run on older / rolling distros (Arch, Debian
# stable, older Ubuntu).  Ubuntu 20.04 ships glibc 2.31, old enough that the
# result runs on essentially any modern desktop Linux.  The Linux build also
# uses -DNO_GTK=ON and static libstdc++/libgcc so only glibc + the SDL2/audio
# stack (present on every desktop) remain as runtime dependencies.
#
# Usage:
#   ./docker.sh --linux                 Native Linux build (SDL2 from apt)
#   ./docker.sh --windows               MinGW-w64 cross-compile for 64-bit Windows
#   ./docker.sh --linux --windows       Both
#   REBUILD_IMAGE=1 ./docker.sh --linux Force a rebuild of the builder image
#
# Outputs (each a self-contained release folder):
#   release/ec7wolf              release/ec7wolf.pk3
#   release/windows/ec7wolf.exe  release/windows/ec7wolf.pk3  release/windows/*.dll
#
# The Linux release/ folder can be fed straight to
# tools/package_corridor7_release.sh together with your legally-owned Corridor 7
# data to produce a fully playable package.

set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
IMAGE=ec7wolf-build:20.04
BUILD_LINUX=0
BUILD_WINDOWS=0

usage() {
	cat <<'EOF'
Usage: ./docker.sh [--linux] [--windows]

Build a Release EC7Wolf binary inside an Ubuntu 20.04 container.

  --linux     Native Linux build (SDL2 from apt), NO_GTK + static libstdc++
  --windows   MinGW-w64 cross-compile for 64-bit Windows

Outputs:
  release/ec7wolf
  release/ec7wolf.pk3
  release/windows/ec7wolf.exe
  release/windows/ec7wolf.pk3
  release/windows/*.dll
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--linux)   BUILD_LINUX=1 ;;
		--windows) BUILD_WINDOWS=1 ;;
		-h|--help) usage; exit 0 ;;
		*)
			printf 'unknown argument: %s\n\n' "$1" >&2
			usage >&2
			exit 2
			;;
	esac
	shift
done

if [[ $BUILD_LINUX -eq 0 && $BUILD_WINDOWS -eq 0 ]]; then
	usage >&2
	exit 2
fi

if command -v docker >/dev/null 2>&1; then
	: # use docker as-is
elif command -v podman >/dev/null 2>&1; then
	docker() { podman "$@"; }
else
	echo 'error: docker or podman is required' >&2
	exit 1
fi

# ---------------------------------------------------------------------------
# Build image
# ---------------------------------------------------------------------------
if [[ ${REBUILD_IMAGE:-0} == 1 ]] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
	echo "==> Building build image $IMAGE"
	CONTEXT=$(mktemp -d)
	cleanup_context() { rmdir "$CONTEXT" 2>/dev/null || true; }
	trap cleanup_context EXIT
	docker build -t "$IMAGE" -f- "$CONTEXT" <<'EOF'
FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
		binutils \
		build-essential \
		ca-certificates \
		cmake \
		curl \
		file \
		g++-mingw-w64-x86-64 \
		git \
		libbz2-dev \
		libjpeg-dev \
		libsdl2-dev \
		libsdl2-mixer-dev \
		libsdl2-net-dev \
		ninja-build \
		pkg-config \
		unzip \
		zlib1g-dev \
	&& rm -rf /var/lib/apt/lists/* \
	&& update-alternatives --set x86_64-w64-mingw32-gcc /usr/bin/x86_64-w64-mingw32-gcc-posix \
	&& update-alternatives --set x86_64-w64-mingw32-g++ /usr/bin/x86_64-w64-mingw32-g++-posix

# Official MinGW SDL2 development packages for the Windows cross-build.
# (This tree does not vendor the optional SDL git submodules.)
ARG SDL2_VER=2.28.5
ARG SDL2_MIXER_VER=2.6.3
ARG SDL2_NET_VER=2.2.0
RUN mkdir -p /opt/mingw-sdl && cd /tmp \
	&& curl -fsSL "https://www.libsdl.org/release/SDL2-devel-${SDL2_VER}-mingw.tar.gz" \
		| tar xz \
	&& curl -fsSL "https://www.libsdl.org/projects/SDL_mixer/release/SDL2_mixer-devel-${SDL2_MIXER_VER}-mingw.tar.gz" \
		| tar xz \
	&& curl -fsSL "https://www.libsdl.org/projects/SDL_net/release/SDL2_net-devel-${SDL2_NET_VER}-mingw.tar.gz" \
		| tar xz \
	&& cp -a "SDL2-${SDL2_VER}/x86_64-w64-mingw32/." /opt/mingw-sdl/ \
	&& cp -a "SDL2_mixer-${SDL2_MIXER_VER}/x86_64-w64-mingw32/." /opt/mingw-sdl/ \
	&& cp -a "SDL2_net-${SDL2_NET_VER}/x86_64-w64-mingw32/." /opt/mingw-sdl/ \
	&& rm -rf /tmp/SDL2-* /tmp/SDL2_mixer-* /tmp/SDL2_net-*

WORKDIR /src
EOF
	cleanup_context
	trap - EXIT
fi

# ---------------------------------------------------------------------------
# Run a build target inside the container.
#   $1 = linux|windows   $2 = host output dir (mounted at /out)
# ---------------------------------------------------------------------------
run_build() {
	local target=$1 out_host=$2
	mkdir -p "$out_host"
	echo "==> Building EC7Wolf ($target Release)"
	docker run --rm -i \
		-e TARGET="$target" \
		-e HOST_UID="$(id -u)" \
		-e HOST_GID="$(id -g)" \
		-v "$ROOT:/src:ro" \
		-v "$out_host:/out" \
		"$IMAGE" \
		bash -s <<'EOF'
set -euo pipefail

export HOME=/tmp
# git (used for the revision header) refuses to touch a tree owned by another
# user; the source is bind-mounted read-only which is fine for reads.
git config --global --add safe.directory '*'

SRC=/src
BUILD=/tmp/ec7wolf-build
rm -rf "$BUILD"
mkdir -p "$BUILD"

export CLICOLOR_FORCE=1

verify_linux() {
	local bin=$1
	local fail=0
	echo
	echo "==> Verifying $bin"
	command -v file >/dev/null 2>&1 && file "$bin"

	# Inspect the binary's *direct* DT_NEEDED entries only. The full recursive
	# ldd tree pulls in libstdc++/libgcc transitively via C++ system libraries
	# (libjack, libfluidsynth, ...), which is expected and harmless; what must
	# be static is the engine's own dependency on the C++ runtime.
	local needed
	needed=$(readelf -d "$bin" | sed -n 's/.*NEEDED.*\[\(.*\)\]/\1/p')
	echo "--- direct NEEDED ---"
	echo "$needed"

	if echo "$needed" | grep -qiE 'libstdc\+\+|libgcc_s'; then
		echo "FAIL: libstdc++/libgcc is a direct dependency (expected static)" >&2; fail=1
	else
		echo "OK: libstdc++/libgcc statically linked (not a direct dependency)"
	fi
	if echo "$needed" | grep -qi 'libgtk'; then
		echo "FAIL: depends on GTK (expected NO_GTK build)" >&2; fail=1
	else
		echo "OK: no GTK dependency"
	fi
	if echo "$needed" | grep -qi 'libSDL2-2.0'; then
		echo "OK: dynamically links system SDL2"
	else
		echo "FAIL: SDL2 not linked as expected" >&2; fail=1
	fi

	local maxglibc
	maxglibc=$(objdump -T "$bin" \
		| grep -oE 'GLIBC_[0-9]+\.[0-9]+(\.[0-9]+)?' \
		| sed 's/GLIBC_//' | sort -V | tail -n1)
	echo "Max required glibc symbol version: ${maxglibc:-none}"
	if [[ -n "$maxglibc" && "$(printf '%s\n2.31\n' "$maxglibc" | sort -V | tail -n1)" != "2.31" ]]; then
		echo "FAIL: requires glibc > 2.31 ($maxglibc)" >&2; fail=1
	else
		echo "OK: requires glibc <= 2.31"
	fi
	return $fail
}

if [[ $TARGET == linux ]]; then
	cmake "$SRC" -G Ninja -B "$BUILD/linux" \
		-DCMAKE_BUILD_TYPE=Release \
		-DNO_GTK=ON \
		-DGPL=ON \
		-DCMAKE_EXE_LINKER_FLAGS='-static-libgcc -static-libstdc++'
	# Second pass folds a freshly-generated revision header into the binary.
	cmake --build "$BUILD/linux"
	cmake --build "$BUILD/linux"

	test -f "$BUILD/linux/ec7wolf"     || { echo 'FAIL: ec7wolf not produced' >&2; exit 1; }
	test -f "$BUILD/linux/ec7wolf.pk3" || { echo 'FAIL: ec7wolf.pk3 not produced' >&2; exit 1; }
	strip "$BUILD/linux/ec7wolf"

	verify_linux "$BUILD/linux/ec7wolf" || { echo '==> Verification FAILED' >&2; exit 1; }

	rm -f /out/ec7wolf /out/ec7wolf.pk3
	install -m 755 "$BUILD/linux/ec7wolf"     /out/ec7wolf
	install -m 644 "$BUILD/linux/ec7wolf.pk3" /out/ec7wolf.pk3
else
	# Native host tools (zipdir / needexe) must be built first, then imported.
	cmake "$SRC" -G Ninja -B "$BUILD/tools" \
		-DCMAKE_BUILD_TYPE=Release -DTOOLS_ONLY=ON
	cmake --build "$BUILD/tools"

	cmake "$SRC" -G Ninja -B "$BUILD/win64" \
		-DCMAKE_BUILD_TYPE=Release \
		-DFORCE_CROSSCOMPILE=ON \
		-DIMPORT_EXECUTABLES="$BUILD/tools/ImportExecutables.cmake" \
		-DCMAKE_SYSTEM_NAME=Windows \
		-DCMAKE_C_COMPILER=x86_64-w64-mingw32-gcc \
		-DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-g++ \
		-DCMAKE_RC_COMPILER=x86_64-w64-mingw32-windres \
		-DCMAKE_FIND_ROOT_PATH='/usr/x86_64-w64-mingw32;/opt/mingw-sdl' \
		-DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER \
		-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY \
		-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY \
		-DCMAKE_PREFIX_PATH=/opt/mingw-sdl \
		-DINTERNAL_ZLIB=ON \
		-DINTERNAL_BZIP2=ON \
		-DINTERNAL_JPEG=ON \
		-DCMAKE_EXE_LINKER_FLAGS='-static-libgcc -static-libstdc++ -Wl,-Bstatic,--whole-archive -lpthread -Wl,-Bdynamic,--no-whole-archive'
	cmake --build "$BUILD/win64"
	cmake --build "$BUILD/win64"

	test -f "$BUILD/win64/ec7wolf.exe"     || { echo 'FAIL: ec7wolf.exe not produced' >&2; exit 1; }
	test -f "$BUILD/win64/ec7wolf.pk3"     || { echo 'FAIL: ec7wolf.pk3 not produced' >&2; exit 1; }
	echo
	echo "==> Verifying ec7wolf.exe"
	x86_64-w64-mingw32-objdump -f "$BUILD/win64/ec7wolf.exe" | grep -i 'file format'
	x86_64-w64-mingw32-objdump -f "$BUILD/win64/ec7wolf.exe" | grep -qi 'pei-x86-64' \
		|| { echo 'FAIL: ec7wolf.exe is not a 64-bit PE executable' >&2; exit 1; }
	echo 'OK: 64-bit PE (pei-x86-64) Windows executable'

	find /out -mindepth 1 -delete
	install -m 755 "$BUILD/win64/ec7wolf.exe" /out/ec7wolf.exe
	install -m 644 "$BUILD/win64/ec7wolf.pk3" /out/ec7wolf.pk3
	# Runtime DLLs from the MinGW SDL packages.
	cp -a /opt/mingw-sdl/bin/*.dll /out/
	ls /out/*.dll >/dev/null 2>&1 || { echo 'FAIL: no runtime DLLs copied' >&2; exit 1; }
	echo "OK: runtime DLLs present"
fi

chown -R "$HOST_UID:$HOST_GID" /out
echo
echo "Build complete. Artifacts:"
ls -la /out
EOF
}

if [[ $BUILD_LINUX -eq 1 ]]; then
	run_build linux "$ROOT/release"
fi
if [[ $BUILD_WINDOWS -eq 1 ]]; then
	run_build windows "$ROOT/release/windows"
fi

echo
echo "Done."
if [[ $BUILD_LINUX -eq 1 ]]; then
	echo "  Linux:   $ROOT/release/ (ec7wolf, ec7wolf.pk3)"
fi
if [[ $BUILD_WINDOWS -eq 1 ]]; then
	echo "  Windows: $ROOT/release/windows/ (ec7wolf.exe, ec7wolf.pk3, *.dll)"
fi
if [[ $BUILD_LINUX -eq 1 ]]; then
	echo
	echo "Package the Linux build with your Corridor 7 data:"
	echo "  tools/package_corridor7_release.sh \"$ROOT/release\" /path/to/CO7 /path/to/package"
fi
