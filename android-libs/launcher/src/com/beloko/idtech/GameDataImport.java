package com.beloko.idtech;

import android.content.ContentResolver;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Getting Corridor 7 onto the phone without developer tools.
 *
 * The game's files cannot ship in the APK -- they are commercial -- so the
 * player has to supply them, and "push them with adb" is not an answer for
 * anybody who is not us. Since Android 11 the app's own external directory is
 * also invisible to file managers and to MTP, so "copy them into the folder"
 * is not an answer either. That leaves the Storage Access Framework: the
 * player points at a folder or a zip once, and this copies what it needs into
 * app-specific storage, which needs no permission at any targetSdk.
 *
 * The file names come from wl_iwad.cpp rather than from a wiki: the loader
 * accepts gamemaps OR maptemp, and MAPTEMP's TED5 signature stands in for
 * MAPHEAD, which is why there is no MAPHEAD.CO7 in the required list and why
 * an install that looks short is actually complete.
 */
public class GameDataImport
{
	/**
	 * What the engine refuses to start without.
	 *
	 * CORR7CD.EXE is in this list and it is not a mistake. Corridor 7 keeps its
	 * palette inside its own executable -- file_vswap.cpp reads C7PAL out of it
	 * at offset 0x2FFC0 -- and the iwad definition lists C7PAL in MustContain.
	 * Import the seven data files without the executable and the launcher says
	 * the data is present, the engine finds no C7PAL, rejects the whole install
	 * and reports "Can not find base game data", which names five extensions
	 * that have nothing to do with Corridor 7. It is a miserable thing to debug
	 * from the message alone.
	 */
	public static final String[] REQUIRED = {
		"AUDIOHED.CO7", "AUDIOT.CO7", "MAPTEMP.CO7",
		"VGADICT.CO7", "VGAHEAD.CO7", "VGAGRAPH.CO7", "GFXTILES.CO7",
		"CORR7CD.EXE"
	};

	/**
	 * The palette is read from a fixed offset and only trusted when the file is
	 * exactly this long, so a different build of the executable imports fine and
	 * then fails the same unhelpful way. Checked so it can be said out loud.
	 */
	public static final long EXECUTABLE_SIZE = 250776;

	/**
	 * Taken when offered, never demanded. AUDIOMUS is the digitized speech and
	 * effects: the game starts without it and sounds wrong.
	 */
	public static final String[] OPTIONAL = { "AUDIOMUS.CO7", "GFXINFOV.CO7" };

	/**
	 * The three animations the installer leaves on the CD, so they are in
	 * nobody's installed game directory. They live in a subdirectory of their
	 * own because that is where the engine looks for them.
	 */
	public static final String[] VIDEO = { "SEQONE.CO7", "SEQTHREE.CO7", "SEQFOUR.CO7" };

	/** Progress for a UI that would otherwise sit still for twenty seconds. */
	public interface Listener
	{
		void onProgress(String message);
	}

	/** Which subdirectory a file belongs in, or null if we do not want it. */
	static String destinationFor(String name)
	{
		String upper = name.toUpperCase(Locale.US);
		for(int i = 0; i < REQUIRED.length; ++i)
			if(REQUIRED[i].equals(upper)) return "";
		for(int i = 0; i < OPTIONAL.length; ++i)
			if(OPTIONAL[i].equals(upper)) return "";
		for(int i = 0; i < VIDEO.length; ++i)
			if(VIDEO[i].equals(upper)) return "video";
		// The ripped CD soundtrack: track03.ogg and friends, by physical track
		// number. Only the odd ones are music, but taking whatever is offered
		// costs nothing and the engine ignores the rest.
		if(upper.matches("TRACK[0-9][0-9]\\.OGG")) return "cdaudio";
		return null;
	}

	/** Canonical upper-case name, so an import from a lower-case zip is tidy. */
	static String canonical(String name)
	{
		return name.toUpperCase(Locale.US).endsWith(".OGG")
			? name.toLowerCase(Locale.US) : name.toUpperCase(Locale.US);
	}

	/**
	 * Non-null when the executable is there but is not the build the palette
	 * offset was measured against.
	 */
	public static String wrongExecutable(File gameDir)
	{
		File exe = new File(gameDir, "CORR7CD.EXE");
		if(!exe.isFile() || exe.length() == EXECUTABLE_SIZE)
			return null;
		return "CORR7CD.EXE is " + exe.length() + " bytes, not " + EXECUTABLE_SIZE
			+ ". Corridor 7 keeps its palette inside the executable and this is "
			+ "not the CD build, so the game will not start.";
	}

