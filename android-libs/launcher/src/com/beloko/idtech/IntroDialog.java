package com.beloko.idtech;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;

import android.app.Dialog;
import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.util.DisplayMetrics;
import android.view.View;
import android.view.View.OnClickListener;
import android.view.Window;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.TextView;

public class IntroDialog {

	public static void show(final Context ctx,String title,int textid)
	{
		final Dialog dialog = new Dialog(ctx);
		// No system title bar: the layout draws its own, so that the space
		// around it is ours to set rather than the platform's.
		dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
		dialog.setContentView(R.layout.intro);
		dialog.setCancelable(true);

		// A dialog left to itself wraps its content, which for a paragraph of
		// text on a landscape screen produces a tall narrow column down the
		// middle. Give it most of the width and let the height follow the text,
		// capped so a long message scrolls instead of running off the screen.
		Window window = dialog.getWindow();
		if (window != null)
		{
			DisplayMetrics metrics = ctx.getResources().getDisplayMetrics();
			window.setLayout((int)(metrics.widthPixels * 0.72f),
				WindowManager.LayoutParams.WRAP_CONTENT);
			// The window's own background would otherwise draw a light panel
			// with square corners behind the frame the layout draws.
			window.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
		}

		final TextView heading = (TextView) dialog.findViewById(R.id.intro_title);
		if (heading != null)
			heading.setText(title);

		//set up text
		final TextView text = (TextView) dialog.findViewById(R.id.textView1);
		text.setText(readTxt(ctx,textid));

		//set up image view


		//set up button
		Button button = (Button) dialog.findViewById(R.id.button1);
		button.setOnClickListener(new OnClickListener() {
			@Override
			public void onClick(View v) {
				dialog.dismiss();    
			}
		});


	
		//now that the dialog is set up, it's time to show it    
		dialog.show();

	}


	private static String readTxt(Context ctx, int id){

		InputStream inputStream = ctx.getResources().openRawResource(id);

		ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();

		int i;
		try {
			i = inputStream.read();
			while (i != -1)
			{
				byteArrayOutputStream.write(i);
				i = inputStream.read();
			}
			inputStream.close();
		} catch (IOException e) {
			e.printStackTrace();
		}

		return byteArrayOutputStream.toString();
	}

	public static boolean showIntro(Context ctx)
	{
		int show = AppSettings.getIntOption(ctx,"intro_shown", -1);
		if (show == -1)
		{
			AppSettings.setIntOption(ctx, "intro_shown", 1);
			return true;
		}
		else
			return false;
	}
}
