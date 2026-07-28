// ===========================================================================
//
// r_glworld.cpp - GL world render + offscreen capture + 2D compositor.
//
// Phase 5 stood up the geometry/camera with a debug shader. Phase 6 replaced
// the debug colours with real fidelity: each surface's FTexture is uploaded as
// an 8-bit *index* texture, and the shader resolves colour exactly the way the
// software renderer does -- index -> colormap[shadeRow] -> palette -- with the
// shade row derived from ECWolf's own distance/light math, plus the Corridor 7
// colour-cycle and full-bright rules. Palette effects (visor/electric/damage)
// live entirely in the 256-entry palette texture, never in world pixels.
//
// Phase 10 adds the 2D compositor: the GL 3D world is rendered into the view
// sub-rectangle of a full frame, and the engine's 8-bit 2D layer (the player
// weapon, HUD/status bar, menus, text -- every VWB/2D operation, drawn by the
// existing software paths) is composited over it as an indexed overlay. The
// view region of the overlay is transparent except where the weapon (or any 2D
// drawn over the world) is opaque, so the GPU world shows through. This is the
// backend-neutral core of "a playable frame without switching to the software
// framebuffer"; the live SDL-window present swap is a following slice.
//
// ===========================================================================

#include <stdio.h>
#include <math.h>
#include <algorithm>

#include <epoxy/gl.h>

#include "render/opengl/r_glworld.h"
#include "render/opengl/r_gldevice.h"
#include "render/opengl/r_glshader.h"
#include "render/r_worldbuilder.h"
#include "render/r_dynamicwalls.h"
#include "render/r_interpolation.h"
#include "wl_def.h"
#include "zdoomsupport.h"
#include "wl_main.h"
#include "wl_play.h"
#include "wl_game.h"
#include "wl_agent.h"
#include "wl_shade.h"
#include "actor.h"
#include "id_ca.h"
#include "gamemap.h"
#include "wl_iwad.h"
#include "id_vl.h"
#include "tarray.h"
#include "textures/textures.h"
#include "v_video.h"
#include "v_palette.h"
#include "colormatcher.h"
#include "c_cvars.h"
#include "r_data/colormaps.h"
#include "render/opengl/r_glxbrz.h"

#include <SDL.h>

// ===========================================================================
//
// Frame profiler (vid_glprofile)
//
// Phase 11's optimization work is required to be profile-driven, so this exists
// before any of it: it splits a live frame into the stages that could plausibly
// dominate, so effort goes where the time actually is rather than where it is
// assumed to be.
//
// Deliberately coarse. Every bucket is wall-clock around a stage that already
// exists, which is enough to rank them; a sampling profiler would give better
// attribution inside a stage, but the question here is which stage.
//
// The GPU bucket is submission time, not execution time -- the driver is free to
// return before the work is done. Under llvmpipe (which is what the headless
// tests run on) rasterisation is on the CPU and does land in it. Read it as
// "time the draw calls cost this thread", not "GPU milliseconds".
//
// ===========================================================================

namespace GLProf
{
	enum Bucket
	{
		B_Visibility,	// software raycast kept for cell visibility + viewz
		B_Weapon,		// view-model draw, twice, plus the coverage mask
		B_Static,		// static world mesh construction
		B_Dynamic,		// doors/pushwalls
		B_Masked,		// masked walls
		B_Sprites,		// actor billboards
		B_Upload,		// VBO creation + texture upload
		B_Draw,			// world colour pass submission
		B_Present,		// composite + xBRZ + swap
		NUM_BUCKETS
	};

	const char *const kNames[NUM_BUCKETS] =
	{
		"visibility", "weapon", "static", "dynamic", "masked", "sprites",
		"upload", "draw", "present"
	};

	double   gAcc[NUM_BUCKETS] = { 0 };
	unsigned gFrames = 0;
	double   gInvFreq = 0.0;

	inline double Now()
	{
		if(gInvFreq == 0.0)
			gInvFreq = 1.0 / (double)SDL_GetPerformanceFrequency();
		return (double)SDL_GetPerformanceCounter() * gInvFreq;
	}

	// Scoped timer. Constructing one when profiling is off costs a bool test.
	struct Scope
	{
		double start;
		Bucket bucket;
		bool on;
		explicit Scope(Bucket b) : start(0.0), bucket(b), on(vid_glprofile)
		{
			if(on)
				start = Now();
		}
		~Scope()
		{
			if(on)
				gAcc[bucket] += Now() - start;
		}
	};

	// Called once per presented frame. Reports in blocks rather than per frame:
	// a per-frame line would itself cost more than some of the stages it claims
	// to measure.
	void EndFrame()
	{
		if(!vid_glprofile)
			return;

		++gFrames;
		if(gFrames < 100)
			return;

		double total = 0.0;
		for(int i = 0; i < NUM_BUCKETS; ++i)
			total += gAcc[i];

		FString line;
		line.Format("GL profile: %.2f ms/frame over %u frames =",
			1000.0 * total / (double)gFrames, gFrames);
		for(int i = 0; i < NUM_BUCKETS; ++i)
		{
			FString part;
			part.Format(" %s %.2f (%.0f%%)", kNames[i],
				1000.0 * gAcc[i] / (double)gFrames,
				total > 0.0 ? 100.0 * gAcc[i] / total : 0.0);
			line += part;
		}
		Printf("%s\n", line.GetChars());

		for(int i = 0; i < NUM_BUCKETS; ++i)
			gAcc[i] = 0.0;
		gFrames = 0;
	}
}

// Software raycaster wall pass. In the live GL path it is run only for its
// side-effects -- it stamps each ray-touched cell `visible` (which the GL sprite
// culling and the automap read) and sets viewz/viewshift for the plane-height
// uniforms -- while its wall pixels are discarded. Defined in wl_draw.cpp.
void WallRefresh(void);
// The same traversal with the per-column texture mapping skipped, since those
// pixels are overwritten before anything reads them. Same visibility set.
void WallRefreshVisibilityOnly(void);

// Distance-shade inputs owned by the software renderer.
extern int r_extralight;
extern fixed viewz;
extern int viewshift;

// Recomputes viewx/viewy/viewsin/viewcos from the current camera transform
// (no raycast); called after re-applying interpolation so the sprite builder's
// view basis matches this frame's interpolated camera. Defined in wl_draw.cpp.
void CalcViewVariables();

// The engine's 2D view-model draw. It writes the player weapon into the 8-bit
// render target pointed at by the vbuf/vbufPitch globals (index 0 = the sprite's
// own transparent key). We repoint those globals at a scratch buffer to capture
// the weapon silhouette without touching the live frame. Defined in wl_draw.cpp.
extern byte     *vbuf;
extern unsigned  vbufPitch;
void DrawPlayerWeapon(void);

namespace
{
	const double kPi = 3.14159265358979323846;

	// --- minimal column-major 4x4 matrix helpers ---
	struct Mat4 { float m[16]; };

	Mat4 Multiply(const Mat4 &a, const Mat4 &b)
	{
		Mat4 r;
		for(int c = 0; c < 4; ++c)
			for(int rw = 0; rw < 4; ++rw)
			{
				float s = 0;
				for(int k = 0; k < 4; ++k)
					s += a.m[k * 4 + rw] * b.m[c * 4 + k];
				r.m[c * 4 + rw] = s;
			}
		return r;
	}

	Mat4 Perspective(float fovyRad, float aspect, float znear, float zfar)
	{
		Mat4 r;
		for(int i = 0; i < 16; ++i) r.m[i] = 0;
		const float f = 1.0f / tanf(fovyRad * 0.5f);
		r.m[0] = f / aspect;
		r.m[5] = f;
		r.m[10] = (zfar + znear) / (znear - zfar);
		r.m[11] = -1.0f;
		r.m[14] = (2.0f * zfar * znear) / (znear - zfar);
		return r;
	}

	void Normalize(float v[3])
	{
		float l = sqrtf(v[0]*v[0] + v[1]*v[1] + v[2]*v[2]);
		if(l > 0) { v[0] /= l; v[1] /= l; v[2] /= l; }
	}
	void Cross(const float a[3], const float b[3], float out[3])
	{
		out[0] = a[1]*b[2] - a[2]*b[1];
		out[1] = a[2]*b[0] - a[0]*b[2];
		out[2] = a[0]*b[1] - a[1]*b[0];
	}

	Mat4 LookAt(const float eye[3], const float fwd[3], const float up[3])
	{
		float f[3] = { fwd[0], fwd[1], fwd[2] };
		Normalize(f);
		float s[3]; Cross(f, up, s); Normalize(s);
		float u[3]; Cross(s, f, u);

		Mat4 r;
		r.m[0] = s[0]; r.m[4] = s[1]; r.m[8]  = s[2];  r.m[12] = -(s[0]*eye[0]+s[1]*eye[1]+s[2]*eye[2]);
		r.m[1] = u[0]; r.m[5] = u[1]; r.m[9]  = u[2];  r.m[13] = -(u[0]*eye[0]+u[1]*eye[1]+u[2]*eye[2]);
		r.m[2] = -f[0];r.m[6] = -f[1];r.m[10] = -f[2]; r.m[14] =  (f[0]*eye[0]+f[1]*eye[1]+f[2]*eye[2]);
		r.m[3] = 0;    r.m[7] = 0;    r.m[11] = 0;      r.m[15] = 1;
		return r;
	}

	// The world position (aPos) is carried into view space so the fragment
	// shader can shade by perpendicular forward distance -- the same quantity
	// the raycaster uses for its wall shade row.
	const char *kVert =
		"#version 330 core\n"
		"layout(location=0) in vec3 aPos;\n"
		"layout(location=1) in vec2 aUV;\n"
		"layout(location=2) in float aTexKey;\n"
		"layout(location=3) in float aShade;\n"
		"uniform mat4 uProj;\n"
		"uniform mat4 uView;\n"
		"out vec2 vUV; out vec3 vViewPos;\n"
		"void main(){\n"
		"    vec4 vp = uView * vec4(aPos,1.0);\n"
		"    vViewPos = vp.xyz;\n"
		"    gl_Position = uProj * vp;\n"
		"    vUV = aUV;\n"
		"}\n";

