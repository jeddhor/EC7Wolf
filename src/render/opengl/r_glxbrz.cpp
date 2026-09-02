// ===========================================================================
//
// r_glxbrz.cpp - xBRZ image scaling as a GLSL pass (renderer redesign Phase 11).
//
// A port of deps/xbrz to the fragment shader, so the OpenGL present path gets
// the same filter the software path already has. See r_glxbrz.h for why the
// CPU implementation cannot simply be reused here.
//
// The port is deliberately literal. Every threshold, every color-distance
// quirk, and every blend weight is carried over from the C++ verbatim,
// including the ones that look like they could be simplified -- the buffered
// color distance quantises its input, and the blend weights are applied in a
// fixed order because later ones blend over the results of earlier ones. A
// "cleaner" shader that got any of that subtly wrong would still produce a
// plausible-looking picture, which is exactly why the two are compared against
// each other pixel for pixel by tools/test_glxbrz_parity.sh rather than by eye.
//
// ===========================================================================

#include "render/opengl/r_glxbrz.h"
#include "render/opengl/r_glshader.h"

#include <stdio.h>

#include "wl_def.h"
#include "c_cvars.h"
#include "m_png.h"
#include "r_capture.h"
#include "r_xbrz.h"
#include "xbrz.h"
#include "tarray.h"
#include "v_video.h"
#include "zdoomsupport.h"
#include "zstring.h"

namespace
{
	// A screen-filling triangle pair in clip space; both passes cover their whole
	// target, and each fragment finds its own source pixel from gl_FragCoord, so
	// no texture coordinates are interpolated.
	const char *kVertSrc =
		"#version 330 core\n"
		"layout(location=0) in vec2 aPos;\n"
		"void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }\n";

	// Shared by both passes: source access and the color distance the whole
	// algorithm is built on.
	const char *kCommonSrc =
		"uniform sampler2D uSrc;\n"
		"ivec2 gSize;\n"
		"\n"
		// The composite is stored bottom-up like any GL framebuffer, but xBRZ's
		// kernels are written in top-down raster order and its rules are not
		// symmetric under a vertical flip. Rather than transpose the rules, every
		// read flips here, so the algorithm below can be compared line for line
		// with the C++. Out-of-range reads clamp, matching OobReaderDuplicate,
		// which is what xbrz::scale selects for ColorFormat::RGB.
		"vec3 Texel(int x, int y)\n"
		"{\n"
		"    int cx = clamp(x, 0, gSize.x - 1);\n"
		"    int cy = clamp(y, 0, gSize.y - 1);\n"
		"    vec3 c = texelFetch(uSrc, ivec2(cx, gSize.y - 1 - cy), 0).rgb;\n"
		"    return floor(c * 255.0 + 0.5);\n"	// back to the 0-255 ints the rules assume
		"}\n"
		"\n"
		// distYCbCrBuffered. The buffered form is not merely a cached distYCbCr:
		// it indexes its lookup table by the channel difference halved and
		// truncated, so the difference it actually measures is rounded toward zero
		// to the nearest even number. That quantisation changes which side of a
		// threshold a marginal pixel falls on, so it is reproduced rather than
		// idealised away.
		"float Dist(vec3 p1, vec3 p2)\n"
		"{\n"
		"    vec3 d = trunc((p1 - p2) * 0.5) * 2.0;\n"
		"    const float k_b = 0.0593;\n"	// ITU-R BT.2020
		"    const float k_r = 0.2627;\n"
		"    const float k_g = 1.0 - k_b - k_r;\n"
		"    float y   = k_r * d.r + k_g * d.g + k_b * d.b;\n"
		"    float c_b = (0.5 / (1.0 - k_b)) * (d.b - y);\n"
		"    float c_r = (0.5 / (1.0 - k_r)) * (d.r - y);\n"
		"    return sqrt(y * y + c_b * c_b + c_r * c_r);\n"
		"}\n"
		"\n"
		"const float kEqualColorTolerance = 30.0;\n"
		"const float kCenterDirectionBias = 4.0;\n"
		"const float kDominantDirectionThreshold = 3.6;\n"
		"const float kSteepDirectionThreshold = 2.2;\n";

