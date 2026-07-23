// ===========================================================================
//
// r_glworld.cpp - GL static-world render + offscreen capture (Phase 5).
//
// ===========================================================================

#include <stdio.h>
#include <math.h>

#include <epoxy/gl.h>

#include "render/opengl/r_glworld.h"
#include "render/opengl/r_gldevice.h"
#include "render/opengl/r_glshader.h"
#include "render/r_worldbuilder.h"
#include "wl_def.h"
#include "zdoomsupport.h"
#include "wl_main.h"
#include "wl_play.h"
#include "wl_agent.h"
#include "actor.h"
#include "id_ca.h"
#include "gamemap.h"

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

	const char *kVert =
		"#version 330 core\n"
		"layout(location=0) in vec3 aPos;\n"
		"layout(location=1) in vec2 aUV;\n"
		"layout(location=2) in float aTexKey;\n"
		"layout(location=3) in float aShade;\n"
		"uniform mat4 uMVP;\n"
		"out vec2 vUV; out float vTexKey; out float vShade;\n"
		"void main(){ gl_Position = uMVP * vec4(aPos,1.0); vUV=aUV; vTexKey=aTexKey; vShade=aShade; }\n";

	// Phase 5 debug shading: a stable pseudo-colour per texture index, shaded
	// per face. Real indexed textures + palette land in Phase 6.
	const char *kFrag =
		"#version 330 core\n"
		"in vec2 vUV; in float vTexKey; in float vShade;\n"
		"out vec4 fragColor;\n"
		"void main(){\n"
		"    float k = vTexKey;\n"
		"    vec3 c = vec3(fract(k*0.1234+0.11), fract(k*0.2345+0.37), fract(k*0.3456+0.59));\n"
		"    c = mix(vec3(0.55), c, 0.85) * vShade;\n"
		"    fragColor = vec4(c, 1.0);\n"
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

	// Build the static world mesh (backend-neutral).
	WorldMesh mesh;
	WorldBuilder::Build(map, mesh);
	Printf("GL world: mesh walls=%u floors=%u ceilings=%u verts=%u\n",
		mesh.wallFaces, mesh.floorTiles, mesh.ceilingTiles,
		(unsigned)mesh.vertices.Size());
	if(mesh.vertices.Size() == 0)
		return false;

	GLDevice dev;
	if(!dev.Create(W, H, false, /*hidden=*/true, "EC7Wolf GL world"))
		return false;

	GLuint prog = GLShader::Build(kVert, kFrag, "world-debug");
	if(!prog) { dev.Destroy(); return false; }

	GLuint vao = 0, vbo = 0;
	glGenVertexArrays(1, &vao);
	glBindVertexArray(vao);
	glGenBuffers(1, &vbo);
	glBindBuffer(GL_ARRAY_BUFFER, vbo);
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
	Mat4 mvp = Multiply(proj, view);

	glViewport(0, 0, W, H);
	glEnable(GL_DEPTH_TEST);
	glDepthFunc(GL_LESS);
	glDisable(GL_CULL_FACE);	// keep both faces during bring-up
	glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
	glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

	glUseProgram(prog);
	glUniformMatrix4fv(glGetUniformLocation(prog, "uMVP"), 1, GL_FALSE, mvp.m);
	glBindVertexArray(vao);
	glDrawArrays(GL_TRIANGLES, 0, (GLsizei)mesh.vertices.Size());
	glFinish();

	unsigned char *rgb = new unsigned char[(size_t)W * H * 3];
	dev.ReadPixelsRGB(rgb, W, H);

	// Diagnostic: how much of the frame is non-background.
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

	delete[] rgb;
	glDeleteRenderbuffers(1, &depthRb);
	glDeleteTextures(1, &colorTex);
	glDeleteFramebuffers(1, &fbo);
	glDeleteBuffers(1, &vbo);
	glDeleteVertexArrays(1, &vao);
	glDeleteProgram(prog);
	dev.Destroy();

	return nonBg > 0;
}
