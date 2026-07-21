#ifndef __R_GLPALETTE_H__
#define __R_GLPALETTE_H__

#include <epoxy/gl.h>

// ===========================================================================
//
// GLIndexedPipeline - indexed texture + palette + colormap lookup on the GPU.
//
// Renderer redesign Phase 4/6. This is the fidelity core of the hardware
// renderer: world textures stay as 8-bit palette indices in an R8UI texture,
// and the fragment shader resolves index -> colormap[shadeRow] -> palette RGB.
// This preserves exact ECWolf palette behavior (palette cycling, full-bright,
// Corridor 7 night/infrared/electric palette rewrites) by touching only the
// palette texture, never re-uploading world art.
//
// ===========================================================================

class GLIndexedPipeline
{
public:
	GLIndexedPipeline();

	// Compile the shader and create the VAO. Returns false on shader failure.
	bool Init();
	void Shutdown();

	// Upload the 256-entry palette (256*3 bytes, RGB). Cheap; call whenever the
	// palette changes (flashes, night/infrared, cycling).
	void UploadPalette(const unsigned char *rgb256);

	// Upload a colormap table: 256 columns x rows rows of shaded indices.
	void UploadColormaps(const unsigned char *indices, int rows);

	// Create/replace an R8UI index texture from tightly packed indices.
	GLuint CreateIndexTexture(const unsigned char *indices, int w, int h);

	// Draw a fullscreen quad sampling indexTex, resolving through the palette
	// (and colormap row shadeRow when useColormap is true).
	void DrawFullscreen(GLuint indexTex, bool useColormap, int shadeRow);

	bool IsValid() const { return program != 0; }

private:
	GLuint program;
	GLuint vao;
	GLuint paletteTex;
	GLuint colormapTex;
	int    colormapRows;

	GLint uIndexTex;
	GLint uPaletteTex;
	GLint uColormapTex;
	GLint uUseColormap;
	GLint uShadeRow;
};

#endif