	// Pass 1: preProcessCorners for every source pixel, packed into the same byte
	// layout the C++ builds in its preprocessing buffer.
	//
	// Running this per source pixel rather than per output pixel is the whole
	// reason for the split. It is nine color distances per corner and four
	// corners per pixel; at 6x, folding it into the scaling pass would repeat all
	// of that thirty-six times over for a result that cannot differ.
	const char *kBlendFragSrc =
		"layout(location=0) out uint fragBlend;\n"
		"\n"
		/* input kernel area naming convention:
		   -----------------
		   | A | B | C | D |
		   |---|---|---|---|
		   | E | F | G | H |   evaluate the four corners between F, G, J, K
		   |---|---|---|---|   input pixel is at position F
		   | I | J | K | L |
		   |---|---|---|---|
		   | M | N | O | P |
		   -----------------                                                 */
		"ivec4 PreProcessCorners(int px, int py)\n"	// (blend_f, blend_g, blend_j, blend_k)
		"{\n"
		"    vec3 b = Texel(px    , py - 1), c = Texel(px + 1, py - 1);\n"
		"    vec3 e = Texel(px - 1, py    ), f = Texel(px    , py    );\n"
		"    vec3 g = Texel(px + 1, py    ), h = Texel(px + 2, py    );\n"
		"    vec3 i = Texel(px - 1, py + 1), j = Texel(px    , py + 1);\n"
		"    vec3 k = Texel(px + 1, py + 1), l = Texel(px + 2, py + 1);\n"
		"    vec3 n = Texel(px    , py + 2), o = Texel(px + 1, py + 2);\n"
		"\n"
		"    ivec4 res = ivec4(0);\n"
		"    if((f == g && j == k) || (f == j && g == k))\n"
		"        return res;\n"
		"\n"
		"    float jg = Dist(i, f) + Dist(f, c) + Dist(n, k) + Dist(k, h) +\n"
		"        kCenterDirectionBias * Dist(j, g);\n"
		"    float fk = Dist(e, j) + Dist(j, o) + Dist(b, g) + Dist(g, l) +\n"
		"        kCenterDirectionBias * Dist(f, k);\n"
		"\n"
		"    if(jg < fk)\n"
		"    {\n"
		"        int bt = kDominantDirectionThreshold * jg < fk ? 2 : 1;\n"
		"        if(f != g && f != j) res.x = bt;\n"
		"        if(k != j && k != g) res.w = bt;\n"
		"    }\n"
		"    else if(fk < jg)\n"
		"    {\n"
		"        int bt = kDominantDirectionThreshold * fk < jg ? 2 : 1;\n"
		"        if(j != f && j != k) res.z = bt;\n"
		"        if(g != f && g != k) res.y = bt;\n"
		"    }\n"
		"    return res;\n"
		"}\n"
		"\n"
		"void main()\n"
		"{\n"
		"    gSize = textureSize(uSrc, 0);\n"
		"    int sx = int(gl_FragCoord.x);\n"
		"    int sy = gSize.y - 1 - int(gl_FragCoord.y);\n"
		"\n"
		// Each corner of this pixel is the shared corner of a different 2x2, so
		// four evaluations are needed and each contributes one of them. The C++
		// reaches the same four by carrying results forward across the scan; here
		// they are simply recomputed, which is what makes the pass parallel.
		"    int blend = PreProcessCorners(sx - 1, sy - 1).w;\n"        // top left
		"    blend |= PreProcessCorners(sx    , sy - 1).z << 2;\n"      // top right
		"    blend |= PreProcessCorners(sx    , sy    ).x << 4;\n"      // bottom right
		"    blend |= PreProcessCorners(sx - 1, sy    ).y << 6;\n"      // bottom left
		"    fragBlend = uint(blend);\n"
		"}\n";

