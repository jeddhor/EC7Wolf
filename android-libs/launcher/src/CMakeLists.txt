add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/com/beloko/idtech/R.java"
	COMMAND "${ANDROID_AAPT_BINARY}" package -m -J ${CMAKE_CURRENT_BINARY_DIR} -M ../AndroidManifest.xml -S ../res -I "${ANDROID_SDK_JAR}" --custom-package com.beloko.idtech
	DEPENDS ../AndroidManifest.xml ../res
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
	COMMENT "Generating resources"
)

add_jar(engine-android
	${CMAKE_CURRENT_BINARY_DIR}/com/beloko/idtech/R.java
	com/beloko/idtech/wolf3d/Game.java
	com/beloko/idtech/wolf3d/NativeLib.java
	com/beloko/idtech/AboutDialog.java
	com/beloko/idtech/ActionInput.java
	com/beloko/idtech/AlphanumComparator.java
	com/beloko/idtech/AppSettings.java
	com/beloko/idtech/CDAudioPlayer.java
	com/beloko/idtech/DirectoryChooserDialog.java
	com/beloko/idtech/GameDataImport.java
	com/beloko/idtech/GamePadFragment.java
	com/beloko/idtech/GD.java
	com/beloko/idtech/GenericAxisValues.java
	com/beloko/idtech/IntroDialog.java
	com/beloko/idtech/NoticeDialog.java
	com/beloko/idtech/OptionsFragment.java
	com/beloko/idtech/QuakeControlConfig.java
	com/beloko/idtech/QuakeControlInterface.java
	com/beloko/idtech/QuakeControlInterpreter.java
	com/beloko/idtech/QuakeCustomCommands.java
	com/beloko/idtech/QuakeQuickCommand.java
	com/beloko/idtech/QuakeTouchControlsSettings.java
	com/beloko/idtech/ShowKeyboard.java
	com/beloko/idtech/SingleMediaScanner.java
	com/beloko/idtech/TouchControlsEditing.java
	com/beloko/idtech/Utils.java
	com/beloko/wolf3d/AboutDialog.java
	com/beloko/wolf3d/Advert.java
	com/beloko/wolf3d/EntryActivity.java
	com/beloko/wolf3d/LaunchFragment.java
	com/mobeta/android/dslv/DragSortController.java
	com/mobeta/android/dslv/DragSortCursorAdapter.java
	com/mobeta/android/dslv/DragSortItemView.java
	com/mobeta/android/dslv/DragSortItemViewCheckable.java
	com/mobeta/android/dslv/DragSortListView.java
	com/mobeta/android/dslv/ResourceDragSortCursorAdapter.java
	com/mobeta/android/dslv/SimpleDragSortCursorAdapter.java
	com/mobeta/android/dslv/SimpleFloatViewManager.java
	org/libsdl/app/HIDDeviceBLESteamController.java
	org/libsdl/app/HIDDevice.java
	org/libsdl/app/HIDDeviceManager.java
	org/libsdl/app/HIDDeviceUSB.java
	org/libsdl/app/SDL.java
	org/libsdl/app/SDLActivity.java
	org/libsdl/app/SDLAudioManager.java
	org/libsdl/app/SDLControllerManager.java
	org/libsdl/app/SDLSurface.java
	INCLUDE_JARS
		"${ANDROID_SDK_JAR}"
)

add_dependencies(engine-android engine touchcontrols pk3)

add_custom_command(TARGET engine-android POST_BUILD
	# Every shared library the engine needs, not just the two this used to
	# copy. libec7wolf.so has SDL2, SDL2_mixer and SDL2_net in its NEEDED list;
	# an APK without them installs happily and then dies at launch, because
	# nothing checks a native dependency until the loader goes looking for it.
	COMMAND "${CMAKE_COMMAND}" -E copy_if_different "$<TARGET_FILE:engine>" "${CMAKE_CURRENT_BINARY_DIR}/lib/${CMAKE_ANDROID_ARCH_ABI}/$<TARGET_FILE_NAME:engine>"
	COMMAND "${CMAKE_COMMAND}" -E copy_if_different "$<TARGET_FILE:touchcontrols>" "${CMAKE_CURRENT_BINARY_DIR}/lib/${CMAKE_ANDROID_ARCH_ABI}/$<TARGET_FILE_NAME:touchcontrols>"
	COMMAND "${CMAKE_COMMAND}" -E copy_if_different "$<TARGET_FILE:SDL2>" "${CMAKE_CURRENT_BINARY_DIR}/lib/${CMAKE_ANDROID_ARCH_ABI}/$<TARGET_FILE_NAME:SDL2>"
	COMMAND "${CMAKE_COMMAND}" -E copy_if_different "$<TARGET_FILE:SDL2_mixer>" "${CMAKE_CURRENT_BINARY_DIR}/lib/${CMAKE_ANDROID_ARCH_ABI}/$<TARGET_FILE_NAME:SDL2_mixer>"
	COMMAND "${CMAKE_COMMAND}" -E copy_if_different "$<TARGET_FILE:SDL2_net>" "${CMAKE_CURRENT_BINARY_DIR}/lib/${CMAKE_ANDROID_ARCH_ABI}/$<TARGET_FILE_NAME:SDL2_net>"
	COMMAND "${CMAKE_COMMAND}" -E copy_directory "${CMAKE_CURRENT_SOURCE_DIR}/../assets" "${OUTPUT_DIR}/assets"
	COMMAND "${ANDROID_AAPT_BINARY}" package -f $<$<CONFIG:Debug>:--debug-mode> -M "${CMAKE_CURRENT_SOURCE_DIR}/../AndroidManifest.xml" -S "${CMAKE_CURRENT_SOURCE_DIR}/../res" -A "${OUTPUT_DIR}/assets" -I "${ANDROID_SDK_JAR}" -F "${APK_OUTPUT}"
	COMMAND "${ANDROID_D8_BINARY}" $<$<CONFIG:Release>:--release> $<$<CONFIG:MinSizeRel>:--release> --output . --lib "${ANDROID_SDK_JAR}"
		"engine-android.jar"
	COMMAND "${ANDROID_AAPT_BINARY}" add -f "${APK_OUTPUT}" "classes.dex" "lib/${CMAKE_ANDROID_ARCH_ABI}/*"
	COMMAND "${ANDROID_APK_SIGNER}" sign --ks-pass "pass:${ANDROID_SIGN_STOREPASS}" --ks "${ANDROID_SIGN_KEYSTORE}" --ks-key-alias "${ANDROID_SIGN_KEYNAME}" "${APK_OUTPUT}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
	COMMENT "Creating APK ${ENGINE_BINARY_NAME}.apk"
)