	// index -> (Corridor7 cycle) -> colormap[shadeRow] -> palette. All fetches
	// are integer/nearest: palette indices must never be linearly filtered.
	const char *kFrag =
		"#version 330 core\n"
		"in vec2 vUV; in vec3 vViewPos;\n"
		"out vec4 fragColor;\n"
		"uniform usampler2D uIndexTex;\n"    // per-surface WxH, R8UI physical indices
		"uniform usampler2D uC7RampFloor;\n" // 256x1 R8UI: colour -> its ramp floor
		"uniform usampler2D uOpacityTex;\n"  // per-surface WxH, R8UI (0 = transparent)
		"uniform sampler2D  uPaletteTex;\n"  // 256x1 RGB8
		"uniform usampler2D uColormapTex;\n" // 256xNUMCOLORMAPS R8UI
		"uniform int   uHasOpacity;\n"
		"uniform int   uMasked;\n"        // 1 = colour-keyed masked wall / door leaf
		"uniform int   uMaskColor;\n"     // physical index treated as transparent (Remap[255])
		"uniform float uDepthVis;\n"
		"uniform float uHeightNum;\n"
		"uniform float uShade;\n"
		"uniform float uMaxLightVis;\n"
		"uniform float uPlaneHeight;\n"  // |planeheight| for the current surface (planes only)
		"uniform float uHorizon;\n"      // screen row of the horizon, GL pixel coords
		"uniform int   uSurfKind;\n"     // 0 floor, 1 ceiling, 2 wall
		"uniform int   uNumColormaps;\n"
		"uniform int   uCyclePhase;\n"
		"uniform int   uRemap15;\n"
		"uniform int   uRemap254;\n"
		"uniform int   uRemap208;\n"
		"uniform int   uRemap239;\n"
		"uniform int   uCorridor7;\n"
		"uniform int   uExtraLight;\n"
		"uniform int   uViewW;\n"
		"uniform int   uDither;\n"
		"uniform int   uSlide;\n"           // 1 = sliding door leaf
		"uniform int   uSlideStyle;\n"      // SLIDE_Normal/Split/Invert
		"uniform float uSlideAmount;\n"     // 0 closed .. 65535 fully open
		"uniform int   uSprite;\n"          // 1 = billboard actor sprite
		"uniform int   uSpriteFullbright;\n"// 1 = sprite ignores distance shade
		"uniform int   uSpriteLaser;\n"     // 1 = C7 infrared laser-barrier dissolve
		"uniform int   uPhase;\n"           // gamestate.TimeCount>>3 (cycle/dissolve)
		"uniform int   uLaserColor;\n"      // physical index for lit laser texels
		"uniform int   uDebug;\n"           // 0 normal, 1 shade-row visualization
		"uniform int   uFilter;\n"          // 0 nearest, 1 bilinear, 2 supersampled
		"const float FRACUNIT = 65536.0;\n"
		"const float MINZ = 8192.0;\n"      // 2048*4
		"float bayer4(ivec2 p){\n"
		"    int m[16] = int[16](0,8,2,10, 12,4,14,6, 3,11,1,9, 15,7,13,5);\n"
		"    int i = (p.y & 3)*4 + (p.x & 3);\n"
		"    return (float(m[i]) + 0.5) / 16.0;\n"
		"}\n"
		// Corridor 7 infrared laser-barrier dissolve, mirroring C7LaserDissolveLit:\n"
		"// a hashed on/off mask over 8-texel vertical blocks that crawls with the\n"
		"// game clock, so each rod reads as moving dashed energy segments.\n"
		"bool c7LaserLit(ivec2 t, int phase){\n"
		"    uint u = uint(t.x); uint v = uint(t.y);\n"
		"    uint h = u*73856093u ^ (v>>3u)*19349663u ^ uint(phase)*83492791u;\n"
		"    h ^= h >> 13u; h *= 0x9E3779B1u; h ^= h >> 16u;\n"
		"    return (h % 3u) != 0u;\n"
		"}\n"
		// --- texture filtering -------------------------------------------------
		//
		// A palette index is a name, not a colour: averaging index 5 and index 200
		// gives 102, which is an unrelated entry. So the hardware cannot filter
		// this texture (it is R8UI, which is nearest-only anyway) and neither can
		// we, until each tap has been resolved all the way through the colour
		// cycle, the colormap row and the palette. Filtering therefore means
		// running the whole per-texel chain once per tap and mixing the RGB.
		//
		// The same taps produce coverage: a tap that is transparent contributes no
		// colour and lowers the weight instead. That fraction is written to alpha,
		// where GL_SAMPLE_ALPHA_TO_COVERAGE turns it into an antialiased silhouette
		// -- which is why sprite edges can be smoothed without blending, and
		// therefore without breaking the order-independence the draw batching
		// relies on.
		"int c7Cycle(int idx, bool isWall){\n"
		"    if(uCorridor7 == 1 && isWall && idx >= 208 && idx <= 239){\n"
		"        int base = idx & ~7;\n"
		"        return base + ((idx - base + uCyclePhase) & 7);\n"
		"    }\n"
		"    return idx;\n"
		"}\n"
		// Transparency exactly as the unfiltered path tests it, per texel.
		"bool tapOpaque(ivec2 texel, int idx){\n"
		"    if(uHasOpacity == 1) return texelFetch(uOpacityTex, texel, 0).r != 0u;\n"
		"    if(uMasked == 1 && idx == uMaskColor) return false;\n"
		"    if(uSprite == 1 && idx == 0) return false;\n"
		"    if(uSprite == 1 && uSpriteLaser == 1) return c7LaserLit(texel, uPhase);\n"
		"    return true;\n"
		"}\n"
		// Wall / door / masked / sprite texel -> RGB.
		"vec3 tapWall(int idx0, int shadeRow){\n"
		"    if(uSprite == 1 && uSpriteLaser == 1)\n"
		"        return texelFetch(uPaletteTex, ivec2(uLaserColor,0), 0).rgb;\n"
		"    bool isWall = uSurfKind == 2;\n"
		"    int idx = c7Cycle(idx0, isWall);\n"
		"    int row = shadeRow;\n"
		"    bool fullbright = uCorridor7 == 1 && isWall &&\n"
		"        (idx == uRemap15 || idx == uRemap254 ||\n"
		"        (idx >= uRemap208 && idx <= uRemap239));\n"
		"    if(fullbright) row = 0;\n"
		"    if(uSprite == 1 && uSpriteFullbright == 1) row = 0;\n"
		"    row = clamp(row, 0, uNumColormaps - 1);\n"
		"    int shaded = int(texelFetch(uColormapTex, ivec2(idx, row), 0).r);\n"
		"    return texelFetch(uPaletteTex, ivec2(shaded, 0), 0).rgb;\n"
		"}\n"
		// Corridor 7 plane texel -> RGB (walks the palette, never the colormap).
		"vec3 tapPlane(int idx, int litBand){\n"
		"    int rampBase = int(texelFetch(uC7RampFloor, ivec2(idx, 0), 0).r);\n"
		"    int planeIdx = max(rampBase, idx - litBand);\n"
		"    return texelFetch(uPaletteTex, ivec2(planeIdx, 0), 0).rgb;\n"
		"}\n"
		// Sprites clamp at their border; everything else tiles, as the raycaster's
		// per-cell texture addressing does. Wrapping a sprite would fetch the far
		// side of the silhouette into its own edge.
		"ivec2 tapWrap(ivec2 texel, ivec2 isz){\n"
		"    if(uSprite == 1) return clamp(texel, ivec2(0), isz - 1);\n"
		"    return ((texel % isz) + isz) % isz;\n"
		"}\n"
		"void tapAt(ivec2 texel, ivec2 isz, int shadeRow, int litBand, float w,\n"
		"           inout vec3 acc, inout float cov){\n"
		"    ivec2 t = tapWrap(texel, isz);\n"
		"    int idx = int(texelFetch(uIndexTex, t, 0).r);\n"
		"    if(!tapOpaque(t, idx)) return;\n"
		"    vec3 c = (uSurfKind == 2) ? tapWall(idx, shadeRow)\n"
		"                              : ((uCorridor7 == 1) ? tapPlane(idx, litBand)\n"
		"                                                   : tapWall(idx, shadeRow));\n"
		"    acc += w * c; cov += w;\n"
		"}\n"
		// One bilinear sample: four taps around the sample point, weighted by the
		// fractional position, each resolved before it is mixed.
		"void sampleBilinear(vec2 uvs, ivec2 isz, int shadeRow, int litBand,\n"
		"                    inout vec3 acc, inout float cov, float weight){\n"
		"    vec2 sp = uvs * vec2(isz) - 0.5;\n"
		"    ivec2 t0 = ivec2(floor(sp));\n"
		"    vec2 f = sp - vec2(t0);\n"
		"    tapAt(t0,               isz, shadeRow, litBand, weight*(1.0-f.x)*(1.0-f.y), acc, cov);\n"
		"    tapAt(t0+ivec2(1,0),    isz, shadeRow, litBand, weight*f.x*(1.0-f.y),       acc, cov);\n"
		"    tapAt(t0+ivec2(0,1),    isz, shadeRow, litBand, weight*(1.0-f.x)*f.y,       acc, cov);\n"
		"    tapAt(t0+ivec2(1,1),    isz, shadeRow, litBand, weight*f.x*f.y,             acc, cov);\n"
		"}\n"
		"void main(){\n"
		"    // Door-leaf slide: reproduce the software CheckSlidePass /\n"
		"    // SlideTextureOffset along U before sampling. Open columns discard.\n"
		"    vec2 uv = vUV;\n"
		"    if(uSlide == 1){\n"
		"        float intercept = clamp(uv.x, 0.0, 0.999985);\n"
		"        float amt = uSlideAmount / FRACUNIT;\n"
		"        bool open;\n"
		"        if(amt <= 0.0) open = false;\n"
		"        else if(uSlideStyle == 1) open = abs(1.0 - intercept*2.0) < amt;\n"
		"        else if(uSlideStyle == 2) open = intercept > (1.0 - amt);\n"
		"        else open = intercept < amt;\n"
		"        if(open) discard;\n"
		"        float off;\n"
		"        if(uSlideStyle == 1) off = (intercept < 0.5) ? amt*0.5 : -amt*0.5;\n"
		"        else if(uSlideStyle == 2) off = amt;\n"
		"        else off = -amt;\n"
		"        uv.x = fract(intercept + off);\n"
		"    }\n"
		"    ivec2 isz = textureSize(uIndexTex,0);\n"
		"\n"
		"    // --- per-fragment shade selection (independent of which texel) ---\n"
		"    int shadeRow = 0;\n"
		"    int litBand = 0;\n"
		"    if(uSurfKind == 2){\n"
		"        // Wall: perpendicular forward distance -> raycaster wallheight rule.\n"
		"        float d = max(-vViewPos.z, 0.0001);\n"
		"        float tz = (uDepthVis * uHeightNum) / (d * FRACUNIT);\n"
		"        tz = max(tz, MINZ);\n"
		"        float visv = min(uMaxLightVis, tz);\n"
		"        float palf = (uShade - visv) / FRACUNIT;\n"
		"        float dref = (uDither == 1) ? (bayer4(ivec2(gl_FragCoord.xy)) - 0.5) : 0.0;\n"
		"        shadeRow = int(floor(palf + dref));\n"
		"    } else if(uCorridor7 == 1){\n"
		"        // Corridor 7 planes use a screen-space VGA band pattern, not the\n"
		"        // distance formula (reconstruction of c7PlaneShades / R_DrawPlane).\n"
		"        float rowFromHorizon = abs(gl_FragCoord.y - uHorizon);\n"
		"        float edge = max(0.0, uHorizon - 1.0 - rowFromHorizon);\n"
		"        int ver = int(min(79.0, edge * 80.0 / max(1.0, uHorizon)));\n"
		"        int band = ver / 3;\n"
		"        litBand = band > uExtraLight / 8 ? band - uExtraLight / 8 : 0;\n"
		"        int virtualX = int(min(319.0, gl_FragCoord.x * 320.0 / float(uViewW)));\n"
		"        int a = (virtualX >> 2) & 1;\n"
		"        int b = (ver % 3 == 1) ? 1 : 0;\n"
		"        int c = band & 1;\n"
		// Four-pixel alternation: the software picks c7NextPlaneShades, i.e. the
		// NEXT band -- one more palette step.
		"        if((a ^ b ^ c) == 0) litBand += 1;\n"
		"    } else {\n"
		"        // Generic (non-C7) plane distance formula.\n"
		"        float rowFromHorizon = abs(gl_FragCoord.y - uHorizon);\n"
		"        float tz = (uDepthVis * FRACUNIT / uPlaneHeight) * rowFromHorizon;\n"
		"        float visv = min(uMaxLightVis, tz);\n"
		"        float palf = (uShade - visv) / FRACUNIT;\n"
		"        shadeRow = int(floor(palf));\n"
		"    }\n"
		"    shadeRow = clamp(shadeRow, 0, uNumColormaps - 1);\n"
		"\n"
		"    // --- debug visualizations read the centre texel only ---\n"
		"    if(uDebug == 1){\n"
		"        ivec2 dt = tapWrap(ivec2(floor(uv * vec2(isz))), isz);\n"
		"        int didx = int(texelFetch(uIndexTex, dt, 0).r);\n"
		"        if(uSurfKind != 2 && uCorridor7 == 1){\n"
		"            int rampBase = int(texelFetch(uC7RampFloor, ivec2(didx, 0), 0).r);\n"
		"            float g = float(didx - max(rampBase, didx - litBand)) / 15.0;\n"
		"            fragColor = vec4(g, g, g, 1.0); return;\n"
		"        }\n"
		"        float g = float(shadeRow) / float(uNumColormaps - 1);\n"
		"        fragColor = vec4(g, g, g, 1.0); return;\n"
		"    }\n"
		"\n"
		"    vec3 acc = vec3(0.0);\n"
		"    float cov = 0.0;\n"
		"    if(uFilter == 0){\n"
		"        // Nearest: one tap, bit-identical to the unfiltered renderer.\n"
		"        tapAt(ivec2(floor(uv * vec2(isz))), isz, shadeRow, litBand, 1.0, acc, cov);\n"
		"    } else if(uFilter == 1){\n"
		"        sampleBilinear(uv, isz, shadeRow, litBand, acc, cov, 1.0);\n"
		"    } else {\n"
		"        // Supersampled: four bilinear samples on a rotated grid across the\n"
		"        // pixel's footprint in texture space. This is what stands in for\n"
		"        // trilinear/anisotropic filtering here -- both of those need a mip\n"
		"        // chain, and a mip chain of palette indices is meaningless while a\n"
		"        // mip chain of resolved colour would have to be rebuilt every time\n"
		"        // Corridor 7 rewrites the palette (night vision, infrared, damage).\n"
		"        // Sampling the footprint directly needs no such precomputation and\n"
		"        // narrows with distance the same way, which is what stops the\n"
		"        // shimmer.\n"
		"        vec2 dx = dFdx(uv), dy = dFdy(uv);\n"
		"        sampleBilinear(uv + (-0.375)*dx + (-0.125)*dy, isz, shadeRow, litBand, acc, cov, 0.25);\n"
		"        sampleBilinear(uv + ( 0.125)*dx + (-0.375)*dy, isz, shadeRow, litBand, acc, cov, 0.25);\n"
		"        sampleBilinear(uv + ( 0.375)*dx + ( 0.125)*dy, isz, shadeRow, litBand, acc, cov, 0.25);\n"
		"        sampleBilinear(uv + (-0.125)*dx + ( 0.375)*dy, isz, shadeRow, litBand, acc, cov, 0.25);\n"
		"    }\n"
		"    if(cov <= 0.0) discard;\n"
		"    // Colour is the average of the taps that were opaque; alpha is how much\n"
		"    // of the pixel they covered. Without alpha-to-coverage the alpha is\n"
		"    // ignored (the target is RGB and nothing blends), so edges stay hard\n"
		"    // and only the colour is filtered.\n"
		"    fragColor = vec4(acc / cov, cov);\n"
		"}\n";

	// --- Phase 10 compositor: a screen-space quad that either blits the RGB
	// world texture (mode 0) or resolves the 8-bit 2D overlay through the palette
	// (mode 1), discarding transparent overlay texels so the world shows through.
	const char *kScreenVert =
		"#version 330 core\n"
		"layout(location=0) in vec2 aPos;\n"
		"layout(location=1) in vec2 aUV;\n"
		"out vec2 vUV;\n"
		"void main(){ vUV = aUV; gl_Position = vec4(aPos, 0.0, 1.0); }\n";

	const char *kScreenFrag =
		"#version 330 core\n"
		"in vec2 vUV; out vec4 fragColor;\n"
		"uniform int uMode;\n"               // 0 = RGB world blit, 1 = indexed 2D overlay
		"uniform sampler2D  uWorldTex;\n"    // RGB8 world colour (mode 0)
		"uniform usampler2D uOverlayIdx;\n"  // R8UI final palette indices (mode 1)
		"uniform usampler2D uOverlayOpac;\n" // R8UI 0 = transparent (mode 1)
		"uniform sampler2D  uPaletteTex;\n"  // 256x1 RGB8
		"void main(){\n"
		"    if(uMode == 0){\n"
		"        fragColor = vec4(texture(uWorldTex, vUV).rgb, 1.0); return;\n"
		"    }\n"
		"    ivec2 sz = textureSize(uOverlayIdx, 0);\n"
		"    ivec2 t = ivec2(floor(vUV * vec2(sz)));\n"
		"    t = clamp(t, ivec2(0), sz - ivec2(1));\n"
		"    if(texelFetch(uOverlayOpac, t, 0).r == 0u) discard;\n"  // world shows through
		"    int idx = int(texelFetch(uOverlayIdx, t, 0).r);\n"
		"    fragColor = vec4(texelFetch(uPaletteTex, ivec2(idx,0), 0).rgb, 1.0);\n"
		"}\n";

	bool WritePPM(const char *path, const unsigned char *rgb, int w, int h)
	{
		FILE *f = fopen(path, "wb");
		if(!f) return false;
		fprintf(f, "P6\n%d %d\n255\n", w, h);
		fwrite(rgb, 1, (size_t)w * h * 3, f);
		fclose(f);
		return true;
	}