	// Pass 2: blendPixel, for the one output cell this fragment stands for.
	//
	// The C++ writes a whole scale x scale block per source pixel, through four
	// rotations that overwrite and blend over each other in sequence. A fragment
	// shader cannot write a block, so this inverts the relationship: each of the
	// same writes is replayed in the same order, and the ones that do not land on
	// this fragment's cell are discarded. Order is preserved because a later
	// blend composites over whatever an earlier one left behind.
	//
	// Compiled once per factor with S fixed, so the blend tables below -- which
	// genuinely differ per factor rather than scaling with it -- fold away to the
	// handful of comparisons that apply.
	const char *kScaleFragSrc =
		"uniform usampler2D uBlend;\n"
		"out vec4 fragColor;\n"
		"\n"
		"int gSx, gSy;\n"	// source pixel
		"int gI, gJ;\n"		// target cell within its S x S block (row, col)
		"int gRot;\n"
		"vec3 gCur;\n"
		"\n"
		"bool Eq(vec3 p1, vec3 p2) { return Dist(p1, p2) < kEqualColorTolerance; }\n"
		"\n"
		// The rotations are applied to the reads rather than to the image, exactly
		// as the C++ getters do: a 90 degree clockwise view of the kernel reads
		// the offset (dy, -dx).
		"vec3 Rot(int dx, int dy)\n"
		"{\n"
		"    ivec2 d = ivec2(dx, dy);\n"
		"    for(int r = 0; r < gRot; ++r)\n"
		"        d = ivec2(d.y, -d.x);\n"
		"    return Texel(gSx + d.x, gSy + d.y);\n"
		"}\n"
		"\n"
		// OutputMatrix::ref<I,J>: where a write addressed in the rotated frame
		// lands in the unrotated block.
		"bool Hits(int I, int J)\n"
		"{\n"
		"    ivec2 t;\n"
		"    if(gRot == 0)      t = ivec2(I, J);\n"
		"    else if(gRot == 1) t = ivec2(S - 1 - J, I);\n"
		"    else if(gRot == 2) t = ivec2(S - 1 - I, S - 1 - J);\n"
		"    else               t = ivec2(J, S - 1 - I);\n"
		"    return t.x == gI && t.y == gJ;\n"
		"}\n"
		"\n"
		// gradientRGB: front over back at opacity m/n, in the integer arithmetic
		// the C++ uses. The truncation is kept because it is worth up to a level
		// per channel and this shader is checked against that output exactly.
		"void Grad(int I, int J, float m, float n, vec3 col)\n"
		"{\n"
		"    if(Hits(I, J))\n"
		"        gCur = floor((col * m + gCur * (n - m)) / n);\n"
		"}\n"
		"\n"
		"void Set(int I, int J, vec3 col)\n"
		"{\n"
		"    if(Hits(I, J))\n"
		"        gCur = col;\n"
		"}\n"
		"\n"
		"void BlendLineShallow(vec3 col)\n"
		"{\n"
		"#if S == 2\n"
		"    Grad(S-1, 0, 1.0, 4.0, col);\n"
		"    Grad(S-1, 1, 3.0, 4.0, col);\n"
		"#elif S == 3\n"
		"    Grad(S-1, 0, 1.0, 4.0, col);\n"
		"    Grad(S-2, 2, 1.0, 4.0, col);\n"
		"    Grad(S-1, 1, 3.0, 4.0, col);\n"
		"    Set (S-1, 2, col);\n"
		"#elif S == 4\n"
		"    Grad(S-1, 0, 1.0, 4.0, col);\n"
		"    Grad(S-2, 2, 1.0, 4.0, col);\n"
		"    Grad(S-1, 1, 3.0, 4.0, col);\n"
		"    Grad(S-2, 3, 3.0, 4.0, col);\n"
		"    Set (S-1, 2, col);\n"
		"    Set (S-1, 3, col);\n"
		"#elif S == 5\n"
		"    Grad(S-1, 0, 1.0, 4.0, col);\n"
		"    Grad(S-2, 2, 1.0, 4.0, col);\n"
		"    Grad(S-3, 4, 1.0, 4.0, col);\n"
		"    Grad(S-1, 1, 3.0, 4.0, col);\n"
		"    Grad(S-2, 3, 3.0, 4.0, col);\n"
		"    Set (S-1, 2, col);\n"
		"    Set (S-1, 3, col);\n"
		"    Set (S-1, 4, col);\n"
		"    Set (S-2, 4, col);\n"
		"#else\n"
		"    Grad(S-1, 0, 1.0, 4.0, col);\n"
		"    Grad(S-2, 2, 1.0, 4.0, col);\n"
		"    Grad(S-3, 4, 1.0, 4.0, col);\n"
		"    Grad(S-1, 1, 3.0, 4.0, col);\n"
		"    Grad(S-2, 3, 3.0, 4.0, col);\n"
		"    Grad(S-3, 5, 3.0, 4.0, col);\n"
		"    Set (S-1, 2, col);\n"
		"    Set (S-1, 3, col);\n"
		"    Set (S-1, 4, col);\n"
		"    Set (S-1, 5, col);\n"
		"    Set (S-2, 4, col);\n"
		"    Set (S-2, 5, col);\n"
		"#endif\n"
		"}\n"
		"\n"
		"void BlendLineSteep(vec3 col)\n"
		"{\n"
		"#if S == 2\n"
		"    Grad(0, S-1, 1.0, 4.0, col);\n"
		"    Grad(1, S-1, 3.0, 4.0, col);\n"
		"#elif S == 3\n"
		"    Grad(0, S-1, 1.0, 4.0, col);\n"
		"    Grad(2, S-2, 1.0, 4.0, col);\n"
		"    Grad(1, S-1, 3.0, 4.0, col);\n"
		"    Set (2, S-1, col);\n"
		"#elif S == 4\n"
		"    Grad(0, S-1, 1.0, 4.0, col);\n"
		"    Grad(2, S-2, 1.0, 4.0, col);\n"
		"    Grad(1, S-1, 3.0, 4.0, col);\n"
		"    Grad(3, S-2, 3.0, 4.0, col);\n"
		"    Set (2, S-1, col);\n"
		"    Set (3, S-1, col);\n"
		"#elif S == 5\n"
		"    Grad(0, S-1, 1.0, 4.0, col);\n"
		"    Grad(2, S-2, 1.0, 4.0, col);\n"
		"    Grad(4, S-3, 1.0, 4.0, col);\n"
		"    Grad(1, S-1, 3.0, 4.0, col);\n"
		"    Grad(3, S-2, 3.0, 4.0, col);\n"
		"    Set (2, S-1, col);\n"
		"    Set (3, S-1, col);\n"
		"    Set (4, S-1, col);\n"
		"    Set (4, S-2, col);\n"
		"#else\n"
		"    Grad(0, S-1, 1.0, 4.0, col);\n"
		"    Grad(2, S-2, 1.0, 4.0, col);\n"
		"    Grad(4, S-3, 1.0, 4.0, col);\n"
		"    Grad(1, S-1, 3.0, 4.0, col);\n"
		"    Grad(3, S-2, 3.0, 4.0, col);\n"
		"    Grad(5, S-3, 3.0, 4.0, col);\n"
		"    Set (2, S-1, col);\n"
		"    Set (3, S-1, col);\n"
		"    Set (4, S-1, col);\n"
		"    Set (5, S-1, col);\n"
		"    Set (4, S-2, col);\n"
		"    Set (5, S-2, col);\n"
		"#endif\n"
		"}\n"
		"\n"
		"void BlendLineSteepAndShallow(vec3 col)\n"
		"{\n"
		"#if S == 2\n"
		"    Grad(1, 0, 1.0, 4.0, col);\n"
		"    Grad(0, 1, 1.0, 4.0, col);\n"
		"    Grad(1, 1, 5.0, 6.0, col);\n"
		"#elif S == 3\n"
		"    Grad(2, 0, 1.0, 4.0, col);\n"
		"    Grad(0, 2, 1.0, 4.0, col);\n"
		"    Grad(2, 1, 3.0, 4.0, col);\n"
		"    Grad(1, 2, 3.0, 4.0, col);\n"
		"    Set (2, 2, col);\n"
		"#elif S == 4\n"
		"    Grad(3, 1, 3.0, 4.0, col);\n"
		"    Grad(1, 3, 3.0, 4.0, col);\n"
		"    Grad(3, 0, 1.0, 4.0, col);\n"
		"    Grad(0, 3, 1.0, 4.0, col);\n"
		"    Grad(2, 2, 1.0, 3.0, col);\n"
		"    Set (3, 3, col);\n"
		"    Set (3, 2, col);\n"
		"    Set (2, 3, col);\n"
		"#elif S == 5\n"
		"    Grad(0, S-1, 1.0, 4.0, col);\n"
		"    Grad(2, S-2, 1.0, 4.0, col);\n"
		"    Grad(1, S-1, 3.0, 4.0, col);\n"
		"    Grad(S-1, 0, 1.0, 4.0, col);\n"
		"    Grad(S-2, 2, 1.0, 4.0, col);\n"
		"    Grad(S-1, 1, 3.0, 4.0, col);\n"
		"    Grad(3, 3, 2.0, 3.0, col);\n"
		"    Set (2, S-1, col);\n"
		"    Set (3, S-1, col);\n"
		"    Set (4, S-1, col);\n"
		"    Set (S-1, 2, col);\n"
		"    Set (S-1, 3, col);\n"
		"#else\n"
		"    Grad(0, S-1, 1.0, 4.0, col);\n"
		"    Grad(2, S-2, 1.0, 4.0, col);\n"
		"    Grad(1, S-1, 3.0, 4.0, col);\n"
		"    Grad(3, S-2, 3.0, 4.0, col);\n"
		"    Grad(S-1, 0, 1.0, 4.0, col);\n"
		"    Grad(S-2, 2, 1.0, 4.0, col);\n"
		"    Grad(S-1, 1, 3.0, 4.0, col);\n"
		"    Grad(S-2, 3, 3.0, 4.0, col);\n"
		"    Set (2, S-1, col);\n"
		"    Set (3, S-1, col);\n"
		"    Set (4, S-1, col);\n"
		"    Set (5, S-1, col);\n"
		"    Set (4, S-2, col);\n"
		"    Set (5, S-2, col);\n"
		"    Set (S-1, 2, col);\n"
		"    Set (S-1, 3, col);\n"
		"#endif\n"
		"}\n"
		"\n"
		"void BlendLineDiagonal(vec3 col)\n"
		"{\n"
		"#if S == 2\n"
		"    Grad(1, 1, 1.0, 2.0, col);\n"
		"#elif S == 3\n"
		"    Grad(1, 2, 1.0, 8.0, col);\n"
		"    Grad(2, 1, 1.0, 8.0, col);\n"
		"    Grad(2, 2, 7.0, 8.0, col);\n"
		"#elif S == 4\n"
		"    Grad(S-1, S/2  , 1.0, 2.0, col);\n"
		"    Grad(S-2, S/2+1, 1.0, 2.0, col);\n"
		"    Set (S-1, S-1, col);\n"
		"#elif S == 5\n"
		"    Grad(S-1, S/2  , 1.0, 8.0, col);\n"
		"    Grad(S-2, S/2+1, 1.0, 8.0, col);\n"
		"    Grad(S-3, S/2+2, 1.0, 8.0, col);\n"
		"    Grad(4, 3, 7.0, 8.0, col);\n"
		"    Grad(3, 4, 7.0, 8.0, col);\n"
		"    Set (4, 4, col);\n"
		"#else\n"
		"    Grad(S-1, S/2  , 1.0, 2.0, col);\n"
		"    Grad(S-2, S/2+1, 1.0, 2.0, col);\n"
		"    Grad(S-3, S/2+2, 1.0, 2.0, col);\n"
		"    Set (S-2, S-1, col);\n"
		"    Set (S-1, S-1, col);\n"
		"    Set (S-1, S-2, col);\n"
		"#endif\n"
		"}\n"
		"\n"
		"void BlendCorner(vec3 col)\n"
		"{\n"
		// A quarter disc, approximated per factor -- the weights are the coverage
		// of each cell, not a formula.
		"#if S == 2\n"
		"    Grad(1, 1, 21.0, 100.0, col);\n"
		"#elif S == 3\n"
		"    Grad(2, 2, 45.0, 100.0, col);\n"
		"#elif S == 4\n"
		"    Grad(3, 3, 68.0, 100.0, col);\n"
		"    Grad(3, 2,  9.0, 100.0, col);\n"
		"    Grad(2, 3,  9.0, 100.0, col);\n"
		"#elif S == 5\n"
		"    Grad(4, 4, 86.0, 100.0, col);\n"
		"    Grad(4, 3, 23.0, 100.0, col);\n"
		"    Grad(3, 4, 23.0, 100.0, col);\n"
		"#else\n"
		"    Grad(5, 5, 97.0, 100.0, col);\n"
		"    Grad(4, 5, 42.0, 100.0, col);\n"
		"    Grad(5, 4, 42.0, 100.0, col);\n"
		"    Grad(5, 3,  6.0, 100.0, col);\n"
		"    Grad(3, 5,  6.0, 100.0, col);\n"
		"#endif\n"
		"}\n"
		"\n"
		"int RotateBlendInfo(int b)\n"
		"{\n"
		"    if(gRot == 1) return ((b << 2) | (b >> 6)) & 0xFF;\n"
		"    if(gRot == 2) return ((b << 4) | (b >> 4)) & 0xFF;\n"
		"    if(gRot == 3) return ((b << 6) | (b >> 2)) & 0xFF;\n"
		"    return b;\n"
		"}\n"
		"\n"
		/* input kernel area naming convention:
		   -------------
		   | A | B | C |
		   |---|---|---|
		   | D | E | F | input pixel is at position E
		   |---|---|---|
		   | G | H | I |
		   -------------                                                     */
		"void BlendPixel(int blendInfo)\n"
		"{\n"
		"    int blend = RotateBlendInfo(blendInfo);\n"
		"    if(((blend >> 4) & 3) == 0)\n"	// bottom-right corner: nothing to do
		"        return;\n"
		"\n"
		"    vec3 b = Rot( 0, -1), c = Rot( 1, -1);\n"
		"    vec3 d = Rot(-1,  0), e = Rot( 0,  0), f = Rot(1, 0);\n"
		"    vec3 g = Rot(-1,  1), h = Rot( 0,  1), i = Rot(1, 1);\n"
		"\n"
		"    bool doLineBlend = true;\n"
		"    if(((blend >> 4) & 3) < 2)\n"	// not dominant: the exceptions apply
		"    {\n"
		// No second blending in an adjacent rotation (insular pixels, mario eyes),
		// but 90 degree corners still get to double-blend.
		"        if(((blend >> 2) & 3) != 0 && !Eq(e, g))\n"
		"            doLineBlend = false;\n"
		"        else if(((blend >> 6) & 3) != 0 && !Eq(e, c))\n"
		"            doLineBlend = false;\n"
		// No full blending for L-shapes; blend the corner only.
		"        else if(!Eq(e, i) && Eq(g, h) && Eq(h, i) && Eq(i, f) && Eq(f, c))\n"
		"            doLineBlend = false;\n"
		"    }\n"
		"\n"
		"    vec3 px = Dist(e, f) <= Dist(e, h) ? f : h;\n"	// most similar color
		"\n"
		"    if(doLineBlend)\n"
		"    {\n"
		"        float fg = Dist(f, g);\n"
		"        float hc = Dist(h, c);\n"
		"        bool shallow = kSteepDirectionThreshold * fg <= hc && e != g && d != g;\n"
		"        bool steep   = kSteepDirectionThreshold * hc <= fg && e != c && b != c;\n"
		"        if(shallow && steep) BlendLineSteepAndShallow(px);\n"
		"        else if(shallow)     BlendLineShallow(px);\n"
		"        else if(steep)       BlendLineSteep(px);\n"
		"        else                 BlendLineDiagonal(px);\n"
		"    }\n"
		"    else\n"
		"        BlendCorner(px);\n"
		"}\n"
		"\n"
		"void main()\n"
		"{\n"
		"    gSize = textureSize(uSrc, 0);\n"
		"    int ox = int(gl_FragCoord.x);\n"
		"    int oy = gSize.y * S - 1 - int(gl_FragCoord.y);\n"
		"    gSx = ox / S; gJ = ox - gSx * S;\n"
		"    gSy = oy / S; gI = oy - gSy * S;\n"
		"\n"
		"    gCur = Texel(gSx, gSy);\n"	// fillBlock: the source pixel, unfiltered
		"\n"
		"    int blendInfo = int(texelFetch(uBlend,\n"
		"        ivec2(gSx, gSize.y - 1 - gSy), 0).r);\n"
		"    if(blendInfo != 0)\n"
		"        for(gRot = 0; gRot < 4; ++gRot)\n"
		"            BlendPixel(blendInfo);\n"
		"\n"
		"    fragColor = vec4(gCur / 255.0, 1.0);\n"
		"}\n";

