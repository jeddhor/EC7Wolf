package com.beloko.idtech;

import android.app.Dialog;
import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.util.DisplayMetrics;
import android.view.Window;
import android.view.WindowManager;

/**
 * The shared look of this launcher's own dialogs.
 *
 * Left to itself a Dialog wraps its content, and a paragraph of text wrapped on
 * a landscape screen comes out as a tall narrow column down the middle with the
 * words against the frame. Both of this launcher's dialogs had that, so the fix
 * lives here rather than twice.
 */
public class DialogStyle
{
	/** Fraction of the screen width a dialog occupies. */
	private static final float WIDTH_FRACTION = 0.72f;

	/**
	 * Drop the system title bar. Must be called before setContentView -- the
	 * window's features are fixed once there is content -- which is why this is
	 * separate from {@link #frame}.
	 */
	public static void noTitleBar(Dialog dialog)
	{
		dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
	}

	/**
	 * Give the dialog a landscape shape and let the layout's own background be
	 * the one that shows. Call after setContentView.
	 */
	public static void frame(Dialog dialog, Context ctx)
	{
		Window window = dialog.getWindow();
		if (window == null)
			return;

		DisplayMetrics metrics = ctx.getResources().getDisplayMetrics();
		window.setLayout((int)(metrics.widthPixels * WIDTH_FRACTION),
			WindowManager.LayoutParams.WRAP_CONTENT);
		// Otherwise the window paints a light panel with square corners behind
		// the rounded frame the layout draws.
		window.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
	}
}