	/** The required files not present in gameDir, or null when none are. */
	public static String missing(File gameDir)
	{
		StringBuilder sb = new StringBuilder();
		for(int i = 0; i < REQUIRED.length; ++i)
		{
			if(!existsInsensitive(gameDir, REQUIRED[i]))
			{
				if(sb.length() > 0) sb.append(", ");
				sb.append(REQUIRED[i]);
			}
		}
		return sb.length() > 0 ? sb.toString() : null;
	}

	private static boolean existsInsensitive(File dir, String name)
	{
		String[] entries = dir.list();
		if(entries == null) return false;
		for(int i = 0; i < entries.length; ++i)
			if(entries[i].equalsIgnoreCase(name)) return true;
		return false;
	}

	/** Copy the game files out of a zip the player picked. */
	public static int importFromZip(ContentResolver resolver, Uri zip, File gameDir,
		Listener listener) throws IOException
	{
		InputStream raw = resolver.openInputStream(zip);
		if(raw == null) throw new IOException("could not open the archive");

		int copied = 0;
		ZipInputStream in = new ZipInputStream(raw);
		try
		{
			ZipEntry entry;
			while((entry = in.getNextEntry()) != null)
			{
				if(entry.isDirectory()) continue;
				// Match on the base name: the files are usually one directory
				// down inside the archive, and we do not care what it is called.
				String name = new File(entry.getName()).getName();
				String sub = destinationFor(name);
				if(sub == null) continue;

				if(listener != null) listener.onProgress(name);
				writeTo(in, new File(subDir(gameDir, sub), canonical(name)));
				++copied;
			}
		}
		finally
		{
			try { in.close(); } catch(IOException ignored) {}
		}
		return copied;
	}

	/**
	 * Copy the game files out of a folder the player picked.
	 *
	 * If that folder holds a disc image rather than loose files, the image is
	 * taken apart instead -- which is the more likely case, because the game's
	 * installer leaves the cinematics on the CD and nothing at all copies the
	 * soundtrack off it. A .cue names its .bin as a sibling, which is why this
	 * wants a folder: a single-document URI cannot see siblings.
	 */
	public static int importFromTree(ContentResolver resolver, Uri tree, File gameDir,
		Listener listener) throws IOException
	{
		final Uri[] pair = findDiscImage(resolver, tree,
			DocumentsContract.getTreeDocumentId(tree), 0);
		if(pair != null)
			return DiscImport.rip(resolver, pair[0], pair[1], gameDir, listener);

		return walk(resolver, tree, DocumentsContract.getTreeDocumentId(tree),
			gameDir, listener, 0);
	}

	/**
	 * Look for a cue sheet and the image it names, in the same directory.
	 *
	 * @return { cue, bin } or null. The bin is matched by the name inside the
	 *         cue rather than by extension, because a cue can name anything and
	 *         a folder can hold more than one image.
	 */
	private static Uri[] findDiscImage(ContentResolver resolver, Uri tree,
		String documentId, int depth)
	{
		if(depth > 3)
			return null;

		Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, documentId);
		Cursor c = resolver.query(children, new String[] {
			DocumentsContract.Document.COLUMN_DOCUMENT_ID,
			DocumentsContract.Document.COLUMN_DISPLAY_NAME,
			DocumentsContract.Document.COLUMN_MIME_TYPE }, null, null, null);
		if(c == null)
			return null;

		final List<String> subdirs = new ArrayList<String>();
		String cueId = null, cueName = null;
		final java.util.HashMap<String, String> here = new java.util.HashMap<String, String>();
		try
		{
			while(c.moveToNext())
			{
				final String id = c.getString(0);
				final String name = c.getString(1);
				final String mime = c.getString(2);
				if(DocumentsContract.Document.MIME_TYPE_DIR.equals(mime))
				{
					subdirs.add(id);
					continue;
				}
				here.put(name.toLowerCase(Locale.US), id);
				if(cueId == null && name.toLowerCase(Locale.US).endsWith(".cue"))
				{
					cueId = id;
					cueName = name;
				}
			}
		}
		finally
		{
			c.close();
		}

