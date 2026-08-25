package com.beloko.wolf3d;

import android.app.Activity;
import android.app.ActionBar;
import android.app.ActionBar.Tab;
import android.app.Fragment;
import android.app.FragmentTransaction;
import android.app.AlertDialog;
import android.app.ProgressDialog;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.util.Log;
// Was android.support.v4.app.FragmentActivity. This class never used it:
// every fragment here is a framework fragment (android.app.Fragment,
// getFragmentManager), so FragmentActivity contributed nothing but a
// dependency on a support library that Google deleted from the repository
// the build looked for it in.
import android.view.KeyEvent;
import android.view.Menu;
import android.view.MotionEvent;

import com.beloko.idtech.AppSettings;
import com.beloko.idtech.GD;
import com.beloko.idtech.GD.IDGame;
import com.beloko.idtech.GameDataImport;
import com.beloko.idtech.GamePadFragment;
import com.beloko.idtech.IntroDialog;
import com.beloko.idtech.OptionsFragment;
import com.beloko.idtech.R;

import java.io.File;
public class EntryActivity extends Activity  {

	private static final String LOG = "EntryActivity";


	final static int LAUNCH_FRAG = 0;
	final static int MODS_FRAG = 1;

	GamePadFragment gamePadFrag;
	/**
	 * The serialization (saved instance state) Bundle key representing the
	 * current tab position.
	 */
	private static final String STATE_SELECTED_NAVIGATION_ITEM = "selected_navigation_item";

	@Override
	protected void onCreate(Bundle savedInstanceState) {
		super.onCreate(savedInstanceState);

		GD.init(getApplicationContext());
		//Utils.expired();

		setContentView(R.layout.activity_quake);

		// Set up the action bar to show tabs.
		final ActionBar actionBar = getActionBar();
		actionBar.setNavigationMode(ActionBar.NAVIGATION_MODE_TABS);

		AppSettings.setGame(IDGame.Corridor7);
		AppSettings.reloadSettings(getApplication());

		actionBar.addTab(actionBar.newTab().setText("play").setTabListener(new TabListener<LaunchFragment>(this, "play", LaunchFragment.class)));
		actionBar.addTab(actionBar.newTab().setText("gamepad").setTabListener(new TabListener<GamePadFragment>(this, "gamepad", GamePadFragment.class)));
		actionBar.addTab(actionBar.newTab().setText("options").setTabListener(new TabListener<OptionsFragment>(this, "options", OptionsFragment.class)));

		gamePadFrag = (GamePadFragment)getFragmentManager().findFragmentByTag("gamepad");

		if (IntroDialog.showIntro(this))
		{
			IntroDialog.show(this,"EC7Wolf", R.raw.intro);
		}

		handleImportIntent(getIntent());
		/*else
		{
			if (AboutDialog.showAbout(this))
				AboutDialog.show(this);
		}*/


	}

	@Override
	public void onRestoreInstanceState(Bundle savedInstanceState) {
		// Restore the previously serialized current tab position.
		if (savedInstanceState.containsKey(STATE_SELECTED_NAVIGATION_ITEM)) {
			getActionBar().setSelectedNavigationItem(
					savedInstanceState.getInt(STATE_SELECTED_NAVIGATION_ITEM));
		}
	}

	@Override
	public void onSaveInstanceState(Bundle outState) {
		// Serialize the current tab position.
		outState.putInt(STATE_SELECTED_NAVIGATION_ITEM, getActionBar()
				.getSelectedNavigationIndex());
	}

	@Override
	public boolean onCreateOptionsMenu(Menu menu) {
		// Inflate the menu; this adds items to the action bar if it is present.
		//getMenuInflater().inflate(R.menu.activity_quake, menu);
		return true;
	}


	@Override
	public boolean onGenericMotionEvent(MotionEvent event) {
		if (gamePadFrag == null)
			gamePadFrag = (GamePadFragment)getFragmentManager().findFragmentByTag("gamepad");

		gamePadFrag.onGenericMotionEvent(event);
		return super.onGenericMotionEvent(event);
	}


	@Override
	public boolean onKeyDown(int keyCode, KeyEvent event)
	{
		if (gamePadFrag == null)
			gamePadFrag = (GamePadFragment)getFragmentManager().findFragmentByTag("gamepad");

		if (gamePadFrag.onKeyDown(keyCode, event))
			return true;
		else
			return super.onKeyDown(keyCode, event);
	}

	@Override
	public boolean onKeyUp(int keyCode, KeyEvent event)
	{
		if (gamePadFrag == null)
			gamePadFrag = (GamePadFragment)getFragmentManager().findFragmentByTag("gamepad");

		if ( gamePadFrag.onKeyUp(keyCode, event))
			return true;
		else
			return super.onKeyUp(keyCode, event);
	} 

	public void test()
	{

	}

	public static class TabListener<T extends Fragment> implements ActionBar.TabListener {
		private final Activity mActivity;
		private final String mTag;
		private final Class<T> mClass;
		private final Bundle mArgs;
		private Fragment mFragment;