	// The array bounds below need a compile-time constant; XBRZ_MAX_FACTOR is a
	// linked-in const, so take the same value from the upstream header it is
	// defined from. The static assert keeps the two from drifting apart.
	const int kMaxFactor = xbrz::SCALE_FACTOR_MAX;

	struct GLXBRZ
	{
		bool   triedBlendProg;
		GLuint blendProg;
		GLuint scaleProg[kMaxFactor + 1];		// indexed by factor
		bool   triedScaleProg[kMaxFactor + 1];

		GLuint srcFbo, srcTex;		// composite target, fw x fh
		GLuint blendFbo, blendTex;	// preprocessing result, fw x fh, R8UI
		GLuint dstFbo, dstTex;		// scaled frame, fw*factor x fh*factor
		int    srcW, srcH, dstFactor;

		int    factor;		// nonzero between Begin and End: compositing is redirected
		int    lastFactor;	// what End actually scaled by, for the parity capture
		FString parityPath;

		GLXBRZ() : triedBlendProg(false), blendProg(0),
			srcFbo(0), srcTex(0), blendFbo(0), blendTex(0), dstFbo(0), dstTex(0),
			srcW(0), srcH(0), dstFactor(0), factor(0), lastFactor(0)
		{
			for(int i = 0; i <= kMaxFactor; ++i)
			{
				scaleProg[i] = 0;
				triedScaleProg[i] = false;
			}
		}
	};
	GLXBRZ g;

