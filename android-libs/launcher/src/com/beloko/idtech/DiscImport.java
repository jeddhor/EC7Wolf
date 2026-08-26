package com.beloko.idtech;

import android.content.ContentResolver;
import android.net.Uri;
import android.util.Log;

import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.Collections;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import android.os.ParcelFileDescriptor;

/**
 * Taking a Corridor 7 disc image apart, on the device.
 *
 * A player is far more likely to have a .cue and a .bin than a folder of
 * already-extracted files -- the game's own installer leaves the cinematics on
 * the disc, and nothing at all puts the soundtrack on a hard drive. This reads
 * the image directly:
 *
 *   * the data track is MODE1/2352 -- 16 bytes of header, 2048 of data, 288 of
 *     error correction -- and underneath that is an ISO 9660 filesystem, walked
 *     here in plain Java because isoinfo lists this disc and then extracts
 *     nothing from it (see tools/extract_c7_video.py, which had to do the same);
 *   * the audio tracks are already raw CD audio, 16-bit little-endian stereo at
 *     44.1 kHz, so ripping them is a byte copy and the only real work is
 *     encoding.
 *
 * Nothing is copied to get at it: a content:// URI opened as a file descriptor
 * seeks, so a 316 MB image is read in place.
 */
public class DiscImport
{
	private static final String LOG = "DiscImport";

	private static final int RAW_SECTOR = 2352;   // MODE1/2352 and audio
	private static final int USER_DATA = 2048;    // the part of it that is data
	private static final int MODE1_OFFSET = 16;   // sync + header before the data
	private static final int PVD_LBA = 16;        // ISO 9660 puts it here

	/** Only the odd-numbered tracks are music; see the CD audio notes. */
	private static final int[] MUSIC_TRACKS = { 3, 5, 7, 9 };

	/** libvorbis VBR quality. Transparent for this material, ~7 MB a track. */
	private static final float QUALITY = 0.4f;

	/**
	 * A source of independent readers over the same image.
	 *
	 * The soundtrack is encoded on several threads at once, and a FileChannel
	 * has one shared position -- so each worker needs its own handle rather than
	 * a borrowed one.
	 */
	public interface ImageSource
	{
		Reader open() throws IOException;
	}

	/** One reader, and whatever has to be closed to let go of it. */
	public static class Reader implements java.io.Closeable
	{
		public FileChannel channel;
		private final java.io.Closeable[] toClose;

		Reader(FileChannel channel, java.io.Closeable... toClose)
		{
			this.channel = channel;
			this.toClose = toClose;
		}

		@Override public void close()
		{
			for (java.io.Closeable c : toClose)
			{
				try { c.close(); } catch (IOException ignored) {}
			}
		}
	}

	public static class Track
	{
		public int number;
		public String mode;     // "MODE1/2352", "AUDIO", ...
		public long startSector;
		public boolean isAudio() { return mode != null && mode.startsWith("AUDIO"); }
	}

	/** What a cue sheet says: the image it names, and the tracks on it. */
	public static class Cue
	{
		public String binName;
		public final List<Track> tracks = new ArrayList<Track>();
	}

	private static final Pattern FILE_LINE =
		Pattern.compile("^\\s*FILE\\s+\"(.+)\"", Pattern.CASE_INSENSITIVE);
	private static final Pattern TRACK_LINE =
		Pattern.compile("^\\s*TRACK\\s+(\\d+)\\s+(\\S+)", Pattern.CASE_INSENSITIVE);
	private static final Pattern INDEX_LINE =
		Pattern.compile("^\\s*INDEX\\s+0*1\\s+(\\d+):(\\d+):(\\d+)", Pattern.CASE_INSENSITIVE);

