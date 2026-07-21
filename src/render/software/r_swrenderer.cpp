// ===========================================================================
//
// r_swrenderer.cpp - reference software renderer backend.
//
// Renderer redesign Phase 2. This is intentionally a thin wrapper around the
// existing CPU render path (ThreeDRefresh): the point of this phase is to route
// rendering through IRenderer without changing a single pixel. Later phases
// decompose this path (world builder, interpolation) but the software backend
// remains the reference and fallback throughout.
//
// ===========================================================================

#include "render/software/r_swrenderer.h"
#include "wl_def.h"
#include "wl_draw.h"

namespace
{
	class SoftwareRenderer : public IRenderer
	{
	public:
		virtual bool Init() { return true; }
		virtual void Shutdown() {}

		virtual void RenderScene()
		{
			// The legacy path locks the framebuffer, renders the world and the
			// view model, and unlocks. Unchanged from the pre-seam engine.
			ThreeDRefresh();
		}

		virtual RendererType Type() const { return RENDERER_Software; }
		virtual const char *Name() const { return "software renderer"; }
	};
}

IRenderer *R_CreateSoftwareRenderer()
{
	return new SoftwareRenderer;
}