	// Upload the live 256-entry palette (post gamma/blend baked into BaseColors,
	// the same buffer the software screenshot is written with) as a 256x1 RGB8
	// texture. Palette effects only ever re-run this; world pixels never change.
	GLuint CreatePaletteTexture()
	{
		// The palette actually on screen, not GPalette's base colours: Corridor 7
		// rewrites the DAC for the visor modes and V_ForceBlend adds a flash on
		// top. The live path already uploads this; the offscreen capture path did
		// not, so a --capture-glframe of a visor scene came back untinted and could
		// not be compared with the software screenshot beside it.
		PalEntry pal[256];
		if(screen != NULL)
			screen->GetFlashedPalette(pal);
		else
			memcpy(pal, GPalette.BaseColors, sizeof(pal));
		unsigned char rgb[256 * 3];
		for(int i = 0; i < 256; ++i)
		{
			rgb[i*3+0] = pal[i].r;
			rgb[i*3+1] = pal[i].g;
			rgb[i*3+2] = pal[i].b;
		}
		GLuint tex = 0;
		glGenTextures(1, &tex);
		glBindTexture(GL_TEXTURE_2D, tex);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
		glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
		glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8, 256, 1, 0, GL_RGB,
			GL_UNSIGNED_BYTE, rgb);
		return tex;
	}

	// Upload the distance colormap table (NormalLight.Maps) as a
	// 256 x NUMCOLORMAPS R8UI texture: colormap[shadeRow][index].
	GLuint CreateColormapTexture(int &rowsOut)
	{
		rowsOut = NUMCOLORMAPS;
		GLuint tex = 0;
		glGenTextures(1, &tex);
		glBindTexture(GL_TEXTURE_2D, tex);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
		glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
		// NormalLight.Maps is laid out row-major as Maps[(shadeRow<<8)+index],
		// which matches a 256-wide x NUMCOLORMAPS-tall R8UI upload directly.
		glTexImage2D(GL_TEXTURE_2D, 0, GL_R8UI, 256, NUMCOLORMAPS, 0,
			GL_RED_INTEGER, GL_UNSIGNED_BYTE, NormalLight.Maps);
		return tex;
	}

	// 256x1 R8UI: for each palette index, the bottom of its ramp. The C7 plane
	// shader steps one index darker per band and stops there; the ramps are not
	// uniform, so this is derived from the palette (V_GetC7RampFloors) and shared
	// with the software renderer rather than assumed.
	GLuint CreateC7RampFloorTexture()
	{
		const BYTE *floors = V_GetC7RampFloors();
		GLuint tex = 0;
		glGenTextures(1, &tex);
		glBindTexture(GL_TEXTURE_2D, tex);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
		glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
		glTexImage2D(GL_TEXTURE_2D, 0, GL_R8UI, 256, 1, 0,
			GL_RED_INTEGER, GL_UNSIGNED_BYTE, floors);
		return tex;
	}

	// Upload a raw R8UI texture (nearest, clamp) -- used for the 2D overlay's
	// index and opacity buffers, which are already full-frame row-major.
	GLuint CreateR8UITexture(const unsigned char *data, int w, int h)
	{
		GLuint id = 0;
		glGenTextures(1, &id);
		glBindTexture(GL_TEXTURE_2D, id);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
		glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
		glTexImage2D(GL_TEXTURE_2D, 0, GL_R8UI, w, h, 0,
			GL_RED_INTEGER, GL_UNSIGNED_BYTE, data);
		return id;
	}

	// Build an R8UI index texture from an FTexture. GetPixels() is column-major
	// (pixels[col*H + row]); GL wants row-major, so transpose into a scratch
	// buffer. The values are already physical palette indices.
	GLuint CreateIndexTextureFor(FTexture *tex)
	{
		if(tex == NULL)
			return 0;
		const int w = tex->GetWidth();
		const int h = tex->GetHeight();
		if(w <= 0 || h <= 0)
			return 0;

		const BYTE *pixels = tex->GetPixels();
		if(pixels == NULL)
			return 0;

		TArray<unsigned char> rowmajor((unsigned)(w * h));
		rowmajor.Resize((unsigned)(w * h));
		for(int col = 0; col < w; ++col)
			for(int row = 0; row < h; ++row)
				rowmajor[row * w + col] = pixels[col * h + row];

		GLuint id = 0;
		glGenTextures(1, &id);
		glBindTexture(GL_TEXTURE_2D, id);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
		glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
		glTexImage2D(GL_TEXTURE_2D, 0, GL_R8UI, w, h, 0,
			GL_RED_INTEGER, GL_UNSIGNED_BYTE, &rowmajor[0]);
		return id;
	}

	// Build an R8UI opacity texture (0 = transparent) from GetColumnOpacity(),
	// which C7's see-through wall textures (grates/fences) provide. Transparency
	// is *explicit* here -- never inferred from index 0/255 -- matching the
	// software renderer's postopacity test. Returns 0 when the texture is fully
	// opaque (no column reports an opacity buffer).
	GLuint CreateOpacityTextureFor(FTexture *tex)
	{
		if(tex == NULL)
			return 0;
		const int w = tex->GetWidth();
		const int h = tex->GetHeight();
		if(w <= 0 || h <= 0)
			return 0;

		TArray<unsigned char> rowmajor((unsigned)(w * h));
		rowmajor.Resize((unsigned)(w * h));
		bool anyTransparent = false;
		for(int col = 0; col < w; ++col)
		{
			const BYTE *opac = tex->GetColumnOpacity((unsigned)col);
			for(int row = 0; row < h; ++row)
			{
				unsigned char o = opac ? opac[row] : 255;
				if(o == 0)
					anyTransparent = true;
				rowmajor[row * w + col] = o;
			}
		}
		if(!anyTransparent)
			return 0;	// fully opaque: no discard needed

		GLuint id = 0;
		glGenTextures(1, &id);
		glBindTexture(GL_TEXTURE_2D, id);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
		glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
		glTexImage2D(GL_TEXTURE_2D, 0, GL_R8UI, w, h, 0,
			GL_RED_INTEGER, GL_UNSIGNED_BYTE, &rowmajor[0]);
		return id;
	}

	// Uniform locations shared across every surface in one world draw.
	struct SurfaceUniforms
	{
		GLint uIndexTex;
		GLint uOpacityTex;
		GLint uHasOpacity;
		GLint uMasked;
		GLint uSurfKind;
		GLint uPlaneHeight;
		GLint uSlide;
		GLint uSlideStyle;
		GLint uSlideAmount;
		GLint uSprite;
		GLint uSpriteFullbright;
		GLint uSpriteLaser;
		float floorPlaneH;
		float ceilPlaneH;
	};

	// One mesh's GPU resources: interleaved VBO + a per-surface index/opacity
	// texture list (parallel to mesh.surfaces).
	// One merged glDrawArrays: a run of surfaces that need identical GL state.
	//
	// The mesh arrives as one surface per wall face, floor tile and ceiling tile
	// -- 3878 of them on MAP01 -- and drawing them one at a time cost 31-50% of
	// the frame in submission alone, measured, before any of them reached the
	// GPU. Sorting by state and merging the runs collapses that to a few dozen
	// draws.
	//
	// Reordering is safe here specifically because this pass has no blending:
	// every transparent texel is a shader `discard` and depth testing decides
	// the rest, so the image does not depend on the order surfaces are drawn in.
	// Introducing a blended surface type would break that, and this is where it
	// would have to be handled.
	struct MeshDraw
	{
		GLuint tex, opac;
		int kind;			// shader surface kind (doors/masked/sprites -> wall)
		int masked, sprite, spriteFb, spriteLaser, isDoor;
		int slideStyle;
		unsigned int slideAmount;
		GLuint first, count;
	};

	struct MeshGL
	{
		GLuint vao, vbo;
		TArray<MeshDraw> draws;
		MeshGL() : vao(0), vbo(0) {}
	};

	// Byte-identical meshes produce byte-identical GPU buffers, so this decides
	// whether last frame's upload can stand. Padding inside WorldSurface is
	// compared along with the fields, which can only ever report "different" for
	// two meshes that are really the same -- that costs a rebuild, never a stale
	// one.
	bool MeshContentEqual(const WorldMesh &a, const WorldMesh &b)
	{
		if(a.vertices.Size() != b.vertices.Size() ||
			a.surfaces.Size() != b.surfaces.Size())
			return false;
		if(a.vertices.Size() &&
			memcmp(&a.vertices[0], &b.vertices[0],
				a.vertices.Size() * sizeof(WorldVertex)) != 0)
			return false;
		if(a.surfaces.Size() &&
			memcmp(&a.surfaces[0], &b.surfaces[0],
				a.surfaces.Size() * sizeof(WorldSurface)) != 0)
			return false;
		return true;
	}

	// Everything the shader reads. Two surfaces that agree on all of it can be
	// drawn together; `first`/`count` are the run itself and are not compared.
	inline bool SameDrawState(const MeshDraw &a, const MeshDraw &b)
	{
		return a.tex == b.tex && a.opac == b.opac && a.kind == b.kind &&
			a.masked == b.masked && a.sprite == b.sprite &&
			a.spriteFb == b.spriteFb && a.spriteLaser == b.spriteLaser &&
			a.isDoor == b.isDoor && a.slideStyle == b.slideStyle &&
			a.slideAmount == b.slideAmount;
	}

	// Draw one mesh with the current program/uniforms. The framebuffer clear and
	// uDebug are set by the caller so several meshes share one pass.
	void RenderMesh(const WorldMesh &mesh, const MeshGL &gl,
		const SurfaceUniforms &su)
	{
		if(gl.draws.Size() == 0)
			return;
		glBindVertexArray(gl.vao);

		GLuint boundTex = 0xffffffffu;
		GLuint boundOpac = 0xffffffffu;
		int boundKind = -100;
		int boundMasked = -100;
		int boundSprite = -100;
		int boundSpriteFb = -100;
		int boundSpriteLaser = -100;
		int boundSlide = -100;
		int boundSlideStyle = -100;
		unsigned int boundSlideAmt = 0xffffffffu;
		for(unsigned int i = 0; i < gl.draws.Size(); ++i)
		{
			const MeshDraw &d = gl.draws[i];
			if(d.tex != boundTex)
			{
				glActiveTexture(GL_TEXTURE0);
				glBindTexture(GL_TEXTURE_2D, d.tex);
				glUniform1i(su.uIndexTex, 0);
				boundTex = d.tex;
			}
			if(d.opac != boundOpac)
			{
				glUniform1i(su.uHasOpacity, d.opac ? 1 : 0);
				if(d.opac)
				{
					glActiveTexture(GL_TEXTURE3);
					glBindTexture(GL_TEXTURE_2D, d.opac);
					glUniform1i(su.uOpacityTex, 3);
				}
				boundOpac = d.opac;
			}
			if(d.kind != boundKind)
			{
				glUniform1i(su.uSurfKind, d.kind);
				if(d.kind == WSURF_Floor)
					glUniform1f(su.uPlaneHeight, su.floorPlaneH);
				else if(d.kind == WSURF_Ceiling)
					glUniform1f(su.uPlaneHeight, su.ceilPlaneH);
				boundKind = d.kind;
			}
			if(d.masked != boundMasked)
			{
				glUniform1i(su.uMasked, d.masked);
				boundMasked = d.masked;
			}
			if(d.sprite != boundSprite)
			{
				glUniform1i(su.uSprite, d.sprite);
				boundSprite = d.sprite;
			}
			if(d.spriteFb != boundSpriteFb)
			{
				glUniform1i(su.uSpriteFullbright, d.spriteFb);
				boundSpriteFb = d.spriteFb;
			}
			if(d.spriteLaser != boundSpriteLaser)
			{
				glUniform1i(su.uSpriteLaser, d.spriteLaser);
				boundSpriteLaser = d.spriteLaser;
			}
			if(d.isDoor != boundSlide)
			{
				glUniform1i(su.uSlide, d.isDoor);
				boundSlide = d.isDoor;
			}
			if(d.isDoor && (d.slideStyle != boundSlideStyle ||
				d.slideAmount != boundSlideAmt))
			{
				glUniform1i(su.uSlideStyle, d.slideStyle);
				glUniform1f(su.uSlideAmount, (float)d.slideAmount);
				boundSlideStyle = d.slideStyle;
				boundSlideAmt = d.slideAmount;
			}
			glDrawArrays(GL_TRIANGLES, (GLint)d.first, (GLsizei)d.count);
		}
	}

	// Upload a mesh's VBO + per-surface index/opacity textures. Textures are
	// cached per FTextureID (shared across the static and dynamic meshes) so
	// shared art uploads a single time.
	void UploadMesh(const WorldMesh &mesh, TMap<int, GLuint> &texCache,
		TMap<int, GLuint> &opacCache, MeshGL &out,
		unsigned int *uniqueOut, unsigned int *maskedOut)
	{
		// Resolve each surface's textures first, then sort the surfaces into
		// state order and rewrite the vertex buffer in that order, so a run of
		// surfaces sharing state becomes one draw. The vertices are copied
		// rather than indexed because the buffer is rebuilt every frame anyway;
		// an index buffer would save nothing here and cost a second upload.
		const unsigned int numSurf = mesh.surfaces.Size();
		TArray<GLuint> surfTex(numSurf ? numSurf : 1);
		TArray<GLuint> surfOpac(numSurf ? numSurf : 1);
		surfTex.Resize(numSurf);
		surfOpac.Resize(numSurf);
		for(unsigned int i = 0; i < numSurf; ++i)
		{
			const FTextureID id = mesh.surfaces[i].texture;
			if(!id.isValid())
			{
				surfTex[i] = 0;
				surfOpac[i] = 0;
				continue;
			}
			const int key = id.GetIndex();
			GLuint *cached = texCache.CheckKey(key);
			if(cached)
			{
				surfTex[i] = *cached;
				surfOpac[i] = *opacCache.CheckKey(key);
				continue;
			}
			FTexture *ftex = TexMan(id);
			GLuint idxTex = CreateIndexTextureFor(ftex);
			GLuint opacTex = CreateOpacityTextureFor(ftex);
			texCache[key] = idxTex;
			opacCache[key] = opacTex;
			surfTex[i] = idxTex;
			surfOpac[i] = opacTex;
			if(idxTex && uniqueOut)
				++*uniqueOut;
			if(opacTex && maskedOut)
				++*maskedOut;
		}

		// Per-surface draw state, then a stable sort into runs. Stable so that a
		// given mesh always produces the same buffer for the same input, which
		// keeps the offscreen captures the parity tests read reproducible.
		struct SortItem
		{
			MeshDraw state;
			unsigned int surface;
		};
		TArray<SortItem> items(numSurf ? numSurf : 1);
		items.Clear();
		for(unsigned int i = 0; i < numSurf; ++i)
		{
			if(surfTex[i] == 0)
				continue;	// no texture resolved: the old path skipped these too
			const WorldSurface &surf = mesh.surfaces[i];
			// Door leaves, masked walls, and sprites all shade as walls
			// (perpendicular distance, C7 cycle). Walls/doors/masked alpha-test
			// the index-255 colour key; sprites key on raw index 0 instead. A
			// door leaf additionally runs the slide.
			const bool isDoor = surf.kind == WSURF_DoorLeaf;
			const bool isMasked = surf.kind == WSURF_Masked;
			const bool isSprite = surf.kind == WSURF_Sprite;
			SortItem it;
			it.state.tex = surfTex[i];
			it.state.opac = surfOpac[i];
			it.state.kind = (isDoor || isMasked || isSprite) ? WSURF_Wall : surf.kind;
			it.state.masked = (isDoor || isMasked) ? 1 : 0;
			it.state.sprite = isSprite ? 1 : 0;
			it.state.spriteFb = (isSprite && surf.fullbright) ? 1 : 0;
			it.state.spriteLaser = (isSprite && surf.laser) ? 1 : 0;
			it.state.isDoor = isDoor ? 1 : 0;
			// Only a door leaf's slide is read by the shader; forcing the rest to
			// a fixed value keeps them from splitting runs needlessly.
			it.state.slideStyle = isDoor ? surf.slideStyle : 0;
			it.state.slideAmount = isDoor ? surf.slideAmount : 0;
			it.state.first = 0;
			it.state.count = 0;
			it.surface = i;
			items.Push(it);
		}

		// TArray has no begin()/end(); it is contiguous, so sort the raw range.
		SortItem *const first = items.Size() ? &items[0] : NULL;
		std::stable_sort(first, first + items.Size(),
			[](const SortItem &a, const SortItem &b)
			{
				if(a.state.tex != b.state.tex) return a.state.tex < b.state.tex;
				if(a.state.opac != b.state.opac) return a.state.opac < b.state.opac;
				if(a.state.kind != b.state.kind) return a.state.kind < b.state.kind;
				if(a.state.masked != b.state.masked) return a.state.masked < b.state.masked;
				if(a.state.sprite != b.state.sprite) return a.state.sprite < b.state.sprite;
				if(a.state.spriteFb != b.state.spriteFb) return a.state.spriteFb < b.state.spriteFb;
				if(a.state.spriteLaser != b.state.spriteLaser) return a.state.spriteLaser < b.state.spriteLaser;
				if(a.state.isDoor != b.state.isDoor) return a.state.isDoor < b.state.isDoor;
				if(a.state.slideStyle != b.state.slideStyle) return a.state.slideStyle < b.state.slideStyle;
				return a.state.slideAmount < b.state.slideAmount;
			});

		TArray<WorldVertex> ordered(mesh.vertices.Size() ? mesh.vertices.Size() : 1);
		ordered.Clear();
		out.draws.Clear();
		for(unsigned int i = 0; i < items.Size(); ++i)
		{
			const WorldSurface &surf = mesh.surfaces[items[i].surface];
			const GLuint first = (GLuint)ordered.Size();
			for(unsigned int v = 0; v < surf.vertexCount; ++v)
				ordered.Push(mesh.vertices[surf.firstVertex + v]);

			// Extend the run in progress when nothing the shader reads changed.
			if(out.draws.Size() > 0 && SameDrawState(out.draws[out.draws.Size()-1],
				items[i].state))
			{
				out.draws[out.draws.Size()-1].count += surf.vertexCount;
				continue;
			}
			MeshDraw d = items[i].state;
			d.first = first;
			d.count = surf.vertexCount;
			out.draws.Push(d);
		}

		glGenVertexArrays(1, &out.vao);
		glBindVertexArray(out.vao);
		glGenBuffers(1, &out.vbo);
		glBindBuffer(GL_ARRAY_BUFFER, out.vbo);
		if(ordered.Size() > 0)
			glBufferData(GL_ARRAY_BUFFER,
				(GLsizeiptr)(ordered.Size() * sizeof(WorldVertex)),
				&ordered[0], GL_STATIC_DRAW);
		const GLsizei stride = sizeof(WorldVertex);
		glEnableVertexAttribArray(0);
		glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, (void*)0);
		glEnableVertexAttribArray(1);
		glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, (void*)(3*sizeof(float)));
		glEnableVertexAttribArray(2);
		glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, stride, (void*)(5*sizeof(float)));
		glEnableVertexAttribArray(3);
		glVertexAttribPointer(3, 1, GL_FLOAT, GL_FALSE, stride, (void*)(6*sizeof(float)));
	}

	void DestroyMesh(MeshGL &gl)
	{
		if(gl.vbo) glDeleteBuffers(1, &gl.vbo);
		if(gl.vao) glDeleteVertexArrays(1, &gl.vao);
		gl.vbo = gl.vao = 0;
	}

	// =======================================================================
	// Shared world render: build the four meshes + program + uniforms once, then
	// draw the colour (and, for the capture, shade-row debug) passes into the
	// currently bound framebuffer's viewport. Both the world capture and the
	// full-frame compositor drive this so the world pixels are identical.
	// =======================================================================
	// A world render's resources split into persistent (program / palette /
	// colormap / index-texture caches) and per-frame (meshes / VBOs / uniforms).
	// The offscreen captures own their resources (create + destroy per call); the
	// live path (below) *borrows* a persistent set so index textures upload once
	// and survive across frames. `prog != 0` on entry to BuildWorldGL selects the
	// borrowed path; otherwise the resources are created and owned here.
	struct WorldGL
	{
		GLuint prog;
		GLuint paletteTex;
		GLuint colormapTex;
		GLuint c7RampFloorTex;
		TMap<int, GLuint> ownTexCache;   // used only when ownResources
		TMap<int, GLuint> ownOpacCache;
		TMap<int, GLuint> *texCache;     // -> own caches, or a borrowed persistent set
		TMap<int, GLuint> *opacCache;
		bool ownResources;
		// The static mesh's GL buffers belong to the cross-frame cache rather
		// than to this frame, so DestroyWorldGL must not free them.
		bool staticBorrowed;
		// Cross-frame static-geometry cache, supplied by the live path. NULL on
		// the offscreen paths, which are one-shot and have nothing to reuse.
		WorldMesh *cacheMesh;
		MeshGL    *cacheGL;
		bool      *cacheValid;
		WorldMesh mesh, dynMesh, maskedMesh, spriteMesh;
		MeshGL staticGL, dynGL, maskedGL, spriteGL;
		SurfaceUniforms su;
		GLint uDebug;
		WorldGL() : prog(0), paletteTex(0), colormapTex(0), c7RampFloorTex(0),
			texCache(NULL), opacCache(NULL), ownResources(true),
			staticBorrowed(false), cacheMesh(NULL), cacheGL(NULL),
			cacheValid(NULL), uDebug(-1) {}
	};

	// Build meshes/program/uniforms for a W x H world render (aspect W/H). The
	// caller must have a current GL context. Returns false if the scene is empty
	// or the program failed to build. Palette/colormap stay bound to units 1/2.
	bool BuildWorldGL(WorldGL &w, int W, int H)
	{
		// Build the static world mesh plus the dynamic (door/pushwall) mesh. The
		// dynamic mesh is interpolated at the current sub-tic alpha so doors and
		// pushwalls render at their exact fractional positions.
		{
			GLProf::Scope s(GLProf::B_Static);
			WorldBuilder::BuildStatic(map, w.mesh);
		}
		const float alpha = R_GetInterpolationAlpha();
		{
			GLProf::Scope s(GLProf::B_Dynamic);
			WorldBuilder::BuildDynamic(map, w.dynMesh, alpha);
		}
		// Masked geometry needs the camera position for its back-face cull (draw
		// only the pane nearest the viewer, like the raycaster's entry-face DDA).
		AActor *maskCam = players[ConsolePlayer].camera
			? players[ConsolePlayer].camera : players[ConsolePlayer].mo;
		{
			GLProf::Scope s(GLProf::B_Masked);
			WorldBuilder::BuildMasked(map, w.maskedMesh,
				(float)maskCam->x / (float)TILEGLOBAL,
				(float)maskCam->y / (float)TILEGLOBAL);
		}

		// Actor sprites and the camera are drawn at their interpolated sub-tic
		// transform, exactly as the software frame did: apply the interpolation,
		// refresh the view basis so the billboard builder is consistent with the
		// interpolated camera, build the sprites, capture the camera transform,
		// then restore authoritative simulation state.
		Interpolation::Apply(alpha);
		CalcViewVariables();
		{
			GLProf::Scope s(GLProf::B_Sprites);
			WorldBuilder::BuildSprites(map, w.spriteMesh);
		}
		AActor *cam = players[ConsolePlayer].camera
			? players[ConsolePlayer].camera : players[ConsolePlayer].mo;
		const fixed camXFixed = cam->x;
		const fixed camYFixed = cam->y;
		const angle_t camAngle = cam->angle;
		const int32_t camPitch = (int32_t)cam->pitch;
		const float camFOV = players[ConsolePlayer].FOV;
		Interpolation::Restore();

		// Mesh census. Useful once per offscreen capture, which is what the
		// world/parity tests read -- but BuildWorldGL runs every frame on the
		// live path, so printing it there buries the console under thousands of
		// lines whenever a door is moving. `prog == 0` on entry is the offscreen
		// path (see above); the live path has to ask for it with vid_gldebug.
		const bool logMesh = w.prog == 0 || vid_gldebug;
		if(logMesh)
			Printf("GL world: static walls=%u floors=%u ceilings=%u verts=%u; "
				"dynamic faces=%u verts=%u (alpha=%.2f); masked faces=%u verts=%u; "
				"sprite faces=%u verts=%u\n",
				w.mesh.wallFaces, w.mesh.floorTiles, w.mesh.ceilingTiles,
				(unsigned)w.mesh.vertices.Size(), w.dynMesh.wallFaces,
				(unsigned)w.dynMesh.vertices.Size(), alpha,
				w.maskedMesh.wallFaces, (unsigned)w.maskedMesh.vertices.Size(),
				w.spriteMesh.wallFaces, (unsigned)w.spriteMesh.vertices.Size());
		if(w.mesh.vertices.Size() == 0 && w.dynMesh.vertices.Size() == 0 &&
			w.maskedMesh.vertices.Size() == 0 && w.spriteMesh.vertices.Size() == 0)
			return false;

		// Resources: create + own them when none were supplied (offscreen path);
		// otherwise the caller borrowed a persistent set (live path).
		if(w.prog == 0)
		{
			w.ownResources = true;
			w.prog = GLShader::Build(kVert, kFrag, "world-indexed");
			if(!w.prog)
				return false;
			w.paletteTex = CreatePaletteTexture();
			int colormapRows = 0;
			w.colormapTex = CreateColormapTexture(colormapRows);
			w.c7RampFloorTex = CreateC7RampFloorTexture();
			w.texCache = &w.ownTexCache;
			w.opacCache = &w.ownOpacCache;
		}
		else
		{
			w.ownResources = false;	// borrowed persistent prog/palette/colormap/caches
		}
		const int colormapRows = NUMCOLORMAPS;

		unsigned int uniqueTextures = 0, maskedTextures = 0;
		{
			GLProf::Scope s(GLProf::B_Upload);
			// The static mesh is the same tens of thousands of vertices on most
			// frames -- it only changes when the map's geometry does. Only the
			// live path caches it; the offscreen captures own their resources
			// and are one-shot, so there is nothing for them to reuse.
			if(w.cacheMesh != NULL)
			{
				if(!*w.cacheValid || !MeshContentEqual(w.mesh, *w.cacheMesh))
				{
					DestroyMesh(*w.cacheGL);
					UploadMesh(w.mesh, *w.texCache, *w.opacCache,
						*w.cacheGL, &uniqueTextures, &maskedTextures);
					*w.cacheMesh = w.mesh;
					*w.cacheValid = true;
				}
				w.staticGL = *w.cacheGL;
				w.staticBorrowed = true;
			}
			else
				UploadMesh(w.mesh, *w.texCache, *w.opacCache, w.staticGL,
					&uniqueTextures, &maskedTextures);
			UploadMesh(w.dynMesh, *w.texCache, *w.opacCache, w.dynGL,
				&uniqueTextures, &maskedTextures);
			UploadMesh(w.maskedMesh, *w.texCache, *w.opacCache, w.maskedGL,
				&uniqueTextures, &maskedTextures);
			UploadMesh(w.spriteMesh, *w.texCache, *w.opacCache, w.spriteGL,
				&uniqueTextures, &maskedTextures);
		}
		// Same rule: once per offscreen capture, or on demand. The live path
		// uploads new textures whenever an unseen wall comes into view, so this
		// is intermittent rather than per-frame, but it is still noise.
		if(w.ownResources || (uniqueTextures && vid_gldebug))
			Printf("GL world: uploaded %u unique index textures (%u with opacity).\n",
				uniqueTextures, maskedTextures);

		// --- projection matched to the software raycaster (CalcProjection) ---
		// (interpolated transform captured above). The raycaster is a pinhole
		// camera whose eye sits `focallength` behind the player along the view
		// direction: horizontally it maps screen-x offset = scale*x/z, and
		// vertically a full-height wall at distance z projects to (heightnumerator
		// << 8)/z pixels. Replicating those exactly -- instead of a raw 90 deg
		// symmetric frustum -- gives the GL its true ~72.4 deg field of view, the
		// correct near-sprite scale, and wall/door depth that matches the software
		// renderer. Without it, near geometry read as a wider fisheye: sprites
		// looked "cut and pasted" and door jambs bulged into hollow alcoves.
		const float camX = (float)camXFixed / (float)TILEGLOBAL;
		const float camY = (float)camYFixed / (float)TILEGLOBAL;
		const float yaw = (float)((double)camAngle / 4294967296.0 * 2.0 * kPi);
		(void)camPitch; (void)camFOV;	// pitch -> horizon shift; FOV -> `scale` below

		// ECWolf view direction convention: (cos a, -sin a) in the XY plane. Pitch
		// is NOT a camera rotation in the raycaster -- it slides the horizon
		// (viewshift) so verticals never keystone; we reproduce that with a
		// principal-point offset (proj.m[9]) rather than tilting `fwd`.
		const float vc = cosf(yaw), vs = sinf(yaw);
		float fwd[3] = { vc, -vs, 0.0f };
		float up[3]  = { 0.0f, 0.0f, 1.0f };

		// The vertical world unit differs from the horizontal one: a full-height
		// wall spans map plane `depth` tiles (Corridor 7: depth=64) in the
		// software's fixed Z, i.e. (depth<<FRACBITS), whereas one floor tile is
		// TILEGLOBAL across. The GL mesh draws each wall a unit cube (z in [0,1]),
		// so 1.0 GL == (depth<<FRACBITS) fixed vertically but == TILEGLOBAL fixed
		// horizontally. Convert viewz / heights through the vertical unit, and
		// focallength (a horizontal distance) through TILEGLOBAL.
		const int   wallDepth  = map->GetPlane(0).depth;
		const double vWallFixed = (double)wallDepth * (double)TILEGLOBAL;

		// Eye pushed back by focallength -- exactly viewx/viewy -- and raised to
		// the software eye height: the floor is GL z=0, ceiling z=1, and the eye
		// sits -viewz (bob + view height) up, expressed in the vertical unit.
		const float focalTiles = (float)focallength / (float)TILEGLOBAL;
		float eye[3] = {
			camX - focalTiles * vc,
			camY + focalTiles * vs,
			(float)(-(double)viewz / vWallFixed)
		};

		Mat4 proj;
		for(int i = 0; i < 16; ++i) proj.m[i] = 0.0f;
		const float znear = 0.02f, zfar = 256.0f;
		// Horizontal focal = `scale` px. Negate clip X because Corridor 7's world
		// is visually left-handed (X east, Y south, Z up) with the camera facing
		// (cos a, -sin a): a standard right-handed LookAt would render the whole
		// level left-right reversed (text backwards, layout mirrored, turning
		// inverted). Back-face culling is disabled, so the winding flip is safe.
		proj.m[0]  = -2.0f * (float)scale / (float)viewwidth;
		// Vertical focal in NDC. The software's per-frame wall height for a full
		// wall at distance z is (heightnumerator<<8)/z px; matched into this GL
		// unit space (1.0 GL = depth tiles vertically) this is
		// m[5] = 2*heightnumerator*depth/(TILEGLOBAL*viewheight). It already folds
		// in the yaspect pixel-shape correction, so vertical FOV (~40 deg here) is
		// independent of the raw aspect ratio -- exactly like the raycaster.
		proj.m[5]  = (float)((double)heightnumerator * wallDepth /
			(32768.0 * (double)viewheight));
		// Look up/down: offset the horizon by viewshift px so verticals stay
		// vertical, exactly as the software plane/wall passes do.
		proj.m[9]  = -2.0f * (float)viewshift / (float)viewheight;
		proj.m[10] = (zfar + znear) / (znear - zfar);
		proj.m[11] = -1.0f;
		proj.m[14] = (2.0f * zfar * znear) / (znear - zfar);

		Mat4 view = LookAt(eye, fwd, up);

		// --- shading uniforms mirror the software renderer exactly ---
		const int shade = LIGHT2SHADE(gLevelLight + r_extralight);
		const bool corridor7 = IWad::CheckGameFilter("Corridor7");
		const int cyclePhase = (int)((gamestate.TimeCount >> C7_RAMP_CYCLE_SHIFT) & 7);

		// Plane heights exactly as R_DrawPlane receives them: floor = viewz,
		// ceiling = viewz + level depth. The shader takes their magnitude.
		const float floorPlaneH = fabsf((float)viewz);
		const float ceilPlaneH  = fabsf((float)(viewz +
			(map->GetPlane(0).depth << FRACBITS)));

		glUseProgram(w.prog);
		glUniformMatrix4fv(glGetUniformLocation(w.prog, "uProj"), 1, GL_FALSE, proj.m);
		glUniformMatrix4fv(glGetUniformLocation(w.prog, "uView"), 1, GL_FALSE, view.m);
		glUniform1f(glGetUniformLocation(w.prog, "uDepthVis"), (float)r_depthvisibility);
		glUniform1f(glGetUniformLocation(w.prog, "uHeightNum"), (float)heightnumerator);
		glUniform1f(glGetUniformLocation(w.prog, "uShade"), (float)shade);
		glUniform1f(glGetUniformLocation(w.prog, "uMaxLightVis"), (float)gLevelMaxLightVis);
		glUniform1i(glGetUniformLocation(w.prog, "uNumColormaps"), colormapRows);
		glUniform1i(glGetUniformLocation(w.prog, "uCyclePhase"), cyclePhase);
		glUniform1i(glGetUniformLocation(w.prog, "uRemap15"), (int)GPalette.Remap[15]);
		glUniform1i(glGetUniformLocation(w.prog, "uRemap254"), (int)GPalette.Remap[254]);
		glUniform1i(glGetUniformLocation(w.prog, "uRemap208"), (int)GPalette.Remap[208]);
		glUniform1i(glGetUniformLocation(w.prog, "uRemap239"), (int)GPalette.Remap[239]);
		glUniform1i(glGetUniformLocation(w.prog, "uCorridor7"), corridor7 ? 1 : 0);
		glUniform1i(glGetUniformLocation(w.prog, "uMaskColor"), (int)GPalette.Remap[255]);
		glUniform1i(glGetUniformLocation(w.prog, "uExtraLight"), r_extralight);
		glUniform1i(glGetUniformLocation(w.prog, "uViewW"), W);
		glUniform1i(glGetUniformLocation(w.prog, "uDither"), 1);
		glUniform1f(glGetUniformLocation(w.prog, "uHorizon"), (float)H * 0.5f);
		// Sprite colour-cycle / laser-dissolve clock and the lit-laser colour
		// index (fullbright white, matching ScaleSprite's ColorMatcher.Pick).
		glUniform1i(glGetUniformLocation(w.prog, "uPhase"),
			(int)(gamestate.TimeCount >> 3));
		glUniform1i(glGetUniformLocation(w.prog, "uLaserColor"),
			(int)ColorMatcher.Pick(0xFF, 0xFF, 0xFF));

		w.su.uIndexTex    = glGetUniformLocation(w.prog, "uIndexTex");
		w.su.uOpacityTex  = glGetUniformLocation(w.prog, "uOpacityTex");
		w.su.uHasOpacity  = glGetUniformLocation(w.prog, "uHasOpacity");
		w.su.uMasked      = glGetUniformLocation(w.prog, "uMasked");
		w.su.uSurfKind    = glGetUniformLocation(w.prog, "uSurfKind");
		w.su.uPlaneHeight = glGetUniformLocation(w.prog, "uPlaneHeight");
		w.su.uSlide       = glGetUniformLocation(w.prog, "uSlide");
		w.su.uSlideStyle  = glGetUniformLocation(w.prog, "uSlideStyle");
		w.su.uSlideAmount = glGetUniformLocation(w.prog, "uSlideAmount");
		w.su.uSprite           = glGetUniformLocation(w.prog, "uSprite");
		w.su.uSpriteFullbright = glGetUniformLocation(w.prog, "uSpriteFullbright");
		w.su.uSpriteLaser      = glGetUniformLocation(w.prog, "uSpriteLaser");
		w.su.floorPlaneH  = floorPlaneH;
		w.su.ceilPlaneH   = ceilPlaneH;
		w.uDebug = glGetUniformLocation(w.prog, "uDebug");
		// Texture filtering is a whole-frame setting, so it is set once here
		// rather than per surface. 0 keeps the renderer bit-identical to the
		// unfiltered path, which is what every parity gate measures.
		glUniform1i(glGetUniformLocation(w.prog, "uFilter"),
			clamp(vid_glfilter, 0, 2));

		// Palette (unit 1) and colormap (unit 2) are shared across every surface.
		glActiveTexture(GL_TEXTURE1);
		glBindTexture(GL_TEXTURE_2D, w.paletteTex);
		glUniform1i(glGetUniformLocation(w.prog, "uPaletteTex"), 1);
		glActiveTexture(GL_TEXTURE2);
		glBindTexture(GL_TEXTURE_2D, w.colormapTex);
		glUniform1i(glGetUniformLocation(w.prog, "uColormapTex"), 2);
		glUniform1i(glGetUniformLocation(w.prog, "uC7RampFloor"), 6);
		return true;
	}

	// Render the world colour pass into the bound FBO's current viewport. Static
	// opaque world first, then dynamic door/pushwall geometry, then masked panes
	// (biased toward the viewer so they don't z-fight a coplanar wall behind
	// them), then sprite billboards -- all sharing one clear and depth buffer.
	void DrawWorldColourPass(WorldGL &w)
	{
		glUseProgram(w.prog);
		glActiveTexture(GL_TEXTURE1);
		glBindTexture(GL_TEXTURE_2D, w.paletteTex);
		glActiveTexture(GL_TEXTURE2);
		glBindTexture(GL_TEXTURE_2D, w.colormapTex);
		glActiveTexture(GL_TEXTURE6);
		glBindTexture(GL_TEXTURE_2D, w.c7RampFloorTex);
		glUniform1i(w.uDebug, 0);
		glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
		glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
		RenderMesh(w.mesh, w.staticGL, w.su);
		RenderMesh(w.dynMesh, w.dynGL, w.su);
		glEnable(GL_POLYGON_OFFSET_FILL);
		glPolygonOffset(-1.0f, -1.0f);
		RenderMesh(w.maskedMesh, w.maskedGL, w.su);
		glDisable(GL_POLYGON_OFFSET_FILL);
		RenderMesh(w.spriteMesh, w.spriteGL, w.su);
	}

	// Shade-row debug visualization of the same scene (capture exit-gate check).
	void DrawWorldDebugPass(WorldGL &w)
	{
		glUseProgram(w.prog);
		glUniform1i(w.uDebug, 1);
		glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
		RenderMesh(w.mesh, w.staticGL, w.su);
		RenderMesh(w.dynMesh, w.dynGL, w.su);
		glEnable(GL_POLYGON_OFFSET_FILL);
		glPolygonOffset(-1.0f, -1.0f);
		RenderMesh(w.maskedMesh, w.maskedGL, w.su);
		glDisable(GL_POLYGON_OFFSET_FILL);
		RenderMesh(w.spriteMesh, w.spriteGL, w.su);
	}

	void DestroyWorldGL(WorldGL &w)
	{
		// Per-frame VBOs are always freed; the persistent resources (program,
		// palette, colormap, index-texture caches) are freed only when owned.
		if(w.staticBorrowed)
			w.staticGL = MeshGL();	// owned by gLive.staticCacheGL
		DestroyMesh(w.staticGL);
		DestroyMesh(w.dynGL);
		DestroyMesh(w.maskedGL);
		DestroyMesh(w.spriteGL);
		if(!w.ownResources)
			return;
		if(w.texCache)
		{
			TMapIterator<int, GLuint> it(*w.texCache);
			TMap<int, GLuint>::Pair *pair;
			while(it.NextPair(pair))
				if(pair->Value)
					glDeleteTextures(1, &pair->Value);
		}
		if(w.opacCache)
		{
			TMapIterator<int, GLuint> ito(*w.opacCache);
			TMap<int, GLuint>::Pair *pair;
			while(ito.NextPair(pair))
				if(pair->Value)
					glDeleteTextures(1, &pair->Value);
		}
		if(w.paletteTex) glDeleteTextures(1, &w.paletteTex);
		if(w.colormapTex) glDeleteTextures(1, &w.colormapTex);
		if(w.c7RampFloorTex) glDeleteTextures(1, &w.c7RampFloorTex);
		if(w.prog) glDeleteProgram(w.prog);
	}

	// Draw a screen-space quad covering the NDC rect [x0,x1]x[y0,y1] with UVs
	// interpolated so the (x0,y0) corner is (u0,v0) and (x1,y1) is (u1,v1).
	void DrawScreenQuad(float x0, float y0, float x1, float y1,
		float u0, float v0, float u1, float v1)
	{
		const float verts[] = {
			x0, y0, u0, v0,
			x1, y0, u1, v0,
			x1, y1, u1, v1,
			x0, y0, u0, v0,
			x1, y1, u1, v1,
			x0, y1, u0, v1,
		};
		GLuint vao = 0, vbo = 0;
		glGenVertexArrays(1, &vao);
		glBindVertexArray(vao);
		glGenBuffers(1, &vbo);
		glBindBuffer(GL_ARRAY_BUFFER, vbo);
		glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
		glEnableVertexAttribArray(0);
		glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4*sizeof(float), (void*)0);
		glEnableVertexAttribArray(1);
		glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4*sizeof(float),
			(void*)(2*sizeof(float)));
		glDrawArrays(GL_TRIANGLES, 0, 6);
		glDeleteBuffers(1, &vbo);
		glDeleteVertexArrays(1, &vao);
	}

	// Measure which view texels PlayFrame's 2D-over-the-view overlays paint, by
	// replaying them over two different backgrounds directly on the canvas and
	// keeping the texels that come out identical (the live path's
	// R_GLLiveDrawViewOverlay does the same as they are drawn). The weapon can be
	// measured in scratch buffers because it blits through `vbuf`, but these draw
	// through `screen`, so the canvas itself is the only place to measure them --
	// hence save, measure, restore. The restore is byte-exact: the replayed values
	// are what a single draw already put there.
	// Fills `cover` (vw*vh, 1 = painted); leaves the canvas as it found it.
	void MeasureViewOverlayCover(byte *wbuf, int pitch, int vx, int vy,
		int vw, int vh, TArray<unsigned char> &cover)
	{
		const unsigned n = (unsigned)(vw * vh);
		cover.Resize(n);
		memset(&cover[0], 0, n);

		const byte bgA = GPalette.Remap[0];
		const byte bgB = (byte)(bgA ^ 0xFF);
		TArray<unsigned char> saved(n), passA(n), passB(n);
		saved.Resize(n); passA.Resize(n); passB.Resize(n);

		for(int r = 0; r < vh; ++r)
			memcpy(&saved[r * vw], wbuf + (vy + r) * pitch + vx, (size_t)vw);

		for(int r = 0; r < vh; ++r)
			memset(wbuf + (vy + r) * pitch + vx, bgA, (size_t)vw);
		R_DrawPlayViewOverlays();
		for(int r = 0; r < vh; ++r)
			memcpy(&passA[r * vw], wbuf + (vy + r) * pitch + vx, (size_t)vw);

		for(int r = 0; r < vh; ++r)
			memset(wbuf + (vy + r) * pitch + vx, bgB, (size_t)vw);
		R_DrawPlayViewOverlays();
		for(int r = 0; r < vh; ++r)
			memcpy(&passB[r * vw], wbuf + (vy + r) * pitch + vx, (size_t)vw);

		for(int r = 0; r < vh; ++r)
			memcpy(wbuf + (vy + r) * pitch + vx, &saved[r * vw], (size_t)vw);

		for(unsigned i = 0; i < n; ++i)
			cover[i] = (passA[i] == passB[i]) ? 1 : 0;
	}

	// Build the 2D overlay (index + opacity, full frame) from the engine's live
	// 8-bit framebuffer. Everything outside the 3D view sub-rect is opaque 2D
	// (HUD/status bar/menus/text). Inside the view rect, only the player weapon
	// and the 2D drawn over the world are opaque; the rest is transparent so the
	// GPU world shows through. Both are detected the same robust way -- redraw
	// over two different backgrounds and keep the pixels that come out identical
	// -- because a masked blit overwrites deterministically, so a texel is
	// "painted" iff it is background-independent, whatever colour it landed in.
	void BuildOverlay(int FW, int FH, int vx, int vy, int vw, int vh,
		GLuint &idxTexOut, GLuint &opacTexOut, unsigned int &viewOpaqueOut)
	{
		const int pitch = screen->GetPitch();
		byte *const wbuf = (byte *)screen->GetBuffer();

		// Overlay coverage first: it writes to (and restores) the canvas, so it
		// must run before the frame is snapshotted into idx below.
		TArray<unsigned char> ovCover;
		MeasureViewOverlayCover(wbuf, pitch, vx, vy, vw, vh, ovCover);

		const BYTE *membuf = wbuf;
		TArray<unsigned char> idx((unsigned)(FW * FH));
		TArray<unsigned char> opac((unsigned)(FW * FH));
		idx.Resize((unsigned)(FW * FH));
		opac.Resize((unsigned)(FW * FH));
		for(int y = 0; y < FH; ++y)
			for(int x = 0; x < FW; ++x)
			{
				idx[y * FW + x] = membuf[y * pitch + x];
				opac[y * FW + x] = 255;	// opaque 2D by default (HUD / menus)
			}

		// Weapon coverage over two backgrounds in scratch full-frame buffers.
		TArray<unsigned char> sa((unsigned)(pitch * FH));
		TArray<unsigned char> sb((unsigned)(pitch * FH));
		sa.Resize((unsigned)(pitch * FH));
		sb.Resize((unsigned)(pitch * FH));
		for(int r = 0; r < vh; ++r)
		{
			memset(&sa[(vy + r) * pitch + vx], 0x00, vw);
			memset(&sb[(vy + r) * pitch + vx], 0xFF, vw);
		}

		byte *saveVbuf = vbuf;
		unsigned savePitch = vbufPitch;
		const unsigned viewOfs = (unsigned)(vy * pitch + vx);
		vbufPitch = (unsigned)pitch;
		vbuf = &sa[0] + viewOfs; DrawPlayerWeapon();
		vbuf = &sb[0] + viewOfs; DrawPlayerWeapon();
		vbuf = saveVbuf;
		vbufPitch = savePitch;

		unsigned int viewOpaque = 0;
		for(int r = 0; r < vh; ++r)
			for(int c = 0; c < vw; ++c)
			{
				const int fx = vx + c, fy = vy + r;
				const unsigned char a = sa[fy * pitch + fx];
				const unsigned char b = sb[fy * pitch + fx];
				if(ovCover[r * vw + c])	// 2D over the view -- keep what it left
				{
					opac[fy * FW + fx] = 255;
					++viewOpaque;
				}
				else if(a == b)	// weapon painted the same index over both -> opaque
				{
					idx[fy * FW + fx] = a;
					opac[fy * FW + fx] = 255;
					++viewOpaque;
				}
				else		// background survived -> transparent, world shows
					opac[fy * FW + fx] = 0;
			}
		viewOpaqueOut = viewOpaque;

		idxTexOut = CreateR8UITexture(&idx[0], FW, FH);
		opacTexOut = CreateR8UITexture(&opac[0], FW, FH);
	}
}