	void DrawFullQuad()
	{
		static const float verts[] = {
			-1.0f, -1.0f,  1.0f, -1.0f,  1.0f, 1.0f,
			-1.0f, -1.0f,  1.0f,  1.0f, -1.0f, 1.0f,
		};
		GLuint vao = 0, vbo = 0;
		glGenVertexArrays(1, &vao);
		glBindVertexArray(vao);
		glGenBuffers(1, &vbo);
		glBindBuffer(GL_ARRAY_BUFFER, vbo);
		glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
		glEnableVertexAttribArray(0);
		glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2*sizeof(float), (void*)0);
		glDrawArrays(GL_TRIANGLES, 0, 6);
		glDeleteBuffers(1, &vbo);
		glDeleteVertexArrays(1, &vao);
	}

	GLuint MakeTarget(GLuint &fbo, GLuint &tex, int w, int h, GLenum internalFmt,
		GLenum fmt, GLenum type)
	{
		if(tex) glDeleteTextures(1, &tex);
		if(fbo) glDeleteFramebuffers(1, &fbo);
		glGenFramebuffers(1, &fbo);
		glBindFramebuffer(GL_FRAMEBUFFER, fbo);
		glGenTextures(1, &tex);
		glBindTexture(GL_TEXTURE_2D, tex);
		glTexImage2D(GL_TEXTURE_2D, 0, internalFmt, w, h, 0, fmt, type, NULL);
		// Nearest throughout: every read in both passes is a texelFetch of a
		// specific pixel, and the algorithm's whole premise is that those pixels
		// are exact. The only filtering that should happen is the final stretch to
		// the window.
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
		glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
			GL_TEXTURE_2D, tex, 0);
		return glCheckFramebufferStatus(GL_FRAMEBUFFER);
	}

	bool EnsurePrograms(int factor)
	{
		if(!g.triedBlendProg)
		{
			g.triedBlendProg = true;
			FString src = "#version 330 core\n";
			src += kCommonSrc;
			src += kBlendFragSrc;
			g.blendProg = GLShader::Build(kVertSrc, src.GetChars(), "xbrz-preprocess");
		}
		if(!g.blendProg)
			return false;

		if(!g.triedScaleProg[factor])
		{
			g.triedScaleProg[factor] = true;
			FString src;
			src.Format("#version 330 core\n#define S %d\n", factor);
			src += kCommonSrc;
			src += kScaleFragSrc;
			FString name;
			name.Format("xbrz-scale-%dx", factor);
			g.scaleProg[factor] = GLShader::Build(kVertSrc, src.GetChars(),
				name.GetChars());
		}
		return g.scaleProg[factor] != 0;
	}

	bool EnsureTargets(int fw, int fh, int factor)
	{
		if(g.srcFbo && g.srcW == fw && g.srcH == fh && g.dstFactor == factor)
			return true;

		if(MakeTarget(g.srcFbo, g.srcTex, fw, fh, GL_RGBA8, GL_RGBA,
			GL_UNSIGNED_BYTE) != GL_FRAMEBUFFER_COMPLETE)
			return false;
		// R8UI, not a normalized format: the preprocessing result is four 2-bit
		// fields packed into a byte, and normalizing it would be a round trip
		// through a float for data that is never a color.
		if(MakeTarget(g.blendFbo, g.blendTex, fw, fh, GL_R8UI, GL_RED_INTEGER,
			GL_UNSIGNED_BYTE) != GL_FRAMEBUFFER_COMPLETE)
			return false;
		if(MakeTarget(g.dstFbo, g.dstTex, fw*factor, fh*factor, GL_RGBA8, GL_RGBA,
			GL_UNSIGNED_BYTE) != GL_FRAMEBUFFER_COMPLETE)
			return false;

		g.srcW = fw;
		g.srcH = fh;
		g.dstFactor = factor;
		return true;
	}

	void WritePNG(const char *path, const BYTE *data, ESSType type, int w, int h,
		int pitch)
	{
		FILE *file = fopen(path, "wb");
		if(file == NULL)
		{
			Printf("GL xBRZ: FAILED to open '%s'\n", path);
			return;
		}
		M_CreatePNG(file, data, NULL, type, w, h, pitch);
		M_FinishPNG(file);
		fclose(file);
	}
}

