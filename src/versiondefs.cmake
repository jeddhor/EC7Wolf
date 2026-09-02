# Variables for generating version.h

set(PRODUCT_NAME "EC7Wolf")
set(PRODUCT_IDENTIFIER "org.ec7wolf.EC7Wolf")
if(APPLE OR WIN32)
	set(PRODUCT_DIRECTORY "${PRODUCT_NAME}")
else()
	string(TOLOWER "${PRODUCT_NAME}" PRODUCT_DIRECTORY)
endif()

string(TOLOWER "${PRODUCT_NAME}" ENGINE_BINARY_NAME)

# --- Save-format compatibility. NOT the product version. -------------------
#
# Leave these alone. VERSION_INTEGER is built from them in src/CMakeLists.txt
# and becomes SAVEPRODVER, which wl_loadsave.cpp compares against
# MINSAVEPRODVER (0x00100201) when loading a save. They are held at the ECWolf
# line this forked from, because renumbering them to match the product version
# below would put SAVEPRODVER at 0x00100000 -- under the minimum -- and the
# engine would refuse every save it had just written.
set(VERSION_MAJOR 1)
set(VERSION_MINOR 5)
set(VERSION_PATCH 0)

# --- The product version ---------------------------------------------------
#
# EC7Wolf has its own version, which is not ECWolf's. This tree is based on
# ECWolf 1.4.2-9-g1bff92d (18 February 2026), on upstream's 1.5.0pre line.
#
# The number after "beta" counts commits since the last major milestone of the
# original development plan -- 20ee748, "feat(corridor7): implement complete
# single-player Corridor 7 support", which closed the plan to bring Corridor 7
# to ECWolf. It therefore increases with every commit, and needs no
# maintenance. It stays a beta until that is deliberately changed here.
set(EC7WOLF_BETA_ANCHOR "20ee748cd9f45846f6002abfaf99e0a47294eb07")
# Used when there is no git to ask: a source zip, or an exported tree. Update
# it when cutting a release; CI builds from a full checkout and computes the
# real number, so this is a floor rather than the usual answer.
set(EC7WOLF_BETA_FALLBACK 209)

execute_process(
	COMMAND git rev-list --count "${EC7WOLF_BETA_ANCHOR}..HEAD"
	WORKING_DIRECTORY "${CMAKE_CURRENT_LIST_DIR}"
	RESULT_VARIABLE EC7WOLF_BETA_RESULT
	OUTPUT_VARIABLE EC7WOLF_BETA
	ERROR_QUIET
	OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(NOT "${EC7WOLF_BETA_RESULT}" STREQUAL "0" OR "${EC7WOLF_BETA}" STREQUAL "")
	set(EC7WOLF_BETA ${EC7WOLF_BETA_FALLBACK})
	message(STATUS "No git history to count from; using beta ${EC7WOLF_BETA}")
endif()

set(VERSION_STRING "1.0-beta${EC7WOLF_BETA}")
message(STATUS "${PRODUCT_NAME} ${VERSION_STRING}")