bool R_GLWorldCapture(const char *outPath)
{
	if(map == NULL)
	{
		Printf("GL world: no map loaded.\n");
		return false;
	}

	int W = viewwidth  > 0 ? viewwidth  : 320;
	int H = viewheight > 0 ? viewheight : 200;

	GLDevice dev;
	if(!dev.Create(W, H, false, /*hidden=*/true, "EC7Wolf GL world"))
		return false;

	WorldGL wr;
	if(!BuildWorldGL(wr, W, H))
	{
		DestroyWorldGL(wr);
		dev.Destroy();
		return false;
	}

	// Offscreen colour + depth target.
	GLuint fbo = 0, colorTex = 0, depthRb = 0;
	glGenFramebuffers(1, &fbo);
	glBindFramebuffer(GL_FRAMEBUFFER, fbo);
	glGenTextures(1, &colorTex);
	glBindTexture(GL_TEXTURE_2D, colorTex);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, colorTex, 0);
	glGenRenderbuffers(1, &depthRb);
	glBindRenderbuffer(GL_RENDERBUFFER, depthRb);
	glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, W, H);
	glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, depthRb);
	if(glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
	{
		Printf("GL world: framebuffer incomplete.\n");
		DestroyWorldGL(wr);
		dev.Destroy();
		return false;
	}

	glViewport(0, 0, W, H);
	glEnable(GL_DEPTH_TEST);
	glDepthFunc(GL_LESS);
	glDisable(GL_CULL_FACE);	// keep both faces during bring-up

	unsigned char *rgb = new unsigned char[(size_t)W * H * 3];

	// Pass 1: full-fidelity colour.
	DrawWorldColourPass(wr);
	glFinish();
	dev.ReadPixelsRGB(rgb, W, H);

	size_t nonBg = 0;
	for(int i = 0; i < W * H; ++i)
		if(rgb[i*3] || rgb[i*3+1] || rgb[i*3+2]) ++nonBg;
	Printf("GL world: rendered %dx%d, %.1f%% covered.\n",
		W, H, 100.0 * (double)nonBg / (double)(W * H));

	bool wrote = false;
	if(outPath)
		wrote = WritePPM(outPath, rgb, W, H);
	if(wrote)
		Printf("GL world: wrote %s\n", outPath);

	// Pass 2: shade-row debug visualization (exit-gate requirement).
	if(outPath)
	{
		DrawWorldDebugPass(wr);
		glFinish();
		dev.ReadPixelsRGB(rgb, W, H);
		FString dbg;
		dbg.Format("%s.shaderow.ppm", outPath);
		if(WritePPM(dbg.GetChars(), rgb, W, H))
			Printf("GL world: wrote %s\n", dbg.GetChars());
	}

	delete[] rgb;

	DestroyWorldGL(wr);
	glDeleteRenderbuffers(1, &depthRb);
	glDeleteTextures(1, &colorTex);
	glDeleteFramebuffers(1, &fbo);
	dev.Destroy();

	return nonBg > 0;
}