int R_GLXBRZBegin(int fw, int fh, int drawableW, int drawableH)
{
	g.factor = 0;
	if(fw <= 0 || fh <= 0)
		return 0;

	// The same decision the software path makes, from the same setting, so the
	// two renderers pick the same factor for a given window.
	const int factor = R_XBRZFactor(fw, fh, drawableW, drawableH);
	if(factor < 2)
		return 0;

	if(!EnsurePrograms(factor) || !EnsureTargets(fw, fh, factor))
	{
		// A shader that will not compile or a target that will not allocate is
		// reported once and then simply means no scaling: the frame still gets
		// composited to the window by the caller's usual path.
		return 0;
	}

	glBindFramebuffer(GL_FRAMEBUFFER, g.srcFbo);
	glViewport(0, 0, fw, fh);
	g.factor = factor;
	return factor;
}

void R_GLXBRZEnd(int drawableW, int drawableH)
{
	const int factor = g.factor;
	g.factor = 0;
	g.lastFactor = factor;

	if(factor >= 2)
	{
		glDisable(GL_DEPTH_TEST);
		glDisable(GL_BLEND);

		glBindFramebuffer(GL_FRAMEBUFFER, g.blendFbo);
		glViewport(0, 0, g.srcW, g.srcH);
		glUseProgram(g.blendProg);
		glActiveTexture(GL_TEXTURE0);
		glBindTexture(GL_TEXTURE_2D, g.srcTex);
		glUniform1i(glGetUniformLocation(g.blendProg, "uSrc"), 0);
		DrawFullQuad();

		glBindFramebuffer(GL_FRAMEBUFFER, g.dstFbo);
		glViewport(0, 0, g.srcW*factor, g.srcH*factor);
		glUseProgram(g.scaleProg[factor]);
		glActiveTexture(GL_TEXTURE0);
		glBindTexture(GL_TEXTURE_2D, g.srcTex);
		glUniform1i(glGetUniformLocation(g.scaleProg[factor], "uSrc"), 0);
		glActiveTexture(GL_TEXTURE1);
		glBindTexture(GL_TEXTURE_2D, g.blendTex);
		glUniform1i(glGetUniformLocation(g.scaleProg[factor], "uBlend"), 1);
		DrawFullQuad();

		// Straight to the window, linearly. The scaled frame is rarely an exact
		// multiple of the window -- a 3x scale of 640x400 into a 1920x1080 window
		// is short in height -- and this last stretch is the one place in the
		// pipeline where smoothing is wanted rather than avoided. It is also what
		// the software path does, where SDL performs the same stretch.
		glBindFramebuffer(GL_READ_FRAMEBUFFER, g.dstFbo);
		glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
		glBlitFramebuffer(0, 0, g.srcW*factor, g.srcH*factor,
			0, 0, drawableW, drawableH, GL_COLOR_BUFFER_BIT, GL_LINEAR);
	}

	glBindFramebuffer(GL_FRAMEBUFFER, 0);
	glViewport(0, 0, drawableW, drawableH);
	glUseProgram(0);
	glActiveTexture(GL_TEXTURE0);
}

