# The Vorbis encoder, and the JNI door into it.
#
# The launcher rips a disc image in Java -- parsing the cue sheet, walking
# ISO 9660, pulling raw CD audio out of the binary -- because all of that is
# arithmetic and Java can seek a content:// URI without copying 316 MB first.
# The one thing Java cannot do is encode Vorbis, so that much lives here.
#
# This is deliberately its own small library rather than part of libec7wolf:
# the launcher runs in a different process from the game and has no business
# loading the engine, SDL and the touch controls in order to compress audio.

cmake_minimum_required(VERSION 3.10)

set(OGG_DIR "${CMAKE_SOURCE_DIR}/deps/ogg")
set(VORBIS_DIR "${CMAKE_SOURCE_DIR}/deps/vorbis")

if(NOT EXISTS "${VORBIS_DIR}/lib/vorbisenc.c")
	message(FATAL_ERROR
		"deps/vorbis is missing; run tools/fetch_android_deps.sh")
endif()

# libogg is compiled here too. Its own CMakeLists asks for cmake_minimum_required
# 2.8.12, which current CMake refuses outright, and it is two source files plus
# one generated header -- not worth carrying a policy override for.
#
# config_types.h is normally produced by upstream's configure step probing for
# integer widths. Android's NDK has stdint.h everywhere, so the answers are
# known and this states them rather than detecting them.
set(INCLUDE_INTTYPES_H 0)
set(INCLUDE_STDINT_H 1)
set(INCLUDE_SYS_TYPES_H 1)
set(SIZE16 int16_t)
set(USIZE16 uint16_t)
set(SIZE32 int32_t)
set(USIZE32 uint32_t)
set(SIZE64 int64_t)
set(USIZE64 uint64_t)
configure_file("${OGG_DIR}/include/ogg/config_types.h.in"
	"${CMAKE_CURRENT_BINARY_DIR}/ogg/include/ogg/config_types.h" @ONLY)

# libvorbis is compiled here rather than through its own CMakeLists, which does
# find_package(Ogg REQUIRED) and cannot see a sibling target. Everything the
# encoder needs and nothing else: vorbisfile is a decoder-side reader, and
# barkmel/psytune/tone are upstream's analysis toys with their own mains.
set(VORBIS_SOURCES
	analysis.c bitrate.c block.c codebook.c envelope.c floor0.c floor1.c
	info.c lookup.c lpc.c lsp.c mapping0.c mdct.c misc.c psy.c registry.c
	res0.c sharedbook.c smallft.c synthesis.c vorbisenc.c window.c)
list(TRANSFORM VORBIS_SOURCES PREPEND "${VORBIS_DIR}/lib/")

add_library(c7rip SHARED c7rip.c
	"${OGG_DIR}/src/bitwise.c" "${OGG_DIR}/src/framing.c"
	${VORBIS_SOURCES})

target_include_directories(c7rip PRIVATE
	"${VORBIS_DIR}/include"
	"${VORBIS_DIR}/lib"
	"${OGG_DIR}/include"
	"${CMAKE_CURRENT_BINARY_DIR}/ogg/include")

target_link_libraries(c7rip PRIVATE log)

# Upstream's own warnings are not this project's business.
target_compile_options(c7rip PRIVATE -Wno-unused-but-set-variable -Wno-unused-variable)