		if(cueId != null)
		{
			final String bin = binNamedBy(resolver,
				DocumentsContract.buildDocumentUriUsingTree(tree, cueId));
			if(bin != null)
			{
				final String binId = here.get(bin.toLowerCase(Locale.US));
				if(binId != null)
					return new Uri[] {
						DocumentsContract.buildDocumentUriUsingTree(tree, cueId),
						DocumentsContract.buildDocumentUriUsingTree(tree, binId) };
			}
			// A cue whose image is missing is worth saying so about rather than
			// quietly falling back to copying loose files that are not there.
			android.util.Log.w("GameDataImport",
				"found " + cueName + " but not the image it names");
		}

		for(String id : subdirs)
		{
			final Uri[] found = findDiscImage(resolver, tree, id, depth + 1);
			if(found != null)
				return found;
		}
		return null;
	}

	/** The FILE line of a cue sheet, which is the image beside it. */
	private static String binNamedBy(ContentResolver resolver, Uri cue)
	{
		try
		{
			InputStream in = resolver.openInputStream(cue);
			if(in == null)
				return null;
			try
			{
				final byte[] buf = new byte[8192];
				final int n = Math.max(0, in.read(buf));
				final DiscImport.Cue parsed =
					DiscImport.parseCue(new String(buf, 0, n, "ISO-8859-1"));
				return parsed.binName;
			}
			finally { in.close(); }
		}
		catch(IOException e)
		{
			return null;
		}
	}

	/**
	 * The player may point at the folder holding the files or at its parent --
	 * a disc is usually unpacked into a directory of its own -- so this
	 * descends. The depth limit is there because a tree URI can be granted on
	 * something enormous, like the whole of Downloads.
	 */
	private static int walk(ContentResolver resolver, Uri tree, String documentId,
		File gameDir, Listener listener, int depth) throws IOException
	{
		if(depth > 3) return 0;

		Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, documentId);
		Cursor c = resolver.query(children, new String[] {
			DocumentsContract.Document.COLUMN_DOCUMENT_ID,
			DocumentsContract.Document.COLUMN_DISPLAY_NAME,
			DocumentsContract.Document.COLUMN_MIME_TYPE }, null, null, null);
		if(c == null) return 0;

		int copied = 0;
		try
		{
			while(c.moveToNext())
			{
				String childId = c.getString(0);
				String name = c.getString(1);
				String mime = c.getString(2);

				if(DocumentsContract.Document.MIME_TYPE_DIR.equals(mime))
				{
					copied += walk(resolver, tree, childId, gameDir, listener, depth + 1);
					continue;
				}

				String sub = destinationFor(name);
				if(sub == null) continue;

				if(listener != null) listener.onProgress(name);
				Uri file = DocumentsContract.buildDocumentUriUsingTree(tree, childId);
				InputStream in = resolver.openInputStream(file);
				if(in == null) continue;
				try { writeTo(in, new File(subDir(gameDir, sub), canonical(name))); }
				finally { try { in.close(); } catch(IOException ignored) {} }
				++copied;
			}
		}
		finally
		{
			c.close();
		}
		return copied;
	}

	private static File subDir(File gameDir, String sub)
	{
		File dir = sub.length() == 0 ? gameDir : new File(gameDir, sub);
		if(!dir.exists()) dir.mkdirs();
		return dir;
	}

	/**
	 * Written to a temporary name and moved into place, so that an import
	 * interrupted halfway -- the player backing out, the process being killed
	 * -- cannot leave a half-copied MAPTEMP that looks present and is not.
	 */
	private static void writeTo(InputStream in, File dest) throws IOException
	{
		File tmp = new File(dest.getParentFile(), dest.getName() + ".part");
		OutputStream out = new FileOutputStream(tmp);
		try
		{
			byte[] buffer = new byte[64 * 1024];
			int n;
			while((n = in.read(buffer)) > 0)
				out.write(buffer, 0, n);
		}
		finally
		{
			try { out.close(); } catch(IOException ignored) {}
		}

		if(dest.exists() && !dest.delete())
		{
			tmp.delete();
			throw new IOException("could not replace " + dest.getName());
		}
		if(!tmp.renameTo(dest))
		{
			tmp.delete();
			throw new IOException("could not write " + dest.getName());
		}
	}

	/** Names of everything importable, for a message that tells the truth. */
	public static List<String> wantedNames()
	{
		List<String> all = new ArrayList<String>();
		for(int i = 0; i < REQUIRED.length; ++i) all.add(REQUIRED[i]);
		for(int i = 0; i < OPTIONAL.length; ++i) all.add(OPTIONAL[i]);
		return all;
	}
}
