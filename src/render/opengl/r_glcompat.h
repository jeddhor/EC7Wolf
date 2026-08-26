/*
** r_glcompat.h
**
** One header so the renderer does not have to know whether it is talking to
** desktop OpenGL or to OpenGL ES.
**
** The backend was written against desktop GL 3.3 core and libepoxy. Android
** has neither: it has OpenGL ES 3.0, whose entry points are linked directly
** rather than resolved by a loader, so there is nothing for epoxy to do and no
** epoxy to do it with.
**
** The gap turned out to be very small, which is worth recording because it is
** the reason this is a header rather than a second renderer. Of the sixty-five
** distinct GL entry points the backend calls, exactly one -- glDebugMessageCallback
** -- is outside core GLES 3.0, and it is a debugging convenience. Every GLSL
** feature in use (texelFetch, usampler2D, textureSize, gl_VertexID, explicit
** attribute locations) is core GLES 3.0 as well. What differs is the spelling
** of the version directive, the need for precision qualifiers, and where the
** headers live.
*/

#ifndef __R_GLCOMPAT_H__
#define __R_GLCOMPAT_H__

#ifdef __ANDROID__

#include <GLES3/gl3.h>
#include <GLES2/gl2ext.h>

// GLES has no loader: the platform links the entry points. These two are the
// only parts of epoxy's interface the backend uses.
int epoxy_gl_version();
bool epoxy_has_gl_extension(const char *extension);

// GLES 3.0 has no debug callback -- it arrived in 3.2, and on 3.0 devices it
// is reachable only through KHR_debug. The backend uses it to print driver
// messages during development and does not depend on it.
#ifndef GL_DEBUG_OUTPUT
#define GL_DEBUG_OUTPUT 0x92E0
#endif
#ifndef GL_DEBUG_OUTPUT_SYNCHRONOUS
#define GL_DEBUG_OUTPUT_SYNCHRONOUS 0x8242
#endif

#else

#include <epoxy/gl.h>

#endif

// The preamble every shader in the backend starts with.
//
// Desktop wants "#version 330 core". GLES wants "#version 300 es" and, unlike
// desktop, requires the fragment stage to state its own precision -- there is
// no default for float in a fragment shader, and a shader that omits it does
// not compile. highp for both, because this renderer samples index textures
// and computes texture coordinates where mediump would visibly quantise.
const char *R_GLShaderPreamble(bool fragment);

#endif