		public TabListener(Activity activity, String tag, Class<T> clz) {
			this(activity, tag, clz, null);
		}

		public TabListener(Activity activity, String tag, Class<T> clz, Bundle args) {
			mActivity = activity;
			mTag = tag;
			mClass = clz;
			mArgs = args;

			// Check to see if we already have a fragment for this tab, probably
			// from a previously saved state.  If so, deactivate it, because our
			// initial state is that a tab isn't shown.
			mFragment = mActivity.getFragmentManager().findFragmentByTag(mTag);

			if (mFragment == null) //Actually create all fragments NOW
			{
				mFragment = Fragment.instantiate(mActivity, mClass.getName(), mArgs);
				FragmentTransaction ft =  mActivity.getFragmentManager().beginTransaction();
				ft.add(android.R.id.content, mFragment, mTag);	
				ft.commit();
			}


			//if (mFragment != null && !mFragment.isDetached()) {
			if (mFragment != null && !mFragment.isHidden()) {
				FragmentTransaction ft = mActivity.getFragmentManager().beginTransaction();
				//ft.detach(mFragment);
				ft.hide(mFragment);
				ft.commit();
			}
		}

		public void onTabSelected(Tab tab, FragmentTransaction ft) {
			if (mFragment == null) {
				mFragment = Fragment.instantiate(mActivity, mClass.getName(), mArgs);
				ft.add(android.R.id.content, mFragment, mTag);
			} else {
				//ft.attach(mFragment);
				//ft.setCustomAnimations(R., R.anim.fade_out, R.anim.fade_in, R.anim.fade_out);
				ft.show(mFragment);
			}
		}

		public void onTabUnselected(Tab tab, FragmentTransaction ft) {
			if (mFragment != null) {
				//ft.detach(mFragment);
				ft.hide(mFragment);
			}
		}

		public void onTabReselected(Tab tab, FragmentTransaction ft) {
			//Toast.makeText(mActivity, "Reselected!", Toast.LENGTH_SHORT).show();
		}
	}


	@Override
	protected void onNewIntent(Intent intent)
	{
		super.onNewIntent(intent);
		setIntent(intent);
		handleImportIntent(intent);
	}

	/**
	 * Import from an archive somebody handed us.
	 *
	 * This is what makes "open with EC7Wolf" work from a file manager or a
	 * browser's download, which is a friendlier road in than the folder picker
	 * -- and the only one a test can drive, because it needs no UI at all.
	 *
	 * The archive may be a zip of the game files or a zip holding the CD image;
	 * GameDataImport works out which.
	 */
	private void handleImportIntent(Intent intent)
	{
		if (intent == null)
			return;

		final String action = intent.getAction();
		Uri uri = null;
		if (Intent.ACTION_VIEW.equals(action))
			uri = intent.getData();
		else if (Intent.ACTION_SEND.equals(action))
			uri = (Uri)intent.getParcelableExtra(Intent.EXTRA_STREAM);
		if (uri == null)
			return;

		// Consumed, so that rotating the screen or coming back to the launcher
		// does not import the same archive again.
		intent.setAction(Intent.ACTION_MAIN);
		intent.setData(null);

		final Uri source = uri;
		final File gameDir = new File(AppSettings.getQuakeFullDir());
		final ProgressDialog progress = new ProgressDialog(this);
		progress.setTitle("Importing game data");
		progress.setMessage("Reading the archive...");
		progress.setIndeterminate(true);
		progress.setCancelable(false);
		progress.show();

		new Thread(new Runnable() {
			public void run() {
				String problem = null;
				int copied = 0;
				try
				{
					copied = GameDataImport.importFromZip(getContentResolver(), source,
						gameDir, new GameDataImport.Listener() {
							public void onProgress(final String what) {
								runOnUiThread(new Runnable() {
									public void run() { progress.setMessage(what); }
								});
							}
						});
				}
				catch (Exception e)
				{
					Log.e(LOG, "import failed", e);
					problem = e.getMessage();
				}

				final String failed = problem;
				final int count = copied;
				runOnUiThread(new Runnable() {
					public void run() {
						try { progress.dismiss(); } catch (Exception ignored) {}

						// The PLAY tab refreshes itself when the activity
						// resumes, and importing from an intent never pauses it
						// -- so without this the launcher goes on saying the
						// data is missing while it sits there imported.
						final Fragment play = getFragmentManager().findFragmentByTag("play");
						if (play instanceof LaunchFragment)
							((LaunchFragment)play).refreshDataStatus();

						final String missing = GameDataImport.missing(gameDir);
						final String text = failed != null
							? "Import failed: " + failed
							: missing == null
								? "Imported " + count + " files. Corridor 7 is ready to play."
								: "That archive did not have everything in it. Still missing: " + missing;
						new AlertDialog.Builder(EntryActivity.this)
							.setTitle("Import Game Data")
							.setMessage(text)
							.setPositiveButton("OK", null)
							.show();
					}
				});
			}
		}).start();
	}

}
