cmake_minimum_required( VERSION 3.6.0...3.27.0 )

# xBRZ 1.8 by Zenju, vendored unmodified from the copy shipped with the BStone
# source port (which carries the upstream 1.8 release with only encoding and
# C++14 compatibility fixes). See License.txt: xBRZ is GPL-3, and combining it
# with this engine's GPL-2+ code makes the resulting binary GPL-3.
#
# Built as its own target so upstream's warnings stay out of the engine build
# and so the file is never accidentally reformatted alongside engine sources.

add_library( xbrz STATIC
	xbrz.cpp
)

set_target_properties( xbrz PROPERTIES
	CXX_STANDARD 17
	CXX_STANDARD_REQUIRED ON
)

target_include_directories( xbrz PUBLIC
	${CMAKE_CURRENT_SOURCE_DIR}
)
