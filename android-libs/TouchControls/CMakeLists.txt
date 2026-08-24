cmake_minimum_required( VERSION 3.6.0...3.27.0 )

add_library(touchcontrols SHARED
    Button.cpp
    ControlSuper.cpp
    GLLines.cpp
    GLRect.cpp
    JNITouchControlsUtils.cpp
    Mouse.cpp
    MultitouchMouse.cpp
    OpenGLUtils.cpp
    RectF.cpp
    TouchControls.cpp
    TouchControlsContainer.cpp
    TouchJoy.cpp
    WheelSelect.cpp
)

# USE_GLES2 selects the shader path, and it is not optional here.
#
# Without it this library uses the OpenGL ES 1.x fixed-function pipeline --
# glVertexPointer, glTranslatef, glEnable(GL_TEXTURE_2D) -- through
# libGLESv1_CM. The engine's renderer creates an ES 3.0 context, and ES 3.0 is
# backward compatible with ES 2.0 but not with ES 1.x: those entry points do
# not exist in it. The result was a segmentation fault inside the first texture
# load, which reads as a bug in the PNG loader and is nothing of the kind.
target_compile_definitions(touchcontrols PRIVATE -DANDROID_NDK -DUSE_GLES2)

target_include_directories(touchcontrols PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}" "${LIBPNG_INCLUDE_DIR}")
message("->${CMAKE_CURRENT_SOURCE_DIR} ->${LIBPNG_INCLUDE_DIR}")

target_link_libraries(touchcontrols PUBLIC EGL GLESv2 log sigc++ TinyXML ${LIBPNG_LIBRARY})
 
