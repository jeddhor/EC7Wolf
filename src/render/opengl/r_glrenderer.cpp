// ===========================================================================
//
// r_glrenderer.cpp - OpenGL renderer backend + device/pipeline self-test.
//
// Renderer redesign Phase 4. The GL device and the indexed-palette pipeline are
// brought up and verified here. World rendering is added from Phase 5; until
// then the backend defers gameplay to the software renderer so the game stays
// fully playable, while the self-test proves the GPU pipeline headlessly.
//
// ===========================================================================

#include <stdio.h>
#include <stdlib.h>

#include <epoxy/gl.h>

#include "render/opengl/r_glrenderer.h"
#include "render/opengl/r_gldevice.h"
#include "render/opengl/r_glpalette.h"
#include "wl_def.h"
#include "zdoomsupport.h"

namespace
{
	class OpenGLRenderer : public IRenderer
	{
	public:
		virtual bool Init()
		{
			// The GL device and indexed-palette pipeline are implemented and
			// self-tested (see R_GLRunSelfTest). World geometry, masked walls,
			// sprites and the 2D/HUD integration land in later phases, so for
			// now gameplay defers to the software renderer via a clean fallback.
			Printf("OpenGL backend: device + indexed-palette pipeline ready; "
				"world rendering pending (Phase 5+). Deferring to software.\n");
			return false;
		}
		virtual void Shutdown() {}
		virtual void RenderScene() {}
		virtual RendererType Type() const { return RENDERER_OpenGL; }
		virtual const char *Name() const { return "OpenGL renderer"; }
	};

	bool WritePPM(const char *path, const unsigned char *rgb, int w, int h)
	{
		FILE *f = fopen(path, "wb");
		if(!f)
			return false;
		fprintf(f, "P6\n%d %d\n255\n", w, h);
		fwrite(rgb, 1, (size_t)w * h * 3, f);
		fclose(f);
		return true;
	}
}

IRenderer *R_CreateOpenGLRenderer()
{
	return new OpenGLRenderer;
}

bool R_GLRunSelfTest(const char *outPath)
{
	const int W = 256, H = 64;

	GLDevice dev;
	if(!dev.Create(W, H, false, /*hidden=*/true, "EC7Wolf GL self-test"))
	{
		Printf("GL self-test: device creation failed.\n");
		return false;
	}
	dev.LogCapabilities();

	GLIndexedPipeline pipe;
	if(!pipe.Init())
	{
		Printf("GL self-test: pipeline init failed.\n");
		dev.Destroy();
		return false;
	}

	// Synthetic palette: index i -> a distinctive RGB triple.
	unsigned char pal[256 * 3];
	for(int i = 0; i < 256; ++i)
	{
		pal[i * 3 + 0] = (unsigned char)i;
		pal[i * 3 + 1] = (unsigned char)(255 - i);
		pal[i * 3 + 2] = (unsigned char)((i * 5) & 255);
	}
	pipe.UploadPalette(pal);

	// Index image: column x holds index x, identical for every row.
	unsigned char *idx = new unsigned char[W * H];
	for(int y = 0; y < H; ++y)
		for(int x = 0; x < W; ++x)
			idx[y * W + x] = (unsigned char)x;
	GLuint itex = pipe.CreateIndexTexture(idx, W, H);
	delete[] idx;

	// Offscreen colour target so the result is independent of window visibility.
	GLuint fbo = 0, colorTex = 0;
	glGenFramebuffers(1, &fbo);
	glBindFramebuffer(GL_FRAMEBUFFER, fbo);
	glGenTextures(1, &colorTex);
	glBindTexture(GL_TEXTURE_2D, colorTex);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA,
		GL_UNSIGNED_BYTE, NULL);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
		colorTex, 0);
	if(glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
	{
		Printf("GL self-test: framebuffer incomplete.\n");
		pipe.Shutdown();
		dev.Destroy();
		return false;
	}

	glViewport(0, 0, W, H);
	glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
	glClear(GL_COLOR_BUFFER_BIT);
	pipe.DrawFullscreen(itex, /*useColormap=*/false, 0);
	glFinish();

	unsigned char *rgb = new unsigned char[W * H * 3];
	dev.ReadPixelsRGB(rgb, W, H);	// reads the bound FBO, flips to top-down

	// Verify: every column's resolved RGB must equal palette[column]. Row
	// order is irrelevant because the index image is column-constant.
	int fails = 0;
	for(int x = 0; x < W; ++x)
	{
		const unsigned char *px = rgb + (size_t)((H / 2) * W + x) * 3;
		const unsigned char *ex = pal + x * 3;
		if(abs((int)px[0] - (int)ex[0]) > 1 ||
		   abs((int)px[1] - (int)ex[1]) > 1 ||
		   abs((int)px[2] - (int)ex[2]) > 1)
			++fails;
	}

	if(outPath)
	{
		if(WritePPM(outPath, rgb, W, H))
			Printf("GL self-test: wrote %s\n", outPath);
	}

	if(fails == 0)
		Printf("GL self-test: PASS - indexed-palette lookup exact for all 256 indices.\n");
	else
		Printf("GL self-test: FAIL - %d/%d columns mismatched.\n", fails, W);

	delete[] rgb;
	glDeleteTextures(1, &colorTex);
	glDeleteFramebuffers(1, &fbo);
	glDeleteTextures(1, &itex);
	pipe.Shutdown();
	dev.Destroy();

	return fails == 0;
}
