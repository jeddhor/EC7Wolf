// ===========================================================================
//
// r_glshader.cpp - GLSL compile/link helpers (renderer redesign Phase 4).
//
// ===========================================================================

#include <string.h>

#include "wl_def.h"
#include "zdoomsupport.h"
#include "zstring.h"
#include "render/opengl/r_glshader.h"
#include "render/opengl/r_glcompat.h"

namespace
{
	GLuint CompileStage(GLenum type, const char *src, const char *debugName)
	{
		// The preamble is this file's business rather than each shader's.
		// Desktop and GLES disagree about the version directive and about
		// whether the fragment stage must state its precision, and a shader
		// carrying its own "#version 330 core" cannot compile on a phone.
		//
		// Any version line the caller left in is dropped: two of them is a
		// compile error, and #version must be the first thing in the source.
		const bool fragment = (type == GL_FRAGMENT_SHADER);
		FString source = R_GLShaderPreamble(fragment);
		const char *body = src;
		while(*body)
		{
			const char *lineEnd = strchr(body, '\n');
			const char *next = lineEnd ? lineEnd + 1 : body + strlen(body);
			while(*body == ' ' || *body == '\t')
				++body;
			if(strncmp(body, "#version", 8) != 0)
				break;
			body = next;
		}
		source += body;

		const char *sources[1] = { source.GetChars() };
		GLuint shader = glCreateShader(type);
		glShaderSource(shader, 1, sources, NULL);
		glCompileShader(shader);

		GLint ok = GL_FALSE;
		glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
		if(!ok)
		{
			char log[2048];
			GLsizei len = 0;
			glGetShaderInfoLog(shader, sizeof(log), &len, log);
			Printf("GL: %s %s shader failed to compile:\n%s\n", debugName,
				type == GL_VERTEX_SHADER ? "vertex" : "fragment", log);
			glDeleteShader(shader);
			return 0;
		}
		return shader;
	}
}

namespace GLShader
{

GLuint Build(const char *vertexSrc, const char *fragmentSrc, const char *debugName)
{
	GLuint vs = CompileStage(GL_VERTEX_SHADER, vertexSrc, debugName);
	if(!vs)
		return 0;
	GLuint fs = CompileStage(GL_FRAGMENT_SHADER, fragmentSrc, debugName);
	if(!fs)
	{
		glDeleteShader(vs);
		return 0;
	}

	GLuint prog = glCreateProgram();
	glAttachShader(prog, vs);
	glAttachShader(prog, fs);
	glLinkProgram(prog);

	// The shaders are no longer needed once linked.
	glDetachShader(prog, vs);
	glDetachShader(prog, fs);
	glDeleteShader(vs);
	glDeleteShader(fs);

	GLint ok = GL_FALSE;
	glGetProgramiv(prog, GL_LINK_STATUS, &ok);
	if(!ok)
	{
		char log[2048];
		GLsizei len = 0;
		glGetProgramInfoLog(prog, sizeof(log), &len, log);
		Printf("GL: %s program failed to link:\n%s\n", debugName, log);
		glDeleteProgram(prog);
		return 0;
	}
	return prog;
}

} // namespace GLShader
