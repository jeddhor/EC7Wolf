/*
** c7rip.c
**
** Ogg Vorbis encoding for the disc importer, and nothing else.
**
** The importer is Java: it reads the cue sheet, walks ISO 9660 on the data
** track and pulls raw CD audio out of the image, all of which is arithmetic
** over a stream. Encoding is the one part Java has no answer for -- this
** project's SDL_mixer decodes Ogg with stb_vorbis, which cannot write one.
**
** The interface is a stream rather than a file-to-file call so that the
** importer never has to land a whole track as raw PCM first: the longest music
** track on the Corridor 7 disc is 636 seconds, which is 112 MB of PCM for a
** file that ends up around 7 MB.
*/

#include <jni.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <android/log.h>

#include <vorbis/vorbisenc.h>

#define LOG(...) ((void)__android_log_print(ANDROID_LOG_INFO, "c7rip", __VA_ARGS__))
#define LOGE(...) ((void)__android_log_print(ANDROID_LOG_ERROR, "c7rip", __VA_ARGS__))

typedef struct
{
	FILE            *out;
	ogg_stream_state os;
	vorbis_info      vi;
	vorbis_comment   vc;
	vorbis_dsp_state vd;
	vorbis_block     vb;
	int              channels;
	int              ok;
} Encoder;

/* Drain whatever the encoder has ready and write it to the file. */
static int FlushPages(Encoder *e)
{
	ogg_page og;
	while(vorbis_analysis_blockout(&e->vd, &e->vb) == 1)
	{
		vorbis_analysis(&e->vb, NULL);
		vorbis_bitrate_addblock(&e->vb);

		ogg_packet op;
		while(vorbis_bitrate_flushpacket(&e->vd, &op))
		{
			ogg_stream_packetin(&e->os, &op);
			while(ogg_stream_pageout(&e->os, &og))
			{
				if(fwrite(og.header, 1, (size_t)og.header_len, e->out) != (size_t)og.header_len ||
					fwrite(og.body, 1, (size_t)og.body_len, e->out) != (size_t)og.body_len)
					return 0;
			}
		}
	}
	return 1;
}

JNIEXPORT jlong JNICALL
Java_com_beloko_idtech_VorbisEncoder_nativeOpen(JNIEnv *env, jclass cls,
	jstring path, jint rate, jint channels, jfloat quality)
{
	(void)cls;
	const char *cpath = (*env)->GetStringUTFChars(env, path, NULL);
	if(cpath == NULL)
		return 0;

	Encoder *e = (Encoder *)calloc(1, sizeof(Encoder));
	if(e == NULL)
	{
		(*env)->ReleaseStringUTFChars(env, path, cpath);
		return 0;
	}

	e->channels = channels;
	e->out = fopen(cpath, "wb");
	(*env)->ReleaseStringUTFChars(env, path, cpath);
	if(e->out == NULL)
	{
		LOGE("could not open the output file");
		free(e);
		return 0;
	}

	vorbis_info_init(&e->vi);
	if(vorbis_encode_init_vbr(&e->vi, channels, rate, quality) != 0)
	{
		LOGE("vorbis_encode_init_vbr refused %d channels at %d Hz", channels, rate);
		vorbis_info_clear(&e->vi);
		fclose(e->out);
		free(e);
		return 0;
	}

	vorbis_comment_init(&e->vc);
	vorbis_comment_add_tag(&e->vc, "ENCODER", "EC7Wolf");
	vorbis_analysis_init(&e->vd, &e->vi);
	vorbis_block_init(&e->vd, &e->vb);

	/* A fixed serial number is fine: one logical stream per file. */
	ogg_stream_init(&e->os, 0x7C000001);

	ogg_packet header, headerComm, headerCode;
	vorbis_analysis_headerout(&e->vd, &e->vc, &header, &headerComm, &headerCode);
	ogg_stream_packetin(&e->os, &header);
	ogg_stream_packetin(&e->os, &headerComm);
	ogg_stream_packetin(&e->os, &headerCode);

	/* The headers must land in their own page, or a player cannot start
	   decoding until it has read audio it does not need yet. */
	ogg_page og;
	while(ogg_stream_flush(&e->os, &og))
	{
		fwrite(og.header, 1, (size_t)og.header_len, e->out);
		fwrite(og.body, 1, (size_t)og.body_len, e->out);
	}

	e->ok = 1;
	return (jlong)(intptr_t)e;
}

/*
 * pcm is interleaved signed 16-bit little-endian, which is what a CD audio
 * track already is -- the bytes come straight out of the disc image.
 */
JNIEXPORT jboolean JNICALL
Java_com_beloko_idtech_VorbisEncoder_nativeWrite(JNIEnv *env, jclass cls,
	jlong handle, jbyteArray pcm, jint length)
{
	(void)cls;
	Encoder *e = (Encoder *)(intptr_t)handle;
	if(e == NULL || !e->ok)
		return JNI_FALSE;

	const jint frames = length / (2 * e->channels);
	if(frames <= 0)
		return JNI_TRUE;

	jbyte *bytes = (*env)->GetByteArrayElements(env, pcm, NULL);
	if(bytes == NULL)
		return JNI_FALSE;

	float **buffer = vorbis_analysis_buffer(&e->vd, frames);
	const unsigned char *p = (const unsigned char *)bytes;
	for(jint i = 0; i < frames; ++i)
	{
		for(int c = 0; c < e->channels; ++c)
		{
			const int lo = p[(i * e->channels + c) * 2];
			const int hi = (signed char)p[(i * e->channels + c) * 2 + 1];
			buffer[c][i] = (float)((hi << 8) | lo) / 32768.0f;
		}
	}
	vorbis_analysis_wrote(&e->vd, frames);

	(*env)->ReleaseByteArrayElements(env, pcm, bytes, JNI_ABORT);

	if(!FlushPages(e))
	{
		e->ok = 0;
		return JNI_FALSE;
	}
	return JNI_TRUE;
}

JNIEXPORT jboolean JNICALL
Java_com_beloko_idtech_VorbisEncoder_nativeClose(JNIEnv *env, jclass cls, jlong handle)
{
	(void)env; (void)cls;
	Encoder *e = (Encoder *)(intptr_t)handle;
	if(e == NULL)
		return JNI_FALSE;

	int ok = e->ok;
	if(ok)
	{
		/* A zero-length write is how libvorbis is told the stream has ended;
		   without it the last packet never gets its end-of-stream flag and the
		   file is short by up to one block. */
		vorbis_analysis_wrote(&e->vd, 0);
		ok = FlushPages(e);
	}

	ogg_stream_clear(&e->os);
	vorbis_block_clear(&e->vb);
	vorbis_dsp_clear(&e->vd);
	vorbis_comment_clear(&e->vc);
	vorbis_info_clear(&e->vi);
	if(fclose(e->out) != 0)
		ok = 0;
	free(e);
	return ok ? JNI_TRUE : JNI_FALSE;
}