void R_GLXBRZArmParityCapture(const char *path)
{
	g.parityPath = path;
}

void R_GLXBRZWriteParity(const unsigned char *mem, int pitch, int fw, int fh,
	bool haveWorld)
{
	if(g.parityPath.IsEmpty() || g.lastFactor < 2 || mem == NULL)
		return;
	if(haveWorld)
		return;		// see the header: only 2D frames are a like-for-like comparison
	if(fw != g.srcW || fh != g.srcH)
		return;

	const int factor = g.lastFactor;
	const int w = fw * factor, h = fh * factor;
	const FString base = g.parityPath;
	g.parityPath = "";	// one frame only, whatever happens below

	// The shader's output, read back from the scaled buffer rather than from the
	// window: the window has had the final stretch applied and would compare the
	// blit rather than the filter.
	TArray<unsigned char> rgb((unsigned)(w * h * 3));
	rgb.Resize((unsigned)(w * h * 3));
	TArray<unsigned char> flip((unsigned)(w * h * 3));
	flip.Resize((unsigned)(w * h * 3));
	glBindFramebuffer(GL_READ_FRAMEBUFFER, g.dstFbo);
	glPixelStorei(GL_PACK_ALIGNMENT, 1);
	glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, &flip[0]);
	glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
	for(int y = 0; y < h; ++y)
		memcpy(&rgb[(size_t)y * w * 3], &flip[(size_t)(h - 1 - y) * w * 3],
			(size_t)w * 3);

	FString glPath, cpuPath;
	glPath.Format("%s-gl.png", base.GetChars());
	cpuPath.Format("%s-cpu.png", base.GetChars());

	// Both paths start from the same indexed frame and the same palette, which is
	// the whole point: any difference in the output is the filter, not the input.
	PalEntry pal[256];
	if(screen != NULL)
		screen->GetFlashedPalette(pal);
	else
		memcpy(pal, GPalette.BaseColors, sizeof(pal));

	const uint32_t *const cpu = R_XBRZScaleIndexed(mem, pitch, fw, fh, pal, factor);

	WritePNG(glPath.GetChars(), &rgb[0], SS_RGB, w, h, w*3);
	if(cpu != NULL)
		WritePNG(cpuPath.GetChars(), (const BYTE *)cpu, SS_BGRA, w, h,
			w * (int)sizeof(uint32_t));

	Printf("GL xBRZ: wrote %dx parity pair '%s' / '%s' (%dx%d).\n",
		factor, glPath.GetChars(), cpuPath.GetChars(), w, h);

	// Both files are closed by now, so the run has produced everything it was
	// asked for and can end at the next present. This page counts no gameplay
	// frames, so nothing else would ever end it.
	Capture::NoteArtifactComplete();
}

void R_GLXBRZShutdown()
{
	if(g.srcTex)   glDeleteTextures(1, &g.srcTex);
	if(g.blendTex) glDeleteTextures(1, &g.blendTex);
	if(g.dstTex)   glDeleteTextures(1, &g.dstTex);
	if(g.srcFbo)   glDeleteFramebuffers(1, &g.srcFbo);
	if(g.blendFbo) glDeleteFramebuffers(1, &g.blendFbo);
	if(g.dstFbo)   glDeleteFramebuffers(1, &g.dstFbo);
	if(g.blendProg) glDeleteProgram(g.blendProg);
	for(int i = 0; i <= kMaxFactor; ++i)
		if(g.scaleProg[i])
			glDeleteProgram(g.scaleProg[i]);

	// Everything is rebuilt lazily, so a video mode change can simply tear down
	// and carry on. The armed capture path survives: it is set once at startup.
	const FString parityPath = g.parityPath;
	g = GLXBRZ();
	g.parityPath = parityPath;
}