bool R_GLFrameCapture(const char *outPath)
{
	if(map == NULL || screen == NULL)
	{
		Printf("GL frame: no map/screen.\n");
		return false;
	}

	const int FW = screen->GetWidth();
	const int FH = screen->GetHeight();
	int vx = viewscreenx, vy = viewscreeny, vw = viewwidth, vh = viewheight;
	if(vw <= 0 || vh <= 0 || vx + vw > FW || vy + vh > FH)
	{
		// Fullscreen 3D view (viewsize 21): the view covers the whole frame.
		vx = 0; vy = 0; vw = FW; vh = FH;
	}

	GLDevice dev;
	if(!dev.Create(FW, FH, false, /*hidden=*/true, "EC7Wolf GL frame"))
		return false;

	// --- 1) Render the GL 3D world into its own view-sized colour texture. Kept
	// at the exact view dimensions so the world shader's screen-space plane bands
	// / horizon math are identical to the standalone world capture. ---
	WorldGL wr;
	if(!BuildWorldGL(wr, vw, vh))
	{
		DestroyWorldGL(wr);
		dev.Destroy();
		return false;
	}

	GLuint worldFbo = 0, worldTex = 0, worldDepth = 0;
	glGenFramebuffers(1, &worldFbo);
	glBindFramebuffer(GL_FRAMEBUFFER, worldFbo);
	glGenTextures(1, &worldTex);
	glBindTexture(GL_TEXTURE_2D, worldTex);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, vw, vh, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, worldTex, 0);
	glGenRenderbuffers(1, &worldDepth);
	glBindRenderbuffer(GL_RENDERBUFFER, worldDepth);
	glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, vw, vh);
	glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, worldDepth);
	if(glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
	{
		Printf("GL frame: world framebuffer incomplete.\n");
		DestroyWorldGL(wr);
		dev.Destroy();
		return false;
	}
	glViewport(0, 0, vw, vh);
	glEnable(GL_DEPTH_TEST);
	glDepthFunc(GL_LESS);
	glDisable(GL_CULL_FACE);
	DrawWorldColourPass(wr);
	glFinish();

	// --- 2) Build the 2D overlay from the engine's 8-bit frame (HUD + weapon +
	// menus + text), view region transparent except the weapon. ---
	GLuint overlayIdx = 0, overlayOpac = 0;
	unsigned int viewOpaque = 0;
	BuildOverlay(FW, FH, vx, vy, vw, vh, overlayIdx, overlayOpac, viewOpaque);
	Printf("GL frame: 2D overlay opaque texels over the 3D view = %u "
		"(player weapon / world-overlaid 2D).\n", viewOpaque);

	// --- 3) Composite into the full-frame target: world blit into the view
	// sub-rect, then the 2D overlay over the whole frame with transparent-key
	// discard. ---
	GLuint frameFbo = 0, frameTex = 0;
	glGenFramebuffers(1, &frameFbo);
	glBindFramebuffer(GL_FRAMEBUFFER, frameFbo);
	glGenTextures(1, &frameTex);
	glBindTexture(GL_TEXTURE_2D, frameTex);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, FW, FH, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, frameTex, 0);
	if(glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
	{
		Printf("GL frame: composite framebuffer incomplete.\n");
		glDeleteTextures(1, &overlayIdx);
		glDeleteTextures(1, &overlayOpac);
		glDeleteTextures(1, &worldTex);
		glDeleteRenderbuffers(1, &worldDepth);
		glDeleteFramebuffers(1, &worldFbo);
		DestroyWorldGL(wr);
		dev.Destroy();
		return false;
	}

	GLuint sprog = GLShader::Build(kScreenVert, kScreenFrag, "screen-composite");
	if(!sprog)
	{
		glDeleteTextures(1, &overlayIdx);
		glDeleteTextures(1, &overlayOpac);
		glDeleteTextures(1, &frameTex);
		glDeleteFramebuffers(1, &frameFbo);
		glDeleteTextures(1, &worldTex);
		glDeleteRenderbuffers(1, &worldDepth);
		glDeleteFramebuffers(1, &worldFbo);
		DestroyWorldGL(wr);
		dev.Destroy();
		return false;
	}

	glViewport(0, 0, FW, FH);
	glDisable(GL_DEPTH_TEST);
	glDisable(GL_POLYGON_OFFSET_FILL);
	glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
	glClear(GL_COLOR_BUFFER_BIT);

	glUseProgram(sprog);
	const GLint uMode = glGetUniformLocation(sprog, "uMode");
	// Texture units: 0 world RGB, 1 palette, 4 overlay index, 5 overlay opacity.
	glActiveTexture(GL_TEXTURE0);
	glBindTexture(GL_TEXTURE_2D, worldTex);
	glUniform1i(glGetUniformLocation(sprog, "uWorldTex"), 0);
	glActiveTexture(GL_TEXTURE1);
	glBindTexture(GL_TEXTURE_2D, wr.paletteTex);
	glUniform1i(glGetUniformLocation(sprog, "uPaletteTex"), 1);
	glActiveTexture(GL_TEXTURE4);
	glBindTexture(GL_TEXTURE_2D, overlayIdx);
	glUniform1i(glGetUniformLocation(sprog, "uOverlayIdx"), 4);
	glActiveTexture(GL_TEXTURE5);
	glBindTexture(GL_TEXTURE_2D, overlayOpac);
	glUniform1i(glGetUniformLocation(sprog, "uOverlayOpac"), 5);

	// World blit into the view sub-rect. NDC uses a top-down pixel convention
	// (row 0 = top); the world texture is GL bottom-up, so its V is *not* flipped
	// (v=0 at the bottom edge, v=1 at the top edge of the view rect).
	{
		const float nx0 = 2.0f * (float)vx / (float)FW - 1.0f;
		const float nx1 = 2.0f * (float)(vx + vw) / (float)FW - 1.0f;
		const float nyTop = 1.0f - 2.0f * (float)vy / (float)FH;
		const float nyBot = 1.0f - 2.0f * (float)(vy + vh) / (float)FH;
		glUniform1i(uMode, 0);
		DrawScreenQuad(nx0, nyBot, nx1, nyTop, 0.0f, 0.0f, 1.0f, 1.0f);
	}

	// 2D overlay over the whole frame. The overlay buffer is top-down, so its V
	// is flipped against NDC (v=1 at the bottom edge, v=0 at the top edge).
	{
		glUniform1i(uMode, 1);
		DrawScreenQuad(-1.0f, -1.0f, 1.0f, 1.0f, 0.0f, 1.0f, 1.0f, 0.0f);
	}
	glFinish();

	unsigned char *rgb = new unsigned char[(size_t)FW * FH * 3];
	dev.ReadPixelsRGB(rgb, FW, FH);

	size_t nonBg = 0;
	for(int i = 0; i < FW * FH; ++i)
		if(rgb[i*3] || rgb[i*3+1] || rgb[i*3+2]) ++nonBg;
	Printf("GL frame: composited %dx%d (view %dx%d at %d,%d), %.1f%% covered.\n",
		FW, FH, vw, vh, vx, vy, 100.0 * (double)nonBg / (double)(FW * FH));

	bool wrote = false;
	if(outPath)
		wrote = WritePPM(outPath, rgb, FW, FH);
	if(wrote)
		Printf("GL frame: wrote %s\n", outPath);

	delete[] rgb;

	glDeleteProgram(sprog);
	glDeleteTextures(1, &overlayIdx);
	glDeleteTextures(1, &overlayOpac);
	glDeleteTextures(1, &frameTex);
	glDeleteFramebuffers(1, &frameFbo);
	glDeleteTextures(1, &worldTex);
	glDeleteRenderbuffers(1, &worldDepth);
	glDeleteFramebuffers(1, &worldFbo);
	DestroyWorldGL(wr);
	dev.Destroy();

	return nonBg > 0;
}

