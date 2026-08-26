// ===========================================================================
//
// r_gldevice.cpp - SDL OpenGL context + presentation (renderer redesign Phase 4).
//
// ===========================================================================

#include <SDL.h>
#include "render/opengl/r_glcompat.h"

#include "render/opengl/r_gldevice.h"
#include "wl_def.h"
#include "zdoomsupport.h"

GLDevice::GLDevice()
	: window(NULL), context(NULL), width(0), height(0)
{
}

GLDevice::~GLDevice()
{
	Destroy();
}

bool GLDevice::Create(int w, int h, bool fullscreen, bool hidden,
	const char *title)
{
	if(SDL_WasInit(SDL_INIT_VIDEO) == 0)
	{
		if(SDL_InitSubSystem(SDL_INIT_VIDEO) != 0)
		{
			Printf("GL: SDL video init failed: %s\n", SDL_GetError());
			return false;
		}
	}

	// GLES 3.0 on Android, desktop 3.3 core elsewhere. The two are the same
	// renderer: everything this backend uses is in both, which is why there is
	// a compatibility header rather than a second implementation.
#ifdef __ANDROID__
	SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
	SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 0);
	SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_ES);
#else
	SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
	SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 3);
	SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE);
#endif
	SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);
	SDL_GL_SetAttribute(SDL_GL_DEPTH_SIZE, 24);
	SDL_GL_SetAttribute(SDL_GL_RED_SIZE, 8);
	SDL_GL_SetAttribute(SDL_GL_GREEN_SIZE, 8);
	SDL_GL_SetAttribute(SDL_GL_BLUE_SIZE, 8);
#ifdef _DEBUG
	SDL_GL_SetAttribute(SDL_GL_CONTEXT_FLAGS, SDL_GL_CONTEXT_DEBUG_FLAG);
#endif

	Uint32 flags = SDL_WINDOW_OPENGL;
	if(fullscreen)
		flags |= SDL_WINDOW_FULLSCREEN_DESKTOP;
	if(hidden)
		flags |= SDL_WINDOW_HIDDEN;

	window = SDL_CreateWindow(title ? title : "EC7Wolf",
		SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, w, h, flags);
	if(window == NULL)
	{
		Printf("GL: window creation failed: %s\n", SDL_GetError());
		return false;
	}

	context = SDL_GL_CreateContext(window);
	if(context == NULL)
	{
		Printf("GL: context creation failed: %s\n", SDL_GetError());
		SDL_DestroyWindow(window);
		window = NULL;
		return false;
	}

	SDL_GL_MakeCurrent(window, context);

	// libepoxy resolves entry points lazily; no explicit loader init needed.
	// Sanity check that a core function is reachable.
	// Same test, different floor: GLES 3.0 carries every feature this backend
	// asks for, and desktop needs 3.3 to have them all.
#ifdef __ANDROID__
	const int required = 30;
#else
	const int required = 33;
#endif
	if(epoxy_gl_version() < required)
	{
		Printf("GL: got version %d, need >= %d\n", epoxy_gl_version(), required);
		Destroy();
		return false;
	}

	SDL_GL_GetDrawableSize(window, &width, &height);
	if(width == 0 || height == 0) { width = w; height = h; }

	return true;
}

void GLDevice::Destroy()
{
	if(context)
	{
		SDL_GL_DeleteContext(context);
		context = NULL;
	}
	if(window)
	{
		SDL_DestroyWindow(window);
		window = NULL;
	}
}

void GLDevice::MakeCurrent()
{
	if(window && context)
		SDL_GL_MakeCurrent(window, context);
}

void GLDevice::SetVSync(bool vsync)
{
	SDL_GL_SetSwapInterval(vsync ? 1 : 0);
}

void GLDevice::SetViewport(int w, int h)
{
	glViewport(0, 0, w, h);
}

void GLDevice::Clear(float r, float g, float b, float a)
{
	glClearColor(r, g, b, a);
	glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
}

void GLDevice::Present()
{
	if(window)
		SDL_GL_SwapWindow(window);
}

void GLDevice::Resize(int w, int h)
{
	width = w;
	height = h;
	glViewport(0, 0, w, h);
}

void GLDevice::SetFullscreen(bool fullscreen)
{
	if(window)
		SDL_SetWindowFullscreen(window,
			fullscreen ? SDL_WINDOW_FULLSCREEN_DESKTOP : 0);
	if(window)
		SDL_GL_GetDrawableSize(window, &width, &height);
}

bool GLDevice::IsFullscreen() const
{
	if(!window)
		return false;
	return (SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN_DESKTOP) != 0;
}

bool GLDevice::ReadPixelsRGB(unsigned char *dstRGB, int w, int h)
{
	if(!context)
		return false;

	glPixelStorei(GL_PACK_ALIGNMENT, 1);
	// GL returns bottom-to-top; flip into the caller's top-to-bottom buffer.
	unsigned char *tmp = new unsigned char[(size_t)w * h * 3];
	glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, tmp);
	for(int y = 0; y < h; ++y)
	{
		const unsigned char *srcRow = tmp + (size_t)(h - 1 - y) * w * 3;
		unsigned char *dstRow = dstRGB + (size_t)y * w * 3;
		memcpy(dstRow, srcRow, (size_t)w * 3);
	}
	delete[] tmp;
	return true;
}

void GLDevice::LogCapabilities() const
{
	const char *ver = (const char *)glGetString(GL_VERSION);
	const char *ren = (const char *)glGetString(GL_RENDERER);
	const char *glsl = (const char *)glGetString(GL_SHADING_LANGUAGE_VERSION);
	Printf("GL: version '%s' renderer '%s' glsl '%s'\n",
		ver ? ver : "?", ren ? ren : "?", glsl ? glsl : "?");
}
