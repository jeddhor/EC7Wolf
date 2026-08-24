#ifndef __R_GLDEVICE_H__
#define __R_GLDEVICE_H__

#include "render/opengl/r_glcompat.h"
struct SDL_Window;
typedef void *SDL_GLContext;

// ===========================================================================
//
// GLDevice - SDL OpenGL window + context ownership (renderer redesign Phase 4).
//
// Owns the GL context and the presentation surface. Kept independent of the
// game's 2D framebuffer so the OpenGL backend can bring up and validate the
// core GPU pipeline (indexed textures, palette lookup) before the full window
// ownership refactor that Phases 5/10 require.
//
// ===========================================================================

class GLDevice
{
public:
	GLDevice();
	~GLDevice();

	// Create a GL 3.3 core-profile window + context. When hidden is true the
	// window is not shown (used for headless bring-up and self-tests).
	bool Create(int width, int height, bool fullscreen, bool hidden,
		const char *title);
	void Destroy();

	void MakeCurrent();
	void SetVSync(bool vsync);

	void SetViewport(int width, int height);
	void Clear(float r, float g, float b, float a);
	void Present();				// swap buffers

	void Resize(int width, int height);
	void SetFullscreen(bool fullscreen);
	bool IsFullscreen() const;

	// Read the current framebuffer back as tightly packed RGB (3 bytes/pixel),
	// top-to-bottom. Caller supplies a width*height*3 buffer. Returns false if
	// no context. Used for hardware screenshots and self-test verification.
	bool ReadPixelsRGB(unsigned char *dstRGB, int width, int height);

	bool IsValid() const { return context != NULL; }
	int Width() const { return width; }
	int Height() const { return height; }
	SDL_Window *Window() const { return window; }

	// One-line capability report (version, renderer, GLSL).
	void LogCapabilities() const;

private:
	SDL_Window *window;
	SDL_GLContext context;
	int width;
	int height;
};

#endif