// ===========================================================================
//
// Phase 10 live present. Unlike the offscreen captures, this owns persistent GL
// resources on the *game window's* context (created by SDLFB when vid_renderer
// selects OpenGL) and composites every presented frame: the GL 3D world into
// the view sub-rectangle, then the engine's live 8-bit 2D layer over it with the
// view region's compositor-key texels made transparent.
//
// ===========================================================================

namespace
{
	// --- GL debug output + resource ledger (renderer redesign Phase 11) --------
	//
	// Hardening instrumentation for the live GL path. Both are opt-in via
	// vid_gldebug (config Vid_GLDebug or --gl-debug) and cost nothing when off.

	// KHR_debug message callback: routes driver diagnostics into the console.
	void GLAPIENTRY GLDebugCallback(GLenum source, GLenum type, GLuint id,
		GLenum severity, GLsizei, const GLchar *message, const void *)
	{
		if(severity == GL_DEBUG_SEVERITY_NOTIFICATION)
			return;	// skip buffer-created / verbose notes
		const char *sev = severity == GL_DEBUG_SEVERITY_HIGH ? "HIGH" :
			severity == GL_DEBUG_SEVERITY_MEDIUM ? "MEDIUM" : "LOW";
		Printf("GL debug [%s]: %s\n", sev, message ? message : "");
		(void)source; (void)type; (void)id;
	}

	bool gGLDebugInstalled = false;
	void InstallGLDebug()
	{
		if(gGLDebugInstalled || !vid_gldebug)
			return;
		gGLDebugInstalled = true;	// attempt once per process
		if(!epoxy_has_gl_extension("GL_KHR_debug"))
		{
			Printf("GL debug: GL_KHR_debug unavailable; using glGetError checks.\n");
			return;
		}
		glEnable(GL_DEBUG_OUTPUT);
		glEnable(GL_DEBUG_OUTPUT_SYNCHRONOUS);	// callback on the offending call
		glDebugMessageCallback(GLDebugCallback, NULL);
		glDebugMessageControl(GL_DONT_CARE, GL_DONT_CARE, GL_DONT_CARE,
			0, NULL, GL_TRUE);
		Printf("GL debug: KHR_debug callback installed.\n");
	}

	// Drain glGetError after a live stage; a no-op unless vid_gldebug is set.
	void GLCheckErrors(const char *tag)
	{
		if(!vid_gldebug)
			return;
		GLenum e;
		while((e = glGetError()) != GL_NO_ERROR)
			Printf("GL error 0x%04x after %s\n", (unsigned)e, tag ? tag : "?");
	}

	// Live GL object ledger: counts the persistent / per-present objects the live
	// module itself allocates so a leak surfaces as a nonzero balance at shutdown.
	// Cache textures (created inside the shared mesh uploader) are excluded and
	// audited separately via the cache map sizes.
	struct GLLedger
	{
		long tex, fbo, rbo, prog;
		GLLedger() : tex(0), fbo(0), rbo(0), prog(0) {}
	};
	GLLedger gLedger;

	struct GLLive
	{
		bool   inited;
		GLuint prog;         // world-indexed (kVert/kFrag)
		GLuint screenProg;   // composite (kScreenVert/kScreenFrag)
		GLuint paletteTex;
		GLuint colormapTex;
		GLuint c7RampFloorTex;
		TMap<int, GLuint> texCache;    // persistent index-texture cache
		TMap<int, GLuint> opacCache;
		const void *lastMap;           // invalidate caches on level change
		GLuint worldFbo, worldTex, worldDepth;
		int    worldW, worldH;
		// Multisampled render target, resolved into worldTex each frame. Zero
		// when antialiasing is off, which is the default.
		GLuint msaaFbo, msaaColor, msaaDepth;
		int    worldSamples;
		bool   haveWorld;              // a world was rendered for this frame
		int    vx, vy, vw, vh, fw, fh; // view rect / frame size (8-bit space)
		TArray<unsigned char> weaponCover; // per-view-rect: 1 where the weapon drew
		int    wcx, wcy, wcw, wch;     // weapon-cover rect (frame coords)
		bool   haveWeaponCover;        // weaponCover is valid for this frame
		TArray<unsigned char> overlayCover; // per-view-rect: 1 where post-world 2D drew
		bool   haveOverlayCover;       // overlayCover is valid for this frame
		FString  capPath;              // headless: last presented frame is kept here
		TArray<unsigned char> lastRGB; // most recent presented frame (top-down RGB)
		int    lastW, lastH;
		// Static world geometry, kept across frames. Held with the mesh it was
		// built from so reuse is decided by comparing content rather than by
		// guessing when the map's static geometry might have changed -- a
		// pushwall settling into its final cell silently rewrites it, and a
		// missed invalidation would leave a wall standing where the player just
		// walked. Comparing can only fail towards rebuilding.
		WorldMesh staticCacheMesh;
		MeshGL    staticCacheGL;
		bool      staticCacheValid;
		GLLive() : inited(false), prog(0), screenProg(0), paletteTex(0),
			colormapTex(0), c7RampFloorTex(0), lastMap(NULL), worldFbo(0), worldTex(0),
			worldDepth(0), worldW(0), worldH(0),
			msaaFbo(0), msaaColor(0), msaaDepth(0), worldSamples(0),
			haveWorld(false),
			vx(0), vy(0), vw(0), vh(0), fw(0), fh(0),
			wcx(0), wcy(0), wcw(0), wch(0), haveWeaponCover(false),
			haveOverlayCover(false), lastW(0), lastH(0),
			staticCacheValid(false) {}
	};
	GLLive gLive;

	// Set true by SDLFB once it has created a GL context on the game window;
	// gates whether the OpenGL backend goes live or falls back to software.
	bool gLiveContextActive = false;

	void ClearLiveCaches()
	{
		TMapIterator<int, GLuint> it(gLive.texCache);
		TMap<int, GLuint>::Pair *pair;
		while(it.NextPair(pair))
			if(pair->Value)
				glDeleteTextures(1, &pair->Value);
		TMapIterator<int, GLuint> ito(gLive.opacCache);
		while(ito.NextPair(pair))
			if(pair->Value)
				glDeleteTextures(1, &pair->Value);
		gLive.texCache.Clear();
		gLive.opacCache.Clear();

		// The cached static geometry belongs to the map that was just left, and
		// its index textures have just been deleted out from under it.
		DestroyMesh(gLive.staticCacheGL);
		gLive.staticCacheMesh.Clear();
		gLive.staticCacheValid = false;
	}

	void EnsureLiveResources()
	{
		if(gLive.inited)
			return;
		InstallGLDebug();	// first live use: attach KHR_debug if requested
		gLive.prog = GLShader::Build(kVert, kFrag, "world-indexed-live");
		if(gLive.prog) gLedger.prog++;
		gLive.screenProg = GLShader::Build(kScreenVert, kScreenFrag,
			"screen-composite-live");
		if(gLive.screenProg) gLedger.prog++;
		gLive.paletteTex = CreatePaletteTexture();
		if(gLive.paletteTex) gLedger.tex++;
		int rows = 0;
		gLive.colormapTex = CreateColormapTexture(rows);
		if(gLive.colormapTex) gLedger.tex++;
		gLive.c7RampFloorTex = CreateC7RampFloorTexture();
		if(gLive.c7RampFloorTex) gLedger.tex++;
		gLive.inited = gLive.prog && gLive.screenProg &&
			gLive.paletteTex && gLive.colormapTex;
		GLCheckErrors("EnsureLiveResources");
	}

