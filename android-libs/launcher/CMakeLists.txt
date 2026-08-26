find_package(Java REQUIRED)
include(UseJava)

set(APK_OUTPUT "${CMAKE_BINARY_DIR}/${ENGINE_BINARY_NAME}.apk")
# The application id, and everything else a phone shows about this app, comes
# from src/versiondefs.cmake. The manifest is generated from it so the two
# cannot drift: this used to say com.beloko.wolf3dhg, with a label of "ECWolf"
# and a version of 1.0, none of which was true.
set(APK_PACKAGE_NAME "${PRODUCT_IDENTIFIER}")
# Monotonic, and free: it counts commits since the beta anchor, so it rises
# with every commit and never needs maintaining. Android only requires that it
# increases between releases.
set(ANDROID_VERSION_CODE "${EC7WOLF_BETA}")
set(ANDROID_MANIFEST "${CMAKE_CURRENT_BINARY_DIR}/AndroidManifest.xml")
configure_file(AndroidManifest.xml.in "${ANDROID_MANIFEST}" @ONLY)
set(APK_ENTRY_ACTIVITY "com.beloko.wolf3d.EntryActivity")

set(ANDROID_SDK "ANDROID_SDK-NOTFOUND" CACHE PATH "Path to android.jar")
set(ANDROID_SDK_TOOLS "ANDROID_SDK_TOOLS-NOTFOUND" CACHE PATH "Path to android build-tools")
if(ANDROID_SDK STREQUAL "ANDROID_SDK-NOTFOUND" OR ANDROID_SDK_TOOLS STREQUAL "ANDROID_SDK_TOOLS-NOTFOUND")
	message(FATAL_ERROR "Please set ANDROID_SDK to location of android.jar and ANDROID_SDK_TOOLS to build-tools for the platform")
endif()

# NO_DEFAULT_PATH and NO_CMAKE_FIND_ROOT_PATH on every one of these.
#
# NO_DEFAULT_PATH so they come from the SDK that was pointed at rather than
# from whatever the distribution installed: Debian ships an "aapt v0.2-debian"
# on the PATH, and that is a different build of a tool whose output has to
# match the d8 and apksigner beside it.
#
# The NDK toolchain file sets CMAKE_FIND_ROOT_PATH_MODE_* to ONLY, which is
# right for everything being cross-compiled: a find_library must not pick up
# the host's copy. But these are host tools and host jars, and re-rooting the
# search into the NDK sysroot means they can never be found however correct the
# path handed in is. The failure surfaces much later and says nothing useful --
# ninja looking for a file literally called "ANDROID_SDK_JAR-NOTFOUND".
find_file(ANDROID_SDK_JAR android.jar PATHS "${ANDROID_SDK}" NO_DEFAULT_PATH NO_CMAKE_FIND_ROOT_PATH)
find_file(ANDROID_AAPT_BINARY NAMES aapt aapt.exe PATHS "${ANDROID_SDK_TOOLS}" NO_DEFAULT_PATH NO_CMAKE_FIND_ROOT_PATH)
find_file(ANDROID_D8_BINARY NAMES d8 d8.exe PATHS "${ANDROID_SDK_TOOLS}" NO_DEFAULT_PATH NO_CMAKE_FIND_ROOT_PATH)
find_file(ANDROID_ADB_BINARY NAMES adb adb.exe PATHS "${ANDROID_SDK_TOOLS}" "${ANDROID_SDK_TOOLS}/../../platform-tools" NO_DEFAULT_PATH NO_CMAKE_FIND_ROOT_PATH)
find_file(ANDROID_APK_SIGNER NAMES apksigner apksigner.exe PATHS "${ANDROID_SDK_TOOLS}" NO_DEFAULT_PATH NO_CMAKE_FIND_ROOT_PATH)
# support-v4 is gone from here entirely. It was pinned to 13.0.0 in a
# repository Google deleted, and the one class the launcher imported from it --
# FragmentActivity -- was never actually used: EntryActivity's fragments are
# all framework fragments. See the note in EntryActivity.java.

set(ANDROID_SIGN_STOREPASS "" CACHE STRING "Keystore password for jarsigner")
set(ANDROID_SIGN_KEYSTORE "" CACHE FILEPATH "Keystore name for jarsigner")
set(ANDROID_SIGN_KEYNAME "" CACHE STRING "Key name for jarsigner")

set(CMAKE_JAVA_COMPILE_FLAGS -target 8 -source 8 -encoding UTF-8 -Xlint:-options ${CMAKE_JAVA_COMPILE_FLAGS})

add_subdirectory(src)

add_custom_target(runadb
	COMMAND "${ANDROID_ADB_BINARY}" install -r "${APK_OUTPUT}"
	COMMAND "${ANDROID_ADB_BINARY}" shell am start "${APK_PACKAGE_NAME}/${APK_ENTRY_ACTIVITY}"
	COMMAND "${ANDROID_ADB_BINARY}" shell logcat
	DEPENDS engine-android
	WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
	COMMENT "Launching apk via adb..."
)
