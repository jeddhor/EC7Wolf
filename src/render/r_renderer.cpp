// ===========================================================================
//
// r_renderer.cpp - renderer backend selection & lifetime.
//
// Renderer redesign Phase 2. Resolves the vid_renderer config value against the
// compiled-in backends, with a guaranteed software fallback so the game always
// has a working renderer.
//
// ===========================================================================

#include "render/r_renderer.h"
#include "render/software/r_swrenderer.h"
#include "wl_def.h"
#include "c_cvars.h"
#include "zstring.h"

#ifdef ECWOLF_RENDERER_OPENGL
#include "render/opengl/r_glrenderer.h"		// Phase 4
#endif

IRenderer *Renderer = NULL;

namespace
{
	RendererType ResolveRequested()
	{
		FString req = vid_renderer;
		req.ToLower();
		if(req.Compare("opengl") == 0 || req.Compare("gl") == 0)
			return RENDERER_OpenGL;
		if(req.Compare("vulkan") == 0 || req.Compare("vk") == 0)
			return RENDERER_Vulkan;
		return RENDERER_Software;
	}

	// Instantiate a non-software backend if it is compiled in, else NULL.
	IRenderer *CreateHardwareBackend(RendererType type)
	{
		switch(type)
		{
#ifdef ECWOLF_RENDERER_OPENGL
			case RENDERER_OpenGL:	return R_CreateOpenGLRenderer();
#endif
			default:
				break;
		}
		return NULL;
	}
}

void R_InitRendererBackend()
{
	if(Renderer != NULL)
		return;

	const RendererType requested = ResolveRequested();

	if(requested != RENDERER_Software)
	{
		IRenderer *backend = CreateHardwareBackend(requested);
		if(backend != NULL)
		{
			if(backend->Init())
			{
				Renderer = backend;
				Printf("Renderer: using %s.\n", Renderer->Name());
				return;
			}
			Printf("Renderer: %s failed to initialize; falling back to software.\n",
				backend->Name());
			backend->Shutdown();
			delete backend;
		}
		else
		{
			Printf("Renderer: '%s' is not available in this build; using software.\n",
				vid_renderer.GetChars());
		}
	}

	Renderer = R_CreateSoftwareRenderer();
	Renderer->Init();
	Printf("Renderer: using %s.\n", Renderer->Name());
}

void R_ShutdownRendererBackend()
{
	if(Renderer != NULL)
	{
		Renderer->Shutdown();
		delete Renderer;
		Renderer = NULL;
	}
}