	/**
	 * INDEX 01 is where a track's content starts. INDEX 00 and PREGAP describe
	 * the gap before it and are not part of it.
	 */
	public static Cue parseCue(String text)
	{
		Cue cue = new Cue();
		Track current = null;
		for (String line : text.split("\r?\n"))
		{
			Matcher m = FILE_LINE.matcher(line);
			if (m.find()) { cue.binName = m.group(1); continue; }

			m = TRACK_LINE.matcher(line);
			if (m.find())
			{
				current = new Track();
				current.number = Integer.parseInt(m.group(1));
				current.mode = m.group(2).toUpperCase(Locale.US);
				continue;
			}

			m = INDEX_LINE.matcher(line);
			if (m.find() && current != null)
			{
				final long mm = Long.parseLong(m.group(1));
				final long ss = Long.parseLong(m.group(2));
				final long ff = Long.parseLong(m.group(3));
				current.startSector = (mm * 60 + ss) * 75 + ff;
				cue.tracks.add(current);
				current = null;
			}
		}
		return cue;
	}

	/** How many raw sectors to pull in one read when copying a file out. */
	private static final int READ_SECTORS = 64;

	/** Reused across the whole rip: one seek and one allocation per sector adds up. */
	private static final ThreadLocal<ByteBuffer> SCRATCH = new ThreadLocal<ByteBuffer>()
	{
		@Override protected ByteBuffer initialValue()
		{
			return ByteBuffer.allocate(RAW_SECTOR * READ_SECTORS);
		}
	};

	/** Fill buf with count raw sectors starting at lba. */
	private static boolean readRaw(FileChannel ch, long lba, ByteBuffer buf, int count)
		throws IOException
	{
		final int want = count * RAW_SECTOR;
		buf.clear();
		buf.limit(want);
		ch.position(lba * RAW_SECTOR);
		int got = 0;
		while (got < want)
		{
			final int n = ch.read(buf);
			if (n < 0) return false;
			got += n;
		}
		return true;
	}

	/** One MODE1/2352 sector's 2048 bytes of user data. */
	private static boolean readDataSector(FileChannel ch, long lba, byte[] out) throws IOException
	{
		final ByteBuffer buf = SCRATCH.get();
		if (!readRaw(ch, lba, buf, 1))
			return false;
		System.arraycopy(buf.array(), MODE1_OFFSET, out, 0, USER_DATA);
		return true;
	}

	private static int le16(byte[] b, int o)
	{
		return (b[o] & 0xFF) | ((b[o + 1] & 0xFF) << 8);
	}

	private static long le32(byte[] b, int o)
	{
		return (b[o] & 0xFFL) | ((b[o + 1] & 0xFFL) << 8)
			| ((b[o + 2] & 0xFFL) << 16) | ((b[o + 3] & 0xFFL) << 24);
	}

	/** A file found on the disc: where it starts, and how long it is. */
	private static class Entry
	{
		String name;
		long lba;
		long size;
		boolean directory;
	}

	/**
	 * Read one ISO 9660 directory extent into a list of entries.
	 *
	 * Names carry a ";1" version suffix which is stripped here, because nobody
	 * outside the standard writes MAPTEMP.CO7;1.
	 */
	private static List<Entry> readDirectory(FileChannel ch, long lba, long size) throws IOException
	{
		final List<Entry> entries = new ArrayList<Entry>();
		final byte[] sector = new byte[USER_DATA];
		final long sectors = (size + USER_DATA - 1) / USER_DATA;

		for (long s = 0; s < sectors; ++s)
		{
			if (!readDataSector(ch, lba + s, sector))
				break;
			int off = 0;
			while (off < USER_DATA)
			{
				final int len = sector[off] & 0xFF;
				if (len == 0)
					break;              // padding to the end of this sector
				if (off + len > USER_DATA)
					break;

				final Entry e = new Entry();
				e.lba = le32(sector, off + 2);
				e.size = le32(sector, off + 10);
				e.directory = (sector[off + 25] & 0x02) != 0;
				final int nameLen = sector[off + 32] & 0xFF;
				if (nameLen > 0 && off + 33 + nameLen <= USER_DATA)
				{
					String name = new String(sector, off + 33, nameLen, "ISO-8859-1");
					final int semi = name.indexOf(';');
					if (semi >= 0) name = name.substring(0, semi);
					e.name = name;
					// "\0" and "\1" are . and .. and are not interesting.
					if (nameLen > 1 || (sector[off + 33] != 0 && sector[off + 33] != 1))
						entries.add(e);
				}
				off += len;
			}
		}
		return entries;
	}

