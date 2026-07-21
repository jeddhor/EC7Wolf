#ifndef __R_GLSHADER_H__
#define __R_GLSHADER_H__

#include <epoxy/gl.h>

// Shader helpers for the OpenGL backend (renderer redesign Phase 4).
namespace GLShader
{
	// Compile + link a program from vertex and fragment source. Returns the
	// program id, or 0 on failure (with the compiler/linker log printed).
	GLuint Build(const char *vertexSrc, const char *fragmentSrc, const char *debugName);
}

#endif
