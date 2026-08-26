package com.beloko.idtech;

import android.util.Log;

import java.io.Closeable;
import java.io.IOException;

/**
 * Ogg Vorbis encoding, in libvorbis, reached through libc7rip.
 *
 * Written as a stream so a track never has to exist as raw PCM anywhere: the
 * longest piece of music on the Corridor 7 disc is 636 seconds, which is 112 MB
 * of samples for a file that ends up nearer 7 MB.
 */
public class VorbisEncoder implements Closeable
{
	private static final String LOG = "VorbisEncoder";
	private static boolean loaded;
	private static boolean available;

	private long handle;

	private static native long nativeOpen(String path, int rate, int channels, float quality);
	private static native boolean nativeWrite(long handle, byte[] pcm, int length);
	private static native boolean nativeClose(long handle);

	/** False when the encoder library is missing; the caller can then fall back. */
	public static synchronized boolean isAvailable()
	{
		if (!loaded)
		{
			loaded = true;
			try
			{
				System.loadLibrary("c7rip");
				available = true;
			}
			catch (UnsatisfiedLinkError e)
			{
				Log.e(LOG, "libc7rip is missing; cannot encode Vorbis", e);
				available = false;
			}
		}
		return available;
	}

	/**
	 * @param quality libvorbis VBR quality, -0.1 to 1.0. 0.4 is roughly the
	 *                "-q 4" most rippers default to and is transparent for
	 *                1994 CD audio.
	 */
	public VorbisEncoder(String path, int rate, int channels, float quality) throws IOException
	{
		if (!isAvailable())
			throw new IOException("the Vorbis encoder is not available");
		handle = nativeOpen(path, rate, channels, quality);
		if (handle == 0)
			throw new IOException("could not start encoding " + path);
	}

	/** Interleaved signed 16-bit little-endian, which is what CD audio is. */
	public void write(byte[] pcm, int length) throws IOException
	{
		if (handle == 0)
			throw new IOException("encoder is closed");
		if (!nativeWrite(handle, pcm, length))
		{
			close();
			throw new IOException("encoding failed");
		}
	}

	@Override
	public void close() throws IOException
	{
		if (handle == 0)
			return;
		final long h = handle;
		handle = 0;
		if (!nativeClose(h))
			throw new IOException("the encoded file did not finish cleanly");
	}
}