	// Requested MSAA sample count, clamped to what the driver will actually give
	// and to the values the menu offers. 0/1 means no multisampling at all, in
	// which case the single-sampled path below is used unchanged.
	int WantedSamples()
	{
		int want = vid_glmsaa;
		if(want <= 1)
			return 0;
		if(want != 2 && want != 4 && want != 8)
			want = 4;
		GLint maxs = 0;
		glGetIntegerv(GL_MAX_SAMPLES, &maxs);
		if(maxs < 2)
			return 0;
		while(want > maxs)
			want >>= 1;
		return want >= 2 ? want : 0;
	}

	void EnsureWorldFbo(int w, int h)
	{
		const int samples = WantedSamples();
		if(gLive.worldFbo && gLive.worldW == w && gLive.worldH == h &&
			gLive.worldSamples == samples)
			return;
		if(gLive.worldTex)   { glDeleteTextures(1, &gLive.worldTex);      gLedger.tex--; }
		if(gLive.worldDepth) { glDeleteRenderbuffers(1, &gLive.worldDepth); gLedger.rbo--; }
		if(gLive.worldFbo)   { glDeleteFramebuffers(1, &gLive.worldFbo);   gLedger.fbo--; }
		if(gLive.msaaFbo)    { glDeleteFramebuffers(1, &gLive.msaaFbo);    gLedger.fbo--; }
		if(gLive.msaaColor)  { glDeleteRenderbuffers(1, &gLive.msaaColor); gLedger.rbo--; }
		if(gLive.msaaDepth)  { glDeleteRenderbuffers(1, &gLive.msaaDepth); gLedger.rbo--; }
		gLive.msaaFbo = gLive.msaaColor = gLive.msaaDepth = 0;
		gLive.worldSamples = samples;
		glGenFramebuffers(1, &gLive.worldFbo);
		gLedger.fbo++;
		glBindFramebuffer(GL_FRAMEBUFFER, gLive.worldFbo);
		glGenTextures(1, &gLive.worldTex);
		gLedger.tex++;
		glBindTexture(GL_TEXTURE_2D, gLive.worldTex);
		glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA,
			GL_UNSIGNED_BYTE, NULL);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
		glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
			GL_TEXTURE_2D, gLive.worldTex, 0);
		glGenRenderbuffers(1, &gLive.worldDepth);
		gLedger.rbo++;
		glBindRenderbuffer(GL_RENDERBUFFER, gLive.worldDepth);
		glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, w, h);
		glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
			GL_RENDERBUFFER, gLive.worldDepth);
		gLive.worldW = w;
		gLive.worldH = h;

		// Multisampling renders into its own multisampled framebuffer and is
		// resolved into worldTex afterwards, because the compositor samples
		// worldTex as an ordinary texture. Rendering straight to a multisampled
		// texture would work too, but this keeps everything downstream unaware
		// that MSAA is on at all.
		if(samples > 0)
		{
			glGenFramebuffers(1, &gLive.msaaFbo);
			gLedger.fbo++;
			glBindFramebuffer(GL_FRAMEBUFFER, gLive.msaaFbo);
			glGenRenderbuffers(1, &gLive.msaaColor);
			gLedger.rbo++;
			glBindRenderbuffer(GL_RENDERBUFFER, gLive.msaaColor);
			glRenderbufferStorageMultisample(GL_RENDERBUFFER, samples,
				GL_RGBA8, w, h);
			glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
				GL_RENDERBUFFER, gLive.msaaColor);
			glGenRenderbuffers(1, &gLive.msaaDepth);
			gLedger.rbo++;
			glBindRenderbuffer(GL_RENDERBUFFER, gLive.msaaDepth);
			glRenderbufferStorageMultisample(GL_RENDERBUFFER, samples,
				GL_DEPTH_COMPONENT24, w, h);
			glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
				GL_RENDERBUFFER, gLive.msaaDepth);
			if(glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
			{
				// Fall back rather than render nothing.
				Printf("GL: %dx MSAA framebuffer incomplete; antialiasing off.\n",
					samples);
				glDeleteFramebuffers(1, &gLive.msaaFbo);   gLedger.fbo--;
				glDeleteRenderbuffers(1, &gLive.msaaColor); gLedger.rbo--;
				glDeleteRenderbuffers(1, &gLive.msaaDepth); gLedger.rbo--;
				gLive.msaaFbo = gLive.msaaColor = gLive.msaaDepth = 0;
				gLive.worldSamples = 0;
			}
		}
	}

	void UpdateLivePalette()
	{
		// The software renderer resolves every on-screen index through the
		// *effective* palette at scanout: the working palette (which the
		// Corridor 7 visor/infrared/electric modes rewrite in place via
		// V_SetCorridor7PaletteMode) blended with the current full-screen flash
		// (damage/bonus/whiteshift/fade, driven through V_SetBlend). Upload that
		// same palette so full-screen effects appear under GL. GetFlashedPalette
		// = GetPalette() folded with Flash/FlashAmount, exactly as the paletted
		// scanout path computes it. (Gamma is applied by neither GL path.)
		PalEntry pal[256];
		if(screen != NULL)
			screen->GetFlashedPalette(pal);
		else
			memcpy(pal, GPalette.BaseColors, sizeof(pal));
		unsigned char rgb[256 * 3];
		for(int i = 0; i < 256; ++i)
		{
			rgb[i*3+0] = pal[i].r;
			rgb[i*3+1] = pal[i].g;
			rgb[i*3+2] = pal[i].b;
		}
		glActiveTexture(GL_TEXTURE1);
		glBindTexture(GL_TEXTURE_2D, gLive.paletteTex);
		glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
		glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 256, 1, GL_RGB,
			GL_UNSIGNED_BYTE, rgb);
	}

	// Render the GL 3D world into the persistent world FBO for this frame.
	void RenderLiveWorld()
	{
		EnsureLiveResources();
		if(!gLive.inited)
			return;
		if(gLive.lastMap != (const void *)map)
		{
			ClearLiveCaches();
			gLive.lastMap = (const void *)map;
		}

		int fw = SCREENWIDTH, fh = SCREENHEIGHT;
		int vx = viewscreenx, vy = viewscreeny, vw = viewwidth, vh = viewheight;
		if(vw <= 0 || vh <= 0 || vx + vw > fw || vy + vh > fh)
		{
			vx = 0; vy = 0; vw = fw; vh = fh;
		}
		gLive.vx = vx; gLive.vy = vy; gLive.vw = vw; gLive.vh = vh;
		gLive.fw = fw; gLive.fh = fh;
		EnsureWorldFbo(vw, vh);

		WorldGL wr;
		wr.prog = gLive.prog;
		wr.paletteTex = gLive.paletteTex;
		wr.colormapTex = gLive.colormapTex;
		wr.c7RampFloorTex = gLive.c7RampFloorTex;
		wr.texCache = &gLive.texCache;
		wr.opacCache = &gLive.opacCache;
		wr.cacheMesh = &gLive.staticCacheMesh;
		wr.cacheGL = &gLive.staticCacheGL;
		wr.cacheValid = &gLive.staticCacheValid;
		if(!BuildWorldGL(wr, vw, vh))
		{
			DestroyWorldGL(wr);
			gLive.haveWorld = false;
			return;
		}

		// The world is resolved to RGB inside the FBO here, before the present
		// path runs, so refresh the palette texture with this frame's effective
		// (flashed / C7-mode) palette now -- otherwise the world would bake with
		// the previous frame's palette and full-screen effects would miss it.
		UpdateLivePalette();

		const bool msaa = gLive.worldSamples > 0 && gLive.msaaFbo != 0;
		glBindFramebuffer(GL_FRAMEBUFFER, msaa ? gLive.msaaFbo : gLive.worldFbo);
		glViewport(0, 0, vw, vh);
		glEnable(GL_DEPTH_TEST);
		glDepthFunc(GL_LESS);
		glDisable(GL_CULL_FACE);
		if(msaa)
		{
			glEnable(GL_MULTISAMPLE);
			// The silhouettes of sprites and masked walls come from a shader
			// `discard`, which multisampling cannot smooth on its own -- a
			// discarded fragment kills every sample. The filtered path writes
			// the fraction of opaque taps to alpha, and alpha-to-coverage turns
			// that into a sample mask, so the cutout gets antialiased too.
			//
			// Coverage rather than blending on purpose: blending would make the
			// pass order-dependent and break the state-sorted draw batching.
			if(vid_glfilter > 0)
				glEnable(GL_SAMPLE_ALPHA_TO_COVERAGE);
		}
		{
			GLProf::Scope s(GLProf::B_Draw);
			DrawWorldColourPass(wr);
		}
		if(msaa)
		{
			glDisable(GL_SAMPLE_ALPHA_TO_COVERAGE);
			// Resolve the multisampled colour into the texture the compositor
			// samples. Depth is not needed downstream.
			glBindFramebuffer(GL_READ_FRAMEBUFFER, gLive.msaaFbo);
			glBindFramebuffer(GL_DRAW_FRAMEBUFFER, gLive.worldFbo);
			glBlitFramebuffer(0, 0, vw, vh, 0, 0, vw, vh,
				GL_COLOR_BUFFER_BIT, GL_NEAREST);
			glBindFramebuffer(GL_FRAMEBUFFER, gLive.worldFbo);
			glDisable(GL_MULTISAMPLE);
		}
		DestroyWorldGL(wr);	// frees per-frame VBOs; borrowed resources kept
		gLive.haveWorld = true;
		GLCheckErrors("RenderLiveWorld");
	}
}

void R_GLProfileEndFrame()
{
	GLProf::EndFrame();
}

bool R_GLLiveWantPresent()
{
	FString r = vid_renderer;
	r.ToLower();
	return r.Compare("opengl") == 0 || r.Compare("gl") == 0;
}

static void FreeLiveResources(bool audit);

void R_GLLiveSetContextActive(bool active)
{
	// SDLFB reports the window's GL context going away. Every live resource --
	// shaders, palette/colormap/LUT textures, the world FBO, the per-map index
	// texture caches -- belongs to that context, and the object names are
	// meaningless in its replacement, so they must not survive it.
	//
	// This is not a rare path: it fires on any video mode change, and toggling
	// fullscreen is one, because VL_SetFullscreen swaps screenWidth/Height to the
	// fullscreen or windowed pair. That almost always changes the resolution, so
	// V_SetResolution takes the recreate branch (delete the SDLFB, which deletes
	// the context, then build a new one) rather than reusing the window. Without
	// this teardown the compositor kept drawing with dead handles and presented a
	// black window until the game was restarted.
	//
	// The dying context is still current here -- SDLFB calls this before
	// SDL_GL_DeleteContext -- so this is a real free, not just a handle drop.
	if(!active && gLiveContextActive)
		FreeLiveResources(/*audit=*/false);
	gLiveContextActive = active;
}

bool R_GLLiveContextActive()
{
	return gLiveContextActive;
}

void R_GLLiveArmCapture(const char *path, int frame)
{
	gLive.capPath = path ? path : "";
	(void)frame;	// the harness writes the latest present at its chosen frame
}

void R_GLLiveWriteCapture()
{
	if(gLive.capPath.IsEmpty() || gLive.lastRGB.Size() == 0)
		return;
	if(WritePPM(gLive.capPath.GetChars(), &gLive.lastRGB[0],
		gLive.lastW, gLive.lastH))
		Printf("GL live: wrote presented frame -> %s (%dx%d).\n",
			gLive.capPath.GetChars(), gLive.lastW, gLive.lastH);
}

// Reduced software frame for the GL live path: run the raycaster only for its
// visibility side-effect (and viewz/viewshift), clear the 3D view to the
// compositor key, draw the weapon over it, then render the GL world. The
// caller (OpenGLRenderer::RenderScene) is wrapped in interpolation Apply/Restore
// exactly like the software path.
void R_GLLiveRenderScene()
{
	if(map == NULL)
		return;
	if(players[ConsolePlayer].camera == NULL)
		players[ConsolePlayer].camera = players[ConsolePlayer].mo;

	map->ClearVisibility();

	// Any post-world 2D coverage belongs to the frame that recorded it; the new
	// frame re-records it (R_GLLiveDrawViewOverlay) after this render completes.
	gLive.haveOverlayCover = false;

	byte *surf = VL_LockSurface();
	if(surf == NULL)
		return;
	vbuf = surf + screenofs;
	vbufPitch = SCREENPITCH;

	CalcViewVariables();
	{
		GLProf::Scope s(GLProf::B_Visibility);
		// Visibility, masked-wall hits and viewz; the wall pixels this would
		// otherwise draw are cleared by the memset immediately below.
		WallRefreshVisibilityOnly();
	}

	// Clear the 3D view region to the compositor key so only 2D drawn over it
	// (the weapon now; banners/messages later in PlayFrame) stays opaque.
	const byte key = GPalette.Remap[0];
	for(int y = 0; y < viewheight; ++y)
		memset(vbuf + y * vbufPitch, key, viewwidth);

	{
		GLProf::Scope s(GLProf::B_Weapon);
		DrawPlayerWeapon();
	}

	// Build a robust weapon coverage mask. The compositor keys the view region
	// on == key (Remap[0]) to decide which texels reveal the GL world, but the
	// weapon is a masked, destination-independent blit (r_sprites.cpp:
	// "if(src != 0) *dest = shade(src)") whose shaded texels can legitimately
	// equal the key -- those would be misread as transparent and punch holes in
	// the weapon. Redraw the weapon over a scratch buffer cleared to a different
	// sentinel: because the blit ignores the destination, a covered texel writes
	// the same value over both clears while an uncovered texel keeps its
	// (differing) background. Equal => the weapon drew here, so it is opaque
	// regardless of colour.
	//
	// Rebuilt only when the silhouette can have moved. Coverage is the sprite's
	// shape, so it depends on which frame is drawn and where -- not on shading
	// or palette. Every input to that is a function of the simulation tic:
	// BobWeapon derives its offsets from gamestate.TimeCount, and the Corridor 7
	// walk-cycle pose advances once per TimeCount too. Frames run several times
	// per tic, and each one was redrawing the weapon a second time and comparing
	// a quarter of a million texels to re-derive an identical mask; that was 59%
	// of the frame once the raycaster stopped dominating it.
	{
		// Same bucket as the draw above: this is the weapon's second draw plus
		// the per-texel comparison, which is the other half of its cost.
		GLProf::Scope s(GLProf::B_Weapon);
		const byte alt = (byte)(key ^ 0xFF);
		const int vw = viewwidth, vh = viewheight;

		struct CoverKey
		{
			const void *frame;
			const void *weapon;
			int32_t time;
			fixed sx, sy;
			int vw, vh, vx, vy;
		};
		static CoverKey lastKey = { NULL, NULL, -1, 0, 0, 0, 0, 0, 0 };
		CoverKey nowKey;
		nowKey.frame = (const void *)players[ConsolePlayer].psprite[0].frame;
		nowKey.weapon = (const void *)players[ConsolePlayer].ReadyWeapon;
		nowKey.time = (int32_t)gamestate.TimeCount;
		nowKey.sx = players[ConsolePlayer].psprite[0].sx;
		nowKey.sy = players[ConsolePlayer].psprite[0].sy;
		nowKey.vw = vw; nowKey.vh = vh;
		nowKey.vx = viewscreenx; nowKey.vy = viewscreeny;

		// Only the mask work is skipped -- never the real weapon draw above, and
		// never anything after this block, which still has to unlock the surface
		// and render the world.
		const bool reusable = gLive.haveWeaponCover &&
			memcmp(&lastKey, &nowKey, sizeof(CoverKey)) == 0;
		if(!reusable)
		{
			lastKey = nowKey;

			TArray<unsigned char> scratch((unsigned)(SCREENPITCH * vh));
			scratch.Resize((unsigned)(SCREENPITCH * vh));
			for(int y = 0; y < vh; ++y)
				memset(&scratch[y * SCREENPITCH], alt, vw);

			byte *saveVbuf = vbuf;
			vbuf = &scratch[0];	// pitch unchanged; scratch[0] is the view origin
			DrawPlayerWeapon();
			vbuf = saveVbuf;

			const byte *real = surf + screenofs;
			gLive.weaponCover.Resize((unsigned)(vw * vh));
			for(int r = 0; r < vh; ++r)
				for(int c = 0; c < vw; ++c)
					gLive.weaponCover[r * vw + c] =
						(real[r * SCREENPITCH + c] == scratch[r * SCREENPITCH + c])
							? 1 : 0;
			gLive.wcx = viewscreenx; gLive.wcy = viewscreeny;
			gLive.wcw = vw; gLive.wch = vh;
			gLive.haveWeaponCover = true;
		}
	}

	// Mark the player's own cell visible for the automap (as R_RenderView does).
	map->GetSpot(players[ConsolePlayer].mo->tilex,
		players[ConsolePlayer].mo->tiley, 0)->amFlags |= AM_Visible;

	VL_UnlockSurface();
	vbuf = NULL;

	if(player_t *player = players[ConsolePlayer].camera->player)
		if(player->ScreenFader)
			player->ScreenFader->Update();

	RenderLiveWorld();
}

