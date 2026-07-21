// ===========================================================================
//
// r_glshader.cpp - GLSL compile/link helpers (renderer redesign Phase 4).
//
// ===========================================================================

#include "render/opengl/r_glshader.h"
#include "wl_def.h"
#include "zdoomsupport.h"

namespace
{
	GLuint CompileStage(GLenum type, const char *src, const char *debugName)
	{
		GLuint shader = glCreateShader(type);
		glShaderSource(shader, 1, &src, NULL);
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