	/** Every file on the disc, one directory level at a time, depth-limited. */
	private static void collect(FileChannel ch, long lba, long size, int depth,
		List<Entry> out) throws IOException
	{
		if (depth > 4)
			return;
		for (Entry e : readDirectory(ch, lba, size))
		{
			if (e.directory)
				collect(ch, e.lba, e.size, depth + 1, out);
			else
				out.add(e);
		}
	}

	/** Copy a file off the data track by sector, into gameDir. */
	private static void extract(FileChannel ch, Entry e, File dest) throws IOException
	{
		final File tmp = new File(dest.getParentFile(), dest.getName() + ".part");
		final OutputStream out = new BufferedOutputStream(new FileOutputStream(tmp), 1 << 20);
		try
		{
			// Sixty-four sectors a time rather than one. Every sector used to
			// cost a seek, a read and a fresh 2352-byte buffer, and the largest
			// file on this disc is 21.7 MB -- about ten thousand of each.
			final ByteBuffer buf = SCRATCH.get();
			long left = e.size;
			long lba = e.lba;
			while (left > 0)
			{
				final int sectors = (int)Math.min((long)READ_SECTORS,
					(left + USER_DATA - 1) / USER_DATA);
				if (!readRaw(ch, lba, buf, sectors))
					throw new IOException("the image ends inside " + e.name);
				final byte[] raw = buf.array();
				for (int s = 0; s < sectors && left > 0; ++s)
				{
					final int n = (int)Math.min((long)USER_DATA, left);
					out.write(raw, s * RAW_SECTOR + MODE1_OFFSET, n);
					left -= n;
				}
				lba += sectors;
			}
		}
		finally
		{
			out.close();
		}
		if (dest.exists() && !dest.delete())
		{
			tmp.delete();
			throw new IOException("could not replace " + dest.getName());
		}
		if (!tmp.renameTo(dest))
		{
			tmp.delete();
			throw new IOException("could not write " + dest.getName());
		}
	}

	/**
	 * Encode one audio track straight out of the image.
	 *
	 * The track runs from its own INDEX 01 to the next track's, or to the end
	 * of the file for the last one.
	 */
	private static void ripAudio(FileChannel ch, long startSector, long endSector,
		File dest, GameDataImport.Listener listener) throws IOException
	{
		final long sectors = endSector - startSector;
		if (sectors <= 0)
			throw new IOException("track has no length");

		final File tmp = new File(dest.getParentFile(), dest.getName() + ".part");
		final VorbisEncoder enc = new VorbisEncoder(tmp.getAbsolutePath(), 44100, 2, QUALITY);
		try
		{
			// A second of audio at a time: big enough that the JNI crossing is
			// noise, small enough not to matter if the import is cancelled.
			final int chunkSectors = 75;
			final byte[] buf = new byte[RAW_SECTOR * chunkSectors];
			final ByteBuffer bb = ByteBuffer.wrap(buf);

			ch.position(startSector * RAW_SECTOR);
			long done = 0;
			while (done < sectors)
			{
				final int want = (int)Math.min((long)chunkSectors, sectors - done);
				bb.clear();
				bb.limit(want * RAW_SECTOR);
				int got = 0;
				while (got < want * RAW_SECTOR)
				{
					final int n = ch.read(bb);
					if (n < 0) break;
					got += n;
				}
				if (got <= 0)
					break;
				enc.write(buf, got);
				done += want;

				if (listener != null && (done % (chunkSectors * 20)) == 0)
					listener.onProgress(dest.getName() + " "
						+ (done * 100 / sectors) + "%");
			}
		}
		finally
		{
			enc.close();
		}

		if (dest.exists() && !dest.delete())
		{
			tmp.delete();
			throw new IOException("could not replace " + dest.getName());
		}
		if (!tmp.renameTo(dest))
		{
			tmp.delete();
			throw new IOException("could not write " + dest.getName());
		}
	}

