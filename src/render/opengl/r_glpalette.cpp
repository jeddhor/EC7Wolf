// ===========================================================================
//
// r_glpalette.cpp - GPU indexed-texture / palette / colormap pipeline.
//
// Renderer redesign Phase 4/6. See r_glpalette.h.
//
// ===========================================================================

#include "render/opengl/r_glpalette.h"
#include "render/opengl/r_glshader.h"
#include "wl_def.h"
#include "zdoomsupport.h"

namespace
{
	// Attributeless fullscreen triangle from gl_VertexID.
	const char *kVertexSrc =
		"#version 330 core\n"
		"out vec2 vUV;\n"
		"void main(){\n"
		"    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));\n"
		"    vUV = p;\n"
		"    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);\n"
		"}\n";

	// index -> (optional colormap[shadeRow]) -> palette RGB. Nearest fetches
	// only; palette indices must never be linearly filtered.
	const char *kFragmentSrc =
		"#version 330 core\n"
		"in vec2 vUV;\n"
		"out vec4 fragColor;\n"
		"uniform usampler2D indexTex;\n"
		"uniform sampler2D  paletteTex;\n"
		"uniform usampler2D colormapTex;\n"
		"uniform bool useColormap;\n"
		"uniform int  shadeRow;\n"
		"void main(){\n"
		"    ivec2 isize = textureSize(indexTex, 0);\n"
		"    ivec2 texel = clamp(ivec2(vUV * vec2(isize)), ivec2(0), isize - 1);\n"
		"    uint idx = texelFetch(indexTex, texel, 0).r;\n"
		"    if(useColormap){\n"
		"        idx = texelFetch(colormapTex, ivec2(int(idx), shadeRow), 0).r;\n"
		"    }\n"
		"    vec3 rgb = texelFetch(paletteTex, ivec2(int(idx), 0), 0).rgb;\n"
		"    fragColor = vec4(rgb, 1.0);\n"
		"}\n";
}

GLIndexedPipeline::GLIndexedPipeline()
	: program(0), vao(0), paletteTex(0), colormapTex(0), colormapRows(0),
	  uIndexTex(-1), uPaletteTex(-1), uColormapTex(-1), uUseColormap(-1),
	  uShadeRow(-1)
{
}

bool GLIndexedPipeline::Init()
{
	program = GLShader::Build(kVertexSrc, kFragmentSrc, "indexed-palette");
	if(!program)
		return false;

	uIndexTex     = glGetUniformLocation(program, "indexTex");
	uPaletteTex   = glGetUniformLocation(program, "paletteTex");
	uColormapTex  = glGetUniformLocation(program, "colormapTex");
	uUseColormap  = glGetUniformLocation(program, "useColormap");
	uShadeRow     = glGetUniformLocation(program, "shadeRow");

	glGenVertexArrays(1, &vao);

	glGenTextures(1, &paletteTex);
	glBindTexture(GL_TEXTURE_2D, paletteTex);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8, 256, 1, 0, GL_RGB,
		GL_UNSIGNED_BYTE, NULL);

	glGenTextures(1, &colormapTex);
	glBindTexture(GL_TEXTURE_2D, colormapTex);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

	return true;
}

void GLIndexedPipeline::Shutdown()
{
	if(paletteTex)  { glDeleteTextures(1, &paletteTex);  paletteTex = 0; }
	if(colormapTex) { glDeleteTextures(1, &colormapTex); colormapTex = 0; }
	if(vao)         { glDeleteVertexArrays(1, &vao);     vao = 0; }
	if(program)     { glDeleteProgram(program);          program = 0; }
}

void GLIndexedPipeline::UploadPalette(const unsigned char *rgb256)
{
	glBindTexture(GL_TEXTURE_2D, paletteTex);
	glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
	glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 256, 1, GL_RGB,
		GL_UNSIGNED_BYTE, rgb256);
}

void GLIndexedPipeline::UploadColormaps(const unsigned char *indices, int rows)
{
	colormapRows = rows;
	glBindTexture(GL_TEXTURE_2D, colormapTex);
	glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_R8UI, 256, rows, 0,
		GL_RED_INTEGER, GL_UNSIGNED_BYTE, indices);
}

GLuint GLIndexedPipeline::CreateIndexTexture(const unsigned char *indices,
	int w, int h)
{
	GLuint tex = 0;
	glGenTextures(1, &tex);
	glBindTexture(GL_TEXTURE_2D, tex);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
	glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_R8UI, w, h, 0,
		GL_RED_INTEGER, GL_UNSIGNED_BYTE, indices);
	return tex;
}

void GLIndexedPipeline::DrawFullscreen(GLuint indexTex, bool useColormap,
	int shadeRow)
{
	glUseProgram(program);

	glActiveTexture(GL_TEXTURE0);
	glBindTexture(GL_TEXTURE_2D, indexTex);
	glUniform1i(uIndexTex, 0);

	glActiveTexture(GL_TEXTURE1);
	glBindTexture(GL_TEXTURE_2D, paletteTex);
	glUniform1i(uPaletteTex, 1);

	glActiveTexture(GL_TEXTURE2);
	glBindTexture(GL_TEXTURE_2D, colormapTex);
	glUniform1i(uColormapTex, 2);

	glUniform1i(uUseColormap, useColormap ? 1 : 0);
	glUniform1i(uShadeRow, shadeRow);

	glBindVertexArray(vao);
	glDrawArrays(GL_TRIANGLES, 0, 3);
	glBindVertexArray(0);
}
