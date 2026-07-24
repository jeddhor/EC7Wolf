// ===========================================================================
//
// r_glworld.cpp - GL static-world render + offscreen capture.
//
// Phase 5 stood up the geometry/camera with a debug shader. Phase 6 replaces
// the debug colours with real fidelity: each surface's FTexture is uploaded as
// an 8-bit *index* texture, and the shader resolves colour exactly the way the
// software renderer does -- index -> colormap[shadeRow] -> palette -- with the
// shade row derived from ECWolf's own distance/light math, plus the Corridor 7
// colour-cycle and full-bright rules. Palette effects (visor/electric/damage)
// live entirely in the 256-entry palette texture, never in world pixels.
//
// ===========================================================================

#include <stdio.h>
#include <math.h>

#include <epoxy/gl.h>

#include "render/opengl/r_glworld.h"
#include "render/opengl/r_gldevice.h"
#include "render/opengl/r_glshader.h"
#include "render/r_worldbuilder.h"
#include "render/r_dynamicwalls.h"
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
#include "tarray.h"
#include "textures/textures.h"
#include "v_palette.h"
#include "r_data/colormaps.h"

// Distance-shade inputs owned by the software renderer.
extern int r_extralight;
extern fixed viewz;
extern int viewshift;

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
		"uniform usampler2D uOpacityTex;\n"  // per-surface WxH, R8UI (0 = transparent)
		"uniform sampler2D  uPaletteTex;\n"  // 256x1 RGB8
		"uniform usampler2D uColormapTex;\n" // 256xNUMCOLORMAPS R8UI
		"uniform int   uHasOpacity;\n"
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
		"uniform int   uDebug;\n"           // 0 normal, 1 shade-row visualization
		"const float FRACUNIT = 65536.0;\n"
		"const float MINZ = 8192.0;\n"      // 2048*4
		"float bayer4(ivec2 p){\n"
		"    int m[16] = int[16](0,8,2,10, 12,4,14,6, 3,11,1,9, 15,7,13,5);\n"
		"    int i = (p.y & 3)*4 + (p.x & 3);\n"
		"    return (float(m[i]) + 0.5) / 16.0;\n"
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
		"    ivec2 texel = ivec2(floor(uv * vec2(isz)));\n"
		"    texel = ((texel % isz) + isz) % isz;\n"   // tile (repeat) within one cell
		"    // Explicit per-texel opacity (C7 grate/fence walls); never write\n"
		"    // transparent texels, matching the software postopacity test.\n"
		"    if(uHasOpacity == 1 && texelFetch(uOpacityTex, texel, 0).r == 0u)\n"
		"        discard;\n"
		"    int idx = int(texelFetch(uIndexTex, texel, 0).r);\n"
		"    // Colour-cycle + full-bright are wall-only in the software renderer\n"
		"    // (ShadeWallColor); planes draw c7PlaneShades[c] with neither.\n"
		"    bool isWall = uSurfKind == 2;\n"
		"    if(uCorridor7 == 1 && isWall && idx >= 208 && idx <= 239){\n"
		"        int base = idx & ~7;\n"
		"        idx = base + ((idx - base - uCyclePhase) & 7);\n"
		"    }\n"
		"    // Shade row selection mirrors the software renderer per surface type.\n"
		"    int shadeRow;\n"
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
		"        int firstShade = max(0, 5 - uExtraLight / 16);\n"
		"        int litBand = band > uExtraLight / 8 ? band - uExtraLight / 8 : 0;\n"
		"        shadeRow = firstShade + litBand;\n"
		"        int virtualX = int(min(319.0, gl_FragCoord.x * 320.0 / float(uViewW)));\n"
		"        int a = (virtualX >> 2) & 1;\n"
		"        int b = (ver % 3 == 1) ? 1 : 0;\n"
		"        int c = band & 1;\n"
		"        if((a ^ b ^ c) == 0) shadeRow += 1;\n"   // four-pixel alternation dither
		"    } else {\n"
		"        // Generic (non-C7) plane distance formula.\n"
		"        float rowFromHorizon = abs(gl_FragCoord.y - uHorizon);\n"
		"        float tz = (uDepthVis * FRACUNIT / uPlaneHeight) * rowFromHorizon;\n"
		"        float visv = min(uMaxLightVis, tz);\n"
		"        float palf = (uShade - visv) / FRACUNIT;\n"
		"        shadeRow = int(floor(palf));\n"
		"    }\n"
		"    // Corridor 7 full-bright reserved indices ignore distance shading\n"
		"    // (walls only, matching ShadeWallColor).\n"
		"    bool fullbright = uCorridor7 == 1 && isWall &&\n"
		"        (idx == uRemap15 || idx == uRemap254 ||\n"
		"        (idx >= uRemap208 && idx <= uRemap239));\n"
		"    if(fullbright) shadeRow = 0;\n"
		"    shadeRow = clamp(shadeRow, 0, uNumColormaps - 1);\n"
		"    if(uDebug == 1){\n"
		"        float g = float(shadeRow) / float(uNumColormaps - 1);\n"
		"        fragColor = vec4(g, g, g, 1.0); return;\n"
		"    }\n"
		"    int shaded = int(texelFetch(uColormapTex, ivec2(idx, shadeRow), 0).r);\n"
		"    vec3 rgb = texelFetch(uPaletteTex, ivec2(shaded, 0), 0).rgb;\n"
		"    fragColor = vec4(rgb, 1.0);\n"
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
		unsigned char rgb[256 * 3];
		for(int i = 0; i < 256; ++i)
		{
			rgb[i*3+0] = GPalette.BaseColors[i].r;
			rgb[i*3+1] = GPalette.BaseColors[i].g;
			rgb[i*3+2] = GPalette.BaseColors[i].b;
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

	// Render the world once with the given debug mode into the bound FBO and
	// read it back to rgb. Assumes program/uniforms/textures already set up
	// except uDebug, which is (re)set here.
	struct SurfaceUniforms
	{
		GLint uIndexTex;
		GLint uOpacityTex;
		GLint uHasOpacity;
		GLint uSurfKind;
		GLint uPlaneHeight;
		GLint uSlide;
		GLint uSlideStyle;
		GLint uSlideAmount;
		float floorPlaneH;
		float ceilPlaneH;
	};

	// One mesh's GPU resources: interleaved VBO + a per-surface index/opacity
	// texture list (parallel to mesh.surfaces).
	struct MeshGL
	{
		GLuint vao, vbo;
		TArray<GLuint> tex;
		TArray<GLuint> opac;
		MeshGL() : vao(0), vbo(0) {}
	};

	// Draw one mesh with the current program/uniforms. The framebuffer clear and
	// uDebug are set by the caller so several meshes share one pass.
	void RenderMesh(const WorldMesh &mesh, const MeshGL &gl,
		const SurfaceUniforms &su)
	{
		if(mesh.vertices.Size() == 0)
			return;
		glBindVertexArray(gl.vao);

		GLuint boundTex = 0xffffffffu;
		GLuint boundOpac = 0xffffffffu;
		int boundKind = -100;
		int boundSlideStyle = -100;
		unsigned int boundSlideAmt = 0xffffffffu;
		for(unsigned int i = 0; i < mesh.surfaces.Size(); ++i)
		{
			const WorldSurface &surf = mesh.surfaces[i];
			const GLuint tex = gl.tex[i];
			if(tex == 0)
				continue;
			if(tex != boundTex)
			{
				glActiveTexture(GL_TEXTURE0);
				glBindTexture(GL_TEXTURE_2D, tex);
				glUniform1i(su.uIndexTex, 0);
				boundTex = tex;
			}
			const GLuint opac = gl.opac[i];
			if(opac != boundOpac)
			{
				glUniform1i(su.uHasOpacity, opac ? 1 : 0);
				if(opac)
				{
					glActiveTexture(GL_TEXTURE3);
					glBindTexture(GL_TEXTURE_2D, opac);
					glUniform1i(su.uOpacityTex, 3);
				}
				boundOpac = opac;
			}
			// A door leaf is shaded as a wall (perpendicular distance, C7 cycle /
			// full-bright) but additionally runs the slide in the shader.
			const bool isDoor = surf.kind == WSURF_DoorLeaf;
			const int shaderKind = isDoor ? WSURF_Wall : surf.kind;
			if(shaderKind != boundKind)
			{
				glUniform1i(su.uSurfKind, shaderKind);
				if(shaderKind == WSURF_Floor)
					glUniform1f(su.uPlaneHeight, su.floorPlaneH);
				else if(shaderKind == WSURF_Ceiling)
					glUniform1f(su.uPlaneHeight, su.ceilPlaneH);
				boundKind = shaderKind;
			}
			glUniform1i(su.uSlide, isDoor ? 1 : 0);
			if(isDoor && (surf.slideStyle != boundSlideStyle ||
				surf.slideAmount != boundSlideAmt))
			{
				glUniform1i(su.uSlideStyle, surf.slideStyle);
				glUniform1f(su.uSlideAmount, (float)surf.slideAmount);
				boundSlideStyle = surf.slideStyle;
				boundSlideAmt = surf.slideAmount;
			}
			glDrawArrays(GL_TRIANGLES, (GLint)surf.firstVertex,
				(GLsizei)surf.vertexCount);
		}
	}

	// Upload a mesh's VBO + per-surface index/opacity textures. Textures are
	// cached per FTextureID (shared across the static and dynamic meshes) so
	// shared art uploads a single time.
	void UploadMesh(const WorldMesh &mesh, TMap<int, GLuint> &texCache,
		TMap<int, GLuint> &opacCache, MeshGL &out,
		unsigned int *uniqueOut, unsigned int *maskedOut)
	{
		glGenVertexArrays(1, &out.vao);
		glBindVertexArray(out.vao);
		glGenBuffers(1, &out.vbo);
		glBindBuffer(GL_ARRAY_BUFFER, out.vbo);
		if(mesh.vertices.Size() > 0)
			glBufferData(GL_ARRAY_BUFFER,
				(GLsizeiptr)(mesh.vertices.Size() * sizeof(WorldVertex)),
				&mesh.vertices[0], GL_STATIC_DRAW);
		const GLsizei stride = sizeof(WorldVertex);
		glEnableVertexAttribArray(0);
		glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, (void*)0);
		glEnableVertexAttribArray(1);
		glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, (void*)(3*sizeof(float)));
		glEnableVertexAttribArray(2);
		glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, stride, (void*)(5*sizeof(float)));
		glEnableVertexAttribArray(3);
		glVertexAttribPointer(3, 1, GL_FLOAT, GL_FALSE, stride, (void*)(6*sizeof(float)));

		out.tex.Resize(mesh.surfaces.Size());
		out.opac.Resize(mesh.surfaces.Size());
		for(unsigned int i = 0; i < mesh.surfaces.Size(); ++i)
		{
			const FTextureID id = mesh.surfaces[i].texture;
			if(!id.isValid())
			{
				out.tex[i] = 0;
				out.opac[i] = 0;
				continue;
			}
			const int key = id.GetIndex();
			GLuint *cached = texCache.CheckKey(key);
			if(cached)
			{
				out.tex[i] = *cached;
				out.opac[i] = *opacCache.CheckKey(key);
				continue;
			}
			FTexture *ftex = TexMan(id);
			GLuint idxTex = CreateIndexTextureFor(ftex);
			GLuint opacTex = CreateOpacityTextureFor(ftex);
			texCache[key] = idxTex;
			opacCache[key] = opacTex;
			out.tex[i] = idxTex;
			out.opac[i] = opacTex;
			if(idxTex && uniqueOut)
				++*uniqueOut;
			if(opacTex && maskedOut)
				++*maskedOut;
		}
	}

	void DestroyMesh(MeshGL &gl)
	{
		if(gl.vbo) glDeleteBuffers(1, &gl.vbo);
		if(gl.vao) glDeleteVertexArrays(1, &gl.vao);
		gl.vbo = gl.vao = 0;
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

	// Build the static world mesh plus the dynamic (door/pushwall) mesh. The
	// dynamic mesh is interpolated at the current sub-tic alpha so doors and
	// pushwalls render at their exact fractional positions.
	WorldMesh mesh;
	WorldBuilder::BuildStatic(map, mesh);
	WorldMesh dynMesh;
	const float alpha = R_GetInterpolationAlpha();
	WorldBuilder::BuildDynamic(map, dynMesh, alpha);
	Printf("GL world: static walls=%u floors=%u ceilings=%u verts=%u; "
		"dynamic faces=%u verts=%u (alpha=%.2f)\n",
		mesh.wallFaces, mesh.floorTiles, mesh.ceilingTiles,
		(unsigned)mesh.vertices.Size(), dynMesh.wallFaces,
		(unsigned)dynMesh.vertices.Size(), alpha);
	if(mesh.vertices.Size() == 0 && dynMesh.vertices.Size() == 0)
		return false;

	GLDevice dev;
	if(!dev.Create(W, H, false, /*hidden=*/true, "EC7Wolf GL world"))
		return false;

	GLuint prog = GLShader::Build(kVert, kFrag, "world-indexed");
	if(!prog) { dev.Destroy(); return false; }

	// --- palette + colormap (shared) and per-surface index textures ---
	GLuint paletteTex = CreatePaletteTexture();
	int colormapRows = 0;
	GLuint colormapTex = CreateColormapTexture(colormapRows);

	// Index + opacity textures cache per FTexture, shared across both meshes so
	// shared art uploads once.
	TMap<int, GLuint> texCache;
	TMap<int, GLuint> opacCache;
	unsigned int uniqueTextures = 0, maskedTextures = 0;
	MeshGL staticGL, dynGL;
	UploadMesh(mesh, texCache, opacCache, staticGL,
		&uniqueTextures, &maskedTextures);
	UploadMesh(dynMesh, texCache, opacCache, dynGL,
		&uniqueTextures, &maskedTextures);
	Printf("GL world: uploaded %u unique index textures (%u with opacity).\n",
		uniqueTextures, maskedTextures);

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
		dev.Destroy();
		return false;
	}

	// --- camera calibrated to ECWolf ---
	AActor *cam = players[ConsolePlayer].camera
		? players[ConsolePlayer].camera : players[ConsolePlayer].mo;
	const float camX = (float)cam->x / (float)TILEGLOBAL;
	const float camY = (float)cam->y / (float)TILEGLOBAL;
	const float camZ = 0.5f;	// eye at mid-wall height
	const float yaw = (float)((double)cam->angle / 4294967296.0 * 2.0 * kPi);
	const float pitch = (float)((double)(int32_t)cam->pitch / 4294967296.0 * 2.0 * kPi);

	// ECWolf view direction convention: (cos a, -sin a) in the XY plane.
	float fwd[3] = {
		cosf(yaw) * cosf(pitch),
		-sinf(yaw) * cosf(pitch),
		sinf(pitch)
	};
	float up[3] = { 0.0f, 0.0f, 1.0f };
	float eye[3] = { camX, camY, camZ };

	const float hFovDeg = players[ConsolePlayer].FOV > 1.0f
		? players[ConsolePlayer].FOV : 90.0f;
	const float aspect = (float)W / (float)H;
	const float hFov = (float)(hFovDeg * kPi / 180.0);
	const float vFov = 2.0f * atanf(tanf(hFov * 0.5f) / aspect);

	Mat4 proj = Perspective(vFov, aspect, 0.02f, 256.0f);
	Mat4 view = LookAt(eye, fwd, up);

	// --- shading uniforms mirror the software renderer exactly ---
	const int shade = LIGHT2SHADE(gLevelLight + r_extralight);
	const bool corridor7 = IWad::CheckGameFilter("Corridor7");
	const int cyclePhase = (int)((gamestate.TimeCount >> 3) & 7);

	// Plane heights exactly as R_DrawPlane receives them: floor = viewz, ceiling
	// = viewz + level depth. The shader takes their magnitude.
	const float floorPlaneH = fabsf((float)viewz);
	const float ceilPlaneH  = fabsf((float)(viewz +
		(map->GetPlane(0).depth << FRACBITS)));

	glViewport(0, 0, W, H);
	glEnable(GL_DEPTH_TEST);
	glDepthFunc(GL_LESS);
	glDisable(GL_CULL_FACE);	// keep both faces during bring-up

	glUseProgram(prog);
	glUniformMatrix4fv(glGetUniformLocation(prog, "uProj"), 1, GL_FALSE, proj.m);
	glUniformMatrix4fv(glGetUniformLocation(prog, "uView"), 1, GL_FALSE, view.m);
	glUniform1f(glGetUniformLocation(prog, "uDepthVis"), (float)r_depthvisibility);
	glUniform1f(glGetUniformLocation(prog, "uHeightNum"), (float)heightnumerator);
	glUniform1f(glGetUniformLocation(prog, "uShade"), (float)shade);
	glUniform1f(glGetUniformLocation(prog, "uMaxLightVis"), (float)gLevelMaxLightVis);
	glUniform1i(glGetUniformLocation(prog, "uNumColormaps"), colormapRows);
	glUniform1i(glGetUniformLocation(prog, "uCyclePhase"), cyclePhase);
	glUniform1i(glGetUniformLocation(prog, "uRemap15"), (int)GPalette.Remap[15]);
	glUniform1i(glGetUniformLocation(prog, "uRemap254"), (int)GPalette.Remap[254]);
	glUniform1i(glGetUniformLocation(prog, "uRemap208"), (int)GPalette.Remap[208]);
	glUniform1i(glGetUniformLocation(prog, "uRemap239"), (int)GPalette.Remap[239]);
	glUniform1i(glGetUniformLocation(prog, "uCorridor7"), corridor7 ? 1 : 0);
	glUniform1i(glGetUniformLocation(prog, "uExtraLight"), r_extralight);
	glUniform1i(glGetUniformLocation(prog, "uViewW"), W);
	glUniform1i(glGetUniformLocation(prog, "uDither"), 1);
	glUniform1f(glGetUniformLocation(prog, "uHorizon"), (float)H * 0.5f);

	SurfaceUniforms su;
	su.uIndexTex    = glGetUniformLocation(prog, "uIndexTex");
	su.uOpacityTex  = glGetUniformLocation(prog, "uOpacityTex");
	su.uHasOpacity  = glGetUniformLocation(prog, "uHasOpacity");
	su.uSurfKind    = glGetUniformLocation(prog, "uSurfKind");
	su.uPlaneHeight = glGetUniformLocation(prog, "uPlaneHeight");
	su.uSlide       = glGetUniformLocation(prog, "uSlide");
	su.uSlideStyle  = glGetUniformLocation(prog, "uSlideStyle");
	su.uSlideAmount = glGetUniformLocation(prog, "uSlideAmount");
	su.floorPlaneH  = floorPlaneH;
	su.ceilPlaneH   = ceilPlaneH;
	const GLint uDebug = glGetUniformLocation(prog, "uDebug");

	// Palette (unit 1) and colormap (unit 2) are shared across every surface.
	glActiveTexture(GL_TEXTURE1);
	glBindTexture(GL_TEXTURE_2D, paletteTex);
	glUniform1i(glGetUniformLocation(prog, "uPaletteTex"), 1);
	glActiveTexture(GL_TEXTURE2);
	glBindTexture(GL_TEXTURE_2D, colormapTex);
	glUniform1i(glGetUniformLocation(prog, "uColormapTex"), 2);

	unsigned char *rgb = new unsigned char[(size_t)W * H * 3];

	// Pass 1: full-fidelity colour. Static opaque world first, then the dynamic
	// door/pushwall geometry, sharing one clear and depth buffer.
	glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
	glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
	glUniform1i(uDebug, 0);
	RenderMesh(mesh, staticGL, su);
	RenderMesh(dynMesh, dynGL, su);
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
		glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
		glUniform1i(uDebug, 1);
		RenderMesh(mesh, staticGL, su);
		RenderMesh(dynMesh, dynGL, su);
		glFinish();
		dev.ReadPixelsRGB(rgb, W, H);
		FString dbg;
		dbg.Format("%s.shaderow.ppm", outPath);
		if(WritePPM(dbg.GetChars(), rgb, W, H))
			Printf("GL world: wrote %s\n", dbg.GetChars());
	}

	delete[] rgb;

	// Cleanup.
	TMapIterator<int, GLuint> it(texCache);
	TMap<int, GLuint>::Pair *pair;
	while(it.NextPair(pair))
		if(pair->Value)
			glDeleteTextures(1, &pair->Value);
	TMapIterator<int, GLuint> ito(opacCache);
	while(ito.NextPair(pair))
		if(pair->Value)
			glDeleteTextures(1, &pair->Value);
	glDeleteTextures(1, &paletteTex);
	glDeleteTextures(1, &colormapTex);
	glDeleteRenderbuffers(1, &depthRb);
	glDeleteTextures(1, &colorTex);
	glDeleteFramebuffers(1, &fbo);
	DestroyMesh(staticGL);
	DestroyMesh(dynGL);
	glDeleteProgram(prog);
	dev.Destroy();

	return nonBg > 0;
}