	/**
	 * Rip everything worth having off a disc image.
	 *
	 * @return how many files were produced.
	 */
	public static int rip(ContentResolver resolver, Uri cueUri, Uri binUri, File gameDir,
		GameDataImport.Listener listener) throws IOException
	{
		String cueText;
		InputStream cueIn = resolver.openInputStream(cueUri);
		if (cueIn == null)
			throw new IOException("could not read the cue sheet");
		try
		{
			final byte[] all = new byte[64 * 1024];
			final int n = Math.max(0, cueIn.read(all));
			cueText = new String(all, 0, n, "ISO-8859-1");
		}
		finally { cueIn.close(); }

		return ripSource(new ImageSource() {
			public Reader open() throws IOException
			{
				final ParcelFileDescriptor pfd = resolver.openFileDescriptor(binUri, "r");
				if (pfd == null)
					throw new IOException("could not open the disc image");
				final FileInputStream fis = new FileInputStream(pfd.getFileDescriptor());
				return new Reader(fis.getChannel(), fis, pfd);
			}
		}, cueText, gameDir, listener);
	}

	/**
	 * The same thing from ordinary files, which is what a disc image inside a
	 * zip becomes once it has been unpacked.
	 */
	public static int ripFiles(File cueFile, File binFile, File gameDir,
		GameDataImport.Listener listener) throws IOException
	{
		final byte[] all = new byte[64 * 1024];
		int n;
		final FileInputStream cueIn = new FileInputStream(cueFile);
		try { n = Math.max(0, cueIn.read(all)); }
		finally { cueIn.close(); }

		return ripSource(new ImageSource() {
			public Reader open() throws IOException
			{
				final FileInputStream fis = new FileInputStream(binFile);
				return new Reader(fis.getChannel(), fis);
			}
		}, new String(all, 0, n, "ISO-8859-1"), gameDir, listener);
	}