// Draw 2D that lands over the 3D view (Corridor 7's top-message / power-chamber
// overlay), recording which texels it painted.
//
// The compositor decides what shows through the view region by keying on the
// palette's black index (the value R_GLLiveRenderScene clears the view to), and
// that test cannot see 2D drawn *in* that colour. C7's top message paints a
// one-pixel black drop shadow under its yellow letters exactly like the DOS
// notification renderer, so those texels read as "nothing drawn here" and the
// world showed through them -- the shadow vanished in GL while surviving in
// software.
//
// The fix is the same destination-independence test the weapon coverage mask
// uses: run the draw twice over two different backgrounds and keep the texels
// that come out identical. A masked/stencil blit ignores what it covers, so a
// texel is "painted" iff it is background-independent, whatever colour it is.
// `draw` is therefore called more than once and must be pure (a translucent
// draw would fail the test and stay transparent, as it does today).
void R_GLLiveDrawViewOverlay(void (*draw)())
{
	if(draw == NULL)
		return;

	const int vx = gLive.wcx, vy = gLive.wcy, vw = gLive.wcw, vh = gLive.wch;
	if(!gLive.haveWeaponCover || !gLive.haveWorld || vw <= 0 || vh <= 0)
	{
		draw();	// no world behind the 2D this frame: nothing to key against
		return;
	}

	// Hold the canvas lock across the whole sequence: the inner draws nest their
	// own Lock/Unlock, and keeping LockCount above one stops the final Unlock
	// from triggering a present mid-measurement.
	byte *surf = VL_LockSurface();
	if(surf == NULL)
	{
		draw();
		return;
	}
	const int pitch = screen->GetPitch();
	const byte bgA = GPalette.Remap[0];
	const byte bgB = (byte)(bgA ^ 0xFF);
	const unsigned n = (unsigned)(vw * vh);

	TArray<unsigned char> saved(n), passA(n), passB(n);
	saved.Resize(n); passA.Resize(n); passB.Resize(n);
	for(int r = 0; r < vh; ++r)
		memcpy(&saved[r * vw], surf + (vy + r) * pitch + vx, (size_t)vw);

	for(int r = 0; r < vh; ++r)
		memset(surf + (vy + r) * pitch + vx, bgA, (size_t)vw);
	draw();
	for(int r = 0; r < vh; ++r)
		memcpy(&passA[r * vw], surf + (vy + r) * pitch + vx, (size_t)vw);

	for(int r = 0; r < vh; ++r)
		memset(surf + (vy + r) * pitch + vx, bgB, (size_t)vw);
	draw();
	for(int r = 0; r < vh; ++r)
		memcpy(&passB[r * vw], surf + (vy + r) * pitch + vx, (size_t)vw);

	// Accumulate: PlayFrame registers more than one overlay per frame (the top
	// message, then PAUSED after the automap), so coverage ORs together and is
	// reset only when the next scene render starts.
	const bool accumulate = gLive.haveOverlayCover && gLive.overlayCover.Size() == n;
	if(!accumulate)
	{
		gLive.overlayCover.Resize(n);
		memset(&gLive.overlayCover[0], 0, n);
	}

	// Restore the real frame and replay only the painted texels over it, so the
	// canvas ends up exactly as a single draw would have left it.
	for(int r = 0; r < vh; ++r)
	{
		byte *dst = surf + (vy + r) * pitch + vx;
		for(int c = 0; c < vw; ++c)
		{
			const unsigned i = (unsigned)(r * vw + c);
			const bool painted = passA[i] == passB[i];
			if(painted)
				gLive.overlayCover[i] = 1;
			dst[c] = painted ? passA[i] : saved[i];
		}
	}
	gLive.haveOverlayCover = true;

	VL_UnlockSurface();
}

void R_GLLivePresent(const unsigned char *mem, int pitch, int fw, int fh,
	int drawableW, int drawableH)
{
	if(drawableW <= 0) drawableW = fw;
	if(drawableH <= 0) drawableH = fh;

	// Closes when this function returns -- every exit path goes through
	// R_GLXBRZEnd, so there is no early return that would escape it.
	GLProf::Scope presentScope(GLProf::B_Present);

	// Image scaling, when it is on: compositing is redirected into an offscreen
	// buffer the size of the 8-bit frame, and R_GLXBRZEnd filters that onto the
	// window. Compositing 1:1 rather than straight to a larger window is not just
	// plumbing -- the filter has to see the frame at the resolution its pixels
	// were reasoned about, or it would be reading the driver's magnification of
	// them. Every exit below goes through R_GLXBRZEnd, which restores the default
	// framebuffer whether or not it scaled anything, so nothing else here has to
	// know which of the two is in force.
	if(R_GLXBRZBegin(fw, fh, drawableW, drawableH) == 0)
	{
		glBindFramebuffer(GL_FRAMEBUFFER, 0);
		glViewport(0, 0, drawableW, drawableH);
	}
	glDisable(GL_DEPTH_TEST);
	glDisable(GL_POLYGON_OFFSET_FILL);
	glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
	glClear(GL_COLOR_BUFFER_BIT);

	// Initialize the compositor resources (shaders + palette/colormap) on the
	// first present, independent of the world path. The 2D-only frames shown
	// before any level renders -- splash, credits, title, and menu screens --
	// must still composite through the palette; otherwise they present black
	// until the first 3D frame lazily initializes these resources.
	EnsureLiveResources();
	if(!gLive.inited || !gLive.screenProg || mem == NULL)
	{
		// Resources failed to build, or nothing to composite: black frame.
		R_GLXBRZEnd(drawableW, drawableH);
		return;
	}

	UpdateLivePalette();

	// Overlay: opaque 2D everywhere, except the view region's key texels when a
	// world was rendered this frame (those reveal the GL world behind them).
	const int W = fw, H = fh;
	TArray<unsigned char> idx((unsigned)(W * H)), opac((unsigned)(W * H));
	idx.Resize((unsigned)(W * H));
	opac.Resize((unsigned)(W * H));
	for(int y = 0; y < H; ++y)
		for(int x = 0; x < W; ++x)
		{
			idx[y * W + x] = mem[y * pitch + x];
			opac[y * W + x] = 255;
		}
	if(gLive.haveWorld)
	{
		const unsigned char key = GPalette.Remap[0];
		for(int r = 0; r < gLive.vh; ++r)
			for(int c = 0; c < gLive.vw; ++c)
			{
				const int fx = gLive.vx + c, fy = gLive.vy + r;
				// The weapon and the post-world 2D overlay are opaque wherever
				// their coverage masks say they drew, even if that texel's index
				// equals the key (a shaded weapon column, C7's black text drop
				// shadow); only then fall back to the key test, so world shows
				// through unpainted view texels while any other 2D over the view
				// stays opaque.
				const bool inCover = fx >= gLive.wcx && fx < gLive.wcx + gLive.wcw &&
					fy >= gLive.wcy && fy < gLive.wcy + gLive.wch;
				const unsigned ci = inCover
					? (unsigned)((fy - gLive.wcy) * gLive.wcw + (fx - gLive.wcx)) : 0;
				bool painted = false;
				if(inCover && gLive.haveWeaponCover)
					painted = gLive.weaponCover[ci] != 0;
				if(inCover && !painted && gLive.haveOverlayCover)
					painted = gLive.overlayCover[ci] != 0;
				if(!painted && mem[fy * pitch + fx] == key)
					opac[fy * W + fx] = 0;
			}
	}
	GLuint oIdx = CreateR8UITexture(&idx[0], W, H);
	gLedger.tex++;
	GLuint oOpac = CreateR8UITexture(&opac[0], W, H);
	gLedger.tex++;

	glUseProgram(gLive.screenProg);
	const GLint uMode = glGetUniformLocation(gLive.screenProg, "uMode");
	glActiveTexture(GL_TEXTURE1);
	glBindTexture(GL_TEXTURE_2D, gLive.paletteTex);
	glUniform1i(glGetUniformLocation(gLive.screenProg, "uPaletteTex"), 1);
	glActiveTexture(GL_TEXTURE4);
	glBindTexture(GL_TEXTURE_2D, oIdx);
	glUniform1i(glGetUniformLocation(gLive.screenProg, "uOverlayIdx"), 4);
	glActiveTexture(GL_TEXTURE5);
	glBindTexture(GL_TEXTURE_2D, oOpac);
	glUniform1i(glGetUniformLocation(gLive.screenProg, "uOverlayOpac"), 5);

	if(gLive.haveWorld && gLive.worldTex)
	{
		glActiveTexture(GL_TEXTURE0);
		glBindTexture(GL_TEXTURE_2D, gLive.worldTex);
		glUniform1i(glGetUniformLocation(gLive.screenProg, "uWorldTex"), 0);
		const float nx0 = 2.0f * (float)gLive.vx / (float)W - 1.0f;
		const float nx1 = 2.0f * (float)(gLive.vx + gLive.vw) / (float)W - 1.0f;
		const float nyTop = 1.0f - 2.0f * (float)gLive.vy / (float)H;
		const float nyBot = 1.0f - 2.0f * (float)(gLive.vy + gLive.vh) / (float)H;
		glUniform1i(uMode, 0);
		DrawScreenQuad(nx0, nyBot, nx1, nyTop, 0.0f, 0.0f, 1.0f, 1.0f);
	}
	glUniform1i(uMode, 1);
	DrawScreenQuad(-1.0f, -1.0f, 1.0f, 1.0f, 0.0f, 1.0f, 1.0f, 0.0f);

	glDeleteTextures(1, &oIdx);
	gLedger.tex--;
	glDeleteTextures(1, &oOpac);
	gLedger.tex--;

	R_GLXBRZEnd(drawableW, drawableH);
	R_GLXBRZWriteParity(mem, pitch, fw, fh, gLive.haveWorld);
	GLCheckErrors("R_GLLivePresent");

	// Headless verification: keep the just-composited frame (still in the default
	// framebuffer, before the caller swaps) so the capture harness can write the
	// exact gameplay frame it asks for.
	if(!gLive.capPath.IsEmpty())
	{
		const size_t n = (size_t)drawableW * drawableH * 3;
		gLive.lastRGB.Resize((unsigned)n);
		TArray<unsigned char> tmp((unsigned)n);
		tmp.Resize((unsigned)n);
		glPixelStorei(GL_PACK_ALIGNMENT, 1);
		glReadPixels(0, 0, drawableW, drawableH, GL_RGB, GL_UNSIGNED_BYTE, &tmp[0]);
		for(int y = 0; y < drawableH; ++y)
			memcpy(&gLive.lastRGB[(size_t)y * drawableW * 3],
				&tmp[(size_t)(drawableH - 1 - y) * drawableW * 3],
				(size_t)drawableW * 3);
		gLive.lastW = drawableW;
		gLive.lastH = drawableH;
	}

	gLive.haveWorld = false;	// consumed; a pure-2D frame follows unless re-rendered
}

// Release every live GL object. The owning context must be current. `audit`
// reports the leak ledger; that is the final-shutdown check, so a video mode
// change (which tears down and rebuilds) passes false and stays quiet.
static void FreeLiveResources(bool audit)
{
	// Cache textures (created by the shared mesh uploader, freed here) are audited
	// separately from the ledger; record their count before ClearLiveCaches frees.
	const long cacheTex = (long)gLive.texCache.CountUsed() +
		(long)gLive.opacCache.CountUsed();
	ClearLiveCaches();
	R_GLXBRZShutdown();
	if(gLive.worldTex)    { glDeleteTextures(1, &gLive.worldTex);       gLedger.tex--; }
	if(gLive.worldDepth)  { glDeleteRenderbuffers(1, &gLive.worldDepth); gLedger.rbo--; }
	if(gLive.worldFbo)    { glDeleteFramebuffers(1, &gLive.worldFbo);    gLedger.fbo--; }
	if(gLive.msaaColor)   { glDeleteRenderbuffers(1, &gLive.msaaColor);  gLedger.rbo--; }
	if(gLive.msaaDepth)   { glDeleteRenderbuffers(1, &gLive.msaaDepth);  gLedger.rbo--; }
	if(gLive.msaaFbo)     { glDeleteFramebuffers(1, &gLive.msaaFbo);     gLedger.fbo--; }
	if(gLive.screenProg)  { glDeleteProgram(gLive.screenProg);          gLedger.prog--; }
	if(gLive.prog)        { glDeleteProgram(gLive.prog);                gLedger.prog--; }
	if(gLive.paletteTex)  { glDeleteTextures(1, &gLive.paletteTex);      gLedger.tex--; }
	if(gLive.colormapTex) { glDeleteTextures(1, &gLive.colormapTex);     gLedger.tex--; }
	if(gLive.c7RampFloorTex) { glDeleteTextures(1, &gLive.c7RampFloorTex); gLedger.tex--; }

	// Resource-leak check: after teardown the live ledger must balance to zero and
	// the texture caches must be empty. A nonzero balance means a live GL object
	// was allocated without a matching free somewhere in the frame loop.
	if(audit)
	{
		const long leaked = gLedger.tex + gLedger.fbo + gLedger.rbo + gLedger.prog;
		if(leaked == 0 && gLive.texCache.CountUsed() == 0 &&
			gLive.opacCache.CountUsed() == 0)
			Printf("GL live: 0 leaked GL objects (balanced; %ld cache textures freed).\n",
				cacheTex);
		else
			Printf("GL live: WARNING leaked GL objects "
				"(tex=%ld fbo=%ld rbo=%ld prog=%ld, %ld cache textures at exit).\n",
				gLedger.tex, gLedger.fbo, gLedger.rbo, gLedger.prog,
				(long)gLive.texCache.CountUsed() + (long)gLive.opacCache.CountUsed());
	}

	// Everything is rebuilt lazily (EnsureLiveResources / EnsureWorldFbo / the
	// mesh caches, which key off lastMap). Carry the capture arming across: it is
	// set once at startup and a mode change must not disarm the harness.
	const FString capPath = gLive.capPath;
	gLive = GLLive();
	gLive.capPath = capPath;
	gLedger = GLLedger();
	gGLDebugInstalled = false;
}

void R_GLLiveShutdown()
{
	FreeLiveResources(/*audit=*/true);
}

void R_GLLiveInvalidateTextures()
{
	// Deferred to the next frame rather than done here, because the caller is
	// menu code and the GL context is only reliably current inside the render
	// path. Forgetting the map is the same signal a level change gives, and it
	// runs ClearLiveCaches() at the top of the next RenderLiveWorld().
	gLive.lastMap = NULL;
}
