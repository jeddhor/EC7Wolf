package com.beloko.idtech;

import android.app.Activity;
import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.IntentSender;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.provider.DocumentsContract;
import android.provider.MediaStore;
import android.util.Log;

import java.util.ArrayList;
import java.util.Collections;

/**
 * Offering to remove what was imported from.
 *
 * A disc image is a third of a gigabyte and a game archive is fifty megabytes,
 * and once the files are in app storage neither is needed again. Leaving them
 * in Downloads is leaving somebody's tablet worse than we found it -- and the
 * one this was built on was 98% full.
 *
 * Deleting is not simply File.delete(): the app did not create these files and
 * does not own them. Which door to knock on depends on where the URI came from.
 */
public class ImportCleanup
{
	private static final String LOG = "ImportCleanup";

	/** The request code the delete confirmation comes back on. */
	public static final int REQUEST_DELETE = 4211;

	/** It is gone. */
	public static final int DELETED = 0;
	/** The system is asking the player; the answer arrives in onActivityResult. */
	public static final int ASKED = 1;
	/** Android would not allow it, and nobody is being asked. */
	public static final int REFUSED = 2;

	/** A human-readable name for a content URI, for asking before deleting. */
	public static String displayName(ContentResolver resolver, Uri uri)
	{
		if (uri == null)
			return null;
		final String[] columns = { android.provider.OpenableColumns.DISPLAY_NAME };
		Cursor c = null;
		try
		{
			c = resolver.query(uri, columns, null, null, null);
			if (c != null && c.moveToFirst())
				return c.getString(0);
		}
		catch (Exception e)
		{
			Log.w(LOG, "could not name " + uri, e);
		}
		finally
		{
			if (c != null) c.close();
		}
		final String last = uri.getLastPathSegment();
		return last != null ? last : uri.toString();
	}

	/** Bytes behind a content URI, or 0 when it will not say. */
	public static long sizeOf(ContentResolver resolver, Uri uri)
	{
		if (uri == null)
			return 0;
		final String[] columns = { android.provider.OpenableColumns.SIZE };
		Cursor c = null;
		try
		{
			c = resolver.query(uri, columns, null, null, null);
			if (c != null && c.moveToFirst() && !c.isNull(0))
				return c.getLong(0);
		}
		catch (Exception e)
		{
			Log.w(LOG, "could not size " + uri, e);
		}
		finally
		{
			if (c != null) c.close();
		}
		return 0;
	}

	/**
	 * Delete what was imported from.
	 *
	 * Three cases, and the difference matters:
	 *
	 *  * A document from the Storage Access Framework picker -- the app holds a
	 *    grant for it and can delete it outright.
	 *  * A MediaStore item on Android 11 or later -- the app does not own it, so
	 *    the system asks the player itself. That system prompt *is* the
	 *    confirmation; this is why the caller's own dialog only offers, and does
	 *    not promise.
	 *  * Anything older, where a plain delete through the resolver is allowed.
	 *
	 * Android 11 and later will not let an app delete a *non-media* file that
	 * another app owns, even when it has been granted read access to it -- a zip
	 * in Downloads put there by a browser is exactly that. So this genuinely
	 * cannot always succeed, and it says which of the three happened rather than
	 * failing quietly and leaving somebody wondering whether the button worked.
	 *
	 * @return DELETED, ASKED or REFUSED.
	 */
	public static int delete(Activity activity, Uri uri)
	{
		if (uri == null)
			return REFUSED;

		final ContentResolver resolver = activity.getContentResolver();

		if (DocumentsContract.isDocumentUri(activity, uri))
		{
			try
			{
				if (DocumentsContract.deleteDocument(resolver, uri))
					return DELETED;
			}
			catch (Exception e)
			{
				Log.w(LOG, "could not delete the document", e);
			}
			return REFUSED;
		}

		// The app's own files go straight out. Anything else belongs to whoever
		// downloaded it, and only the player can agree to that.
		try
		{
			if (resolver.delete(uri, null, null) > 0)
				return DELETED;
		}
		catch (SecurityException e)
		{
			// Expected for a file this app did not create; ask properly below.
		}
		catch (Exception e)
		{
			Log.w(LOG, "could not delete " + uri, e);
		}

		if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R)
		{
			try
			{
				// createDeleteRequest insists on an id-specific URI in a
				// collection it recognises, and refuses the one an intent hands
				// over with "All requested items must be referenced by specific
				// ID". Rebuild it against the files collection, which covers
				// downloads as well as media.
				final long id = ContentUris.parseId(uri);
				final Uri canonical = ContentUris.withAppendedId(
					MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL), id);
				final ArrayList<Uri> one = new ArrayList<Uri>(Collections.singletonList(canonical));
				final IntentSender sender =
					MediaStore.createDeleteRequest(resolver, one).getIntentSender();
				activity.startIntentSenderForResult(sender, REQUEST_DELETE, null, 0, 0, 0);
				return ASKED;
			}
			catch (Exception e)
			{
				Log.w(LOG, "could not raise a delete request", e);
			}
		}
		return REFUSED;
	}

	/** What to tell the player, or null when there is nothing to say. */
	public static String describe(int outcome, String name)
	{
		switch (outcome)
		{
			case DELETED: return "Deleted " + name;
			case ASKED:   return null;   // the system is asking; it will report
			default:      return "Android would not let EC7Wolf delete " + name
				+ ". You can remove it from Downloads yourself.";
		}
	}
}
