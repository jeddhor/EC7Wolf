/*
** r_glcompat.cpp
**
** See r_glcompat.h. Nothing here is interesting except on Android.
*/

#include "r_glcompat.h"

#ifdef __ANDROID__

#include <string.h>

// Reported the way the desktop path reports it: major*10 + minor, so that the
// backend's "is this new enough" test reads the same on both.
//
// GLES 3.0 is the floor. It is what this renderer needs and what every Android
// device made since about 2013 provides.
int epoxy_gl_version()
{
	const char *version = (const char *)glGetString(GL_VERSION);
	if(version == NULL)
		return 0;

	// "OpenGL ES 3.2 v1.r26p0" and similar. Find the first digit rather than
	// assuming a fixed prefix; vendors have not been consistent about it.
	while(*version && (*version < '0' || *version > '9'))
		++version;
	if(!*version)
		return 0;

	const int major = *version - '0';
	int minor = 0;
	if(version[1] == '.' && version[2] >= '0' && version[2] <= '9')
		minor = version[2] - '0';

	return major*10 + minor;
}

bool epoxy_has_gl_extension(const char *extension)
{
	if(extension == NULL || *extension == '\0')
		return false;

	// GLES 3.0 has the indexed form; the single string was removed. Asking for
	// GL_EXTENSIONS as one string returns NULL on a core context and would
	// quietly report every extension as absent.
	GLint count = 0;
	glGetIntegerv(GL_NUM_EXTENSIONS, &count);
	for(GLint i = 0;i < count;++i)
	{
		const char *name = (const char *)glGetStringi(GL_EXTENSIONS, (GLuint)i);
		if(name != NULL && strcmp(name, extension) == 0)
			return true;
	}
	return false;
}

const char *R_GLShaderPreamble(bool fragment)
{
	// The fragment stage must declare precision; the vertex stage has defaults
	// but is given the same ones so that a varying means the same thing at
	// both ends of it.
	return fragment
		? "#version 300 es\nprecision highp float;\nprecision highp int;\n"
		  "precision highp sampler2D;\nprecision highp usampler2D;\n"
		: "#version 300 es\nprecision highp float;\nprecision highp int;\n";
}

#else

const char *R_GLShaderPreamble(bool)
{
	return "#version 330 core\n";
}

#endif
