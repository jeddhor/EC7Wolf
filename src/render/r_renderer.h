#ifndef __R_RENDERER_H__
#define __R_RENDERER_H__

// ===========================================================================
//
// Backend-neutral renderer seam (renderer redesign Phase 2).
//
// Game code asks the active IRenderer to render the scene; the backend decides
// how. The software backend wraps the historical ThreeDRefresh path unchanged,
// so selecting "software" is visually and behaviorally identical to the
// pre-seam engine. OpenGL (Phase 4) and Vulkan (Phase 12) plug in later without
// touching game code.
//
// ===========================================================================

enum RendererType
{
	RENDERER_Software,
	RENDERER_OpenGL,
	RENDERER_Vulkan
};

class IRenderer
{
public:
	virtual ~IRenderer() {}

	// One-time backend init/teardown. Init() returns false if the backend
	// cannot start (e.g. a hardware context fails to create), which makes the
	// selector fall back to the software renderer.
	virtual bool Init() = 0;
	virtual void Shutdown() = 0;

	// Render the full 3D scene (world + first-person view model) for the
	// current frame into the active framebuffer. This is the seam that wraps
	// the legacy ThreeDRefresh sequence.
	virtual void RenderScene() = 0;

	// Draw 2D that lands over the 3D view right after RenderScene (Corridor 7's
	// top-message overlay). The software backend just draws. A backend that
	// composites the view from its own framebuffer needs to know which texels
	// this painted -- it cannot recover that from the 8-bit frame alone, because
	// 2D drawn in the compositor's transparent key colour (C7's black text drop
	// shadow) is indistinguishable from untouched view background. Such a backend
	// may call `draw` more than once, so it must be a pure drawing function.
	virtual void DrawViewOverlay(void (*draw)()) { if(draw) draw(); }

	virtual RendererType Type() const = 0;
	virtual const char *Name() const = 0;
};

// The active renderer. Non-null once R_InitRendererBackend() has run and until
// R_ShutdownRendererBackend() runs.
extern IRenderer *Renderer;

// Create the backend selected by the vid_renderer config value, honoring the
// compiled-in ECWOLF_RENDERER_* backends and falling back to software when the
// requested backend is unavailable or fails to initialize. Idempotent.
void R_InitRendererBackend();
void R_ShutdownRendererBackend();

#endif