	private static int ripSource(ImageSource source, String cueText, File gameDir,
		GameDataImport.Listener listener) throws IOException
	{
		final Cue cue = parseCue(cueText);
		if (cue.tracks.isEmpty())
			throw new IOException("the cue sheet lists no tracks");

		int produced = 0;
		final Reader reader = source.open();
		final FileChannel ch = reader.channel;
		try
		{
			final long imageSectors = ch.size() / RAW_SECTOR;

			// --- the data track ---------------------------------------------
			final long tStart = android.os.SystemClock.elapsedRealtime();
			if (listener != null) listener.onProgress("Reading the disc");
			final byte[] pvd = new byte[USER_DATA];
			if (!readDataSector(ch, PVD_LBA, pvd))
				throw new IOException("no primary volume descriptor; is this a MODE1/2352 image?");
			if (!(pvd[1] == 'C' && pvd[2] == 'D' && pvd[3] == '0' && pvd[4] == '0' && pvd[5] == '1'))
				throw new IOException("this does not look like an ISO 9660 disc");

			// The root directory record sits at offset 156 of the PVD.
			final long rootLba = le32(pvd, 156 + 2);
			final long rootSize = le32(pvd, 156 + 10);

			final List<Entry> files = new ArrayList<Entry>();
			collect(ch, rootLba, rootSize, 0, files);

			for (Entry e : files)
			{
				final String sub = GameDataImport.destinationFor(e.name);
				if (sub == null)
					continue;
				if (listener != null) listener.onProgress("Extracting " + e.name);
				final File dir = sub.length() == 0 ? gameDir : new File(gameDir, sub);
				if (!dir.exists()) dir.mkdirs();
				extract(ch, e, new File(dir, GameDataImport.canonical(e.name)));
				++produced;
			}

			Log.i(LOG, "data track extracted in "
				+ (android.os.SystemClock.elapsedRealtime() - tStart) + " ms");

			// --- the soundtrack ---------------------------------------------
			if (!VorbisEncoder.isAvailable())
			{
				Log.w(LOG, "no Vorbis encoder; the game data is in but the music is not");
				return produced;
			}

			final File cdaudio = new File(gameDir, "cdaudio");
			if (!cdaudio.exists()) cdaudio.mkdirs();

			// All four at once.
			//
			// Encoding is 77% of a disc import -- 41 of 54 seconds measured on a
			// Tab S5e -- and the four tracks have nothing to do with each other.
			// Each worker opens its own reader over the image, because a
			// FileChannel has a single shared position and sharing one would
			// have them seeking over each other.
			final List<Runnable> jobs = new ArrayList<Runnable>();
			final List<File> wrote = Collections.synchronizedList(new ArrayList<File>());
			final AtomicReference<IOException> failure = new AtomicReference<IOException>();
			final AtomicInteger done = new AtomicInteger();

			for (int wanted : MUSIC_TRACKS)
			{
				Track track = null;
				long end = imageSectors;
				for (int i = 0; i < cue.tracks.size(); ++i)
				{
					final Track t = cue.tracks.get(i);
					if (t.number != wanted) continue;
					track = t;
					if (i + 1 < cue.tracks.size())
						end = cue.tracks.get(i + 1).startSector;
					break;
				}
				if (track == null || !track.isAudio())
					continue;

				final File dest = new File(cdaudio,
					String.format(Locale.US, "track%02d.ogg", wanted));
				final long from = track.startSector, to = end;
				final int number = wanted;
				jobs.add(new Runnable() {
					public void run()
					{
						Reader mine = null;
						try
						{
							mine = source.open();
							final long t0 = android.os.SystemClock.elapsedRealtime();
							// No per-track percentage: four of them reporting
							// into one line reads as noise.
							ripAudio(mine.channel, from, to, dest, null);
							Log.i(LOG, "track " + number + " encoded in "
								+ (android.os.SystemClock.elapsedRealtime() - t0) + " ms");
							wrote.add(dest);
						}
						catch (IOException e)
						{
							failure.compareAndSet(null, e);
						}
						catch (RuntimeException e)
						{
							failure.compareAndSet(null, new IOException(e.getMessage()));
						}
						finally
						{
							if (mine != null) mine.close();
							if (listener != null)
								listener.onProgress("Encoding the soundtrack ("
									+ done.incrementAndGet() + " of " + jobs.size() + " done)");
						}
					}
				});
			}

			if (!jobs.isEmpty())
			{
				if (listener != null)
					listener.onProgress("Encoding the soundtrack (0 of " + jobs.size() + " done)");
				// Bounded by the cores that are actually there; four encoders on
				// a two-big-core phone would only queue behind each other.
				final int threads = Math.min(jobs.size(),
					Math.max(1, Runtime.getRuntime().availableProcessors()));
				final ExecutorService pool = Executors.newFixedThreadPool(threads);
				try
				{
					for (Runnable job : jobs)
						pool.execute(job);
					pool.shutdown();
					pool.awaitTermination(2, TimeUnit.HOURS);
				}
				catch (InterruptedException e)
				{
					pool.shutdownNow();
					Thread.currentThread().interrupt();
					throw new IOException("the import was interrupted");
				}

				final IOException bad = failure.get();
				if (bad != null)
					throw bad;
				produced += wrote.size();
			}
		}
		finally
		{
			reader.close();
		}
		return produced;
	}
}
