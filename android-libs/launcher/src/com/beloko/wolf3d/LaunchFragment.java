package com.beloko.wolf3d;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.ObjectInputStream;
import java.io.ObjectOutputStream;
import java.util.ArrayList;
import java.util.Iterator;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Fragment;
import android.content.DialogInterface;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.DocumentsContract;
import android.graphics.drawable.BitmapDrawable;
import android.os.Bundle;
import android.util.Log;
import android.view.LayoutInflater;
import android.view.View;
import android.view.View.OnClickListener;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.ListView;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.RadioGroup.OnCheckedChangeListener;
import android.widget.TextView;
import android.widget.Toast;

import com.beloko.idtech.AppSettings;
import com.beloko.idtech.GameDataImport;
import com.beloko.idtech.GD;
import com.beloko.idtech.GD.IDGame;
import com.beloko.idtech.Utils;
import com.beloko.idtech.wolf3d.Game;
import com.beloko.idtech.R;

import org.libsdl.app.SDLActivity;

public class LaunchFragment extends Fragment{                           

	String LOG = "LaunchFragment";     

	TextView gameArgsTextView;       
	EditText argsEditText;       
	ListView listview;

	TextView copyWadsTextView;                                          

	String demoBaseDir;
	String fullBaseDir;

	ArrayList<String> argsHistory;

	TextView dataStatusTextView;
	Button startFullButton;

	// Request codes for the two ways in. SAF hands the result back through
	// onActivityResult, and the two paths read the URI differently.
	static final int REQUEST_IMPORT_ZIP = 4101;
	static final int REQUEST_IMPORT_FOLDER = 4102;


	@Override
	public void onCreate(Bundle savedInstanceState) {
		super.onCreate(savedInstanceState);

		AppSettings.setGame(IDGame.Corridor7);
		demoBaseDir = AppSettings.getQuakeDemoDir();
		fullBaseDir = AppSettings.getQuakeFullDir();

		AppSettings.createDirectories(getActivity());

		loadArgs();
	}                                          

	@Override
	public void onHiddenChanged(boolean hidden) {
		if (GD.DEBUG) Log.d(LOG,"onHiddenChanged");
		demoBaseDir = AppSettings.getQuakeDemoDir();
		fullBaseDir = AppSettings.getQuakeFullDir();

		super.onHiddenChanged(hidden);
	}


	@Override
	public View onCreateView(LayoutInflater inflater, ViewGroup container,
			Bundle savedInstanceState) {
		View mainView = inflater.inflate(R.layout.fragment_launch, null);


		argsEditText = (EditText)mainView.findViewById(R.id.extra_args_edittext);
		gameArgsTextView = (TextView)mainView.findViewById(R.id.extra_args_textview);

		Button startfull = (Button)mainView.findViewById(R.id.start_full);
		startfull.setOnClickListener(new OnClickListener() {

			@Override
			public void onClick(View v) {
				String missingFiles;
				// ec7wolf.pk3, not ecwolf.pk3: that is what this fork builds and what
				// the APK carries in its assets. Asking for the other name copies
				// nothing and the game starts with no data at all.
				if ((missingFiles = Utils.checkFiles(fullBaseDir , new String[] {"ec7wolf.pk3"})) != null)
					Utils.copyAsset(getActivity(), "ec7wolf.pk3", fullBaseDir);
				startGame(fullBaseDir);
			}
		});

		ImageView history = (ImageView)mainView.findViewById(R.id.args_history_imageview);
		history.setOnClickListener(new View.OnClickListener() {
			//@Override
			public void onClick(View v) {

				String[] servers = new String[ argsHistory.size()];
				for (int n=0;n<argsHistory.size();n++) servers[n] = argsHistory.get(n);

				AlertDialog.Builder builder = new AlertDialog.Builder(getActivity());
				builder.setTitle("Extra Args History");
				builder.setItems(servers, new DialogInterface.OnClickListener() {
					public void onClick(DialogInterface dialog, int which) {
						argsEditText.setText(argsHistory.get(which));
					}
				});
				builder.show();
			}        
		});


		dataStatusTextView = (TextView)mainView.findViewById(R.id.data_status_textview);
		startFullButton = startfull;

		Button importButton = (Button)mainView.findViewById(R.id.import_data_button);
		importButton.setOnClickListener(new OnClickListener() {
			@Override
			public void onClick(View v) {
				askWhereTheDataIs();
			}
		});

		refreshDataStatus();

		return mainView;
	}

	@Override
	public void onResume() {
		super.onResume();
		// The player may have imported, then gone away and come back; and the
		// game activity runs in its own process, so returning from a game is
		// also a resume here.
		refreshDataStatus();
	}

	/** Where the game's own files live: app-specific, so no permission. */
	File gameDir() {
		return new File(fullBaseDir);
	}

	/**
	 * The launcher used to start the game whatever was on disk, which meant a
	 * player with no data got a black screen and no explanation. This says what
	 * is missing and refuses to launch until it is not.
	 */
	void refreshDataStatus() {
		if (dataStatusTextView == null)
			return;

		String missing = GameDataImport.missing(gameDir());
		String wrongExe = GameDataImport.wrongExecutable(gameDir());
		if (missing == null && wrongExe != null) {
			dataStatusTextView.setText(wrongExe);
			if (startFullButton != null) startFullButton.setEnabled(false);
		} else if (missing == null) {
			dataStatusTextView.setText("Corridor 7 data found. Ready to play.");
			if (startFullButton != null) startFullButton.setEnabled(true);
		} else {
			dataStatusTextView.setText(
				"Corridor 7 data not found.\n\nUse Import Game Data and point it at "
				+ "your Corridor 7 files -- a folder, a zip, or the folder holding a "
				+ ".cue and .bin disc image. Missing: " + missing);
			if (startFullButton != null) startFullButton.setEnabled(false);
		}
	}

	/**
	 * Open the picker in Downloads, which is where a file on a phone came from
	 * unless it came from somewhere the player chose deliberately. Without this
	 * the folder picker starts at the root of storage, which the Storage Access
	 * Framework refuses to hand out -- so the first thing the player sees is
	 * "To protect your privacy, choose another folder", which reads like a
	 * refusal rather than an instruction to go somewhere else.
	 */
	void startAtDownloads(Intent intent) {
		if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O)
			return;
		try {
			Uri downloads = DocumentsContract.buildDocumentUri(
				"com.android.externalstorage.documents", "primary:Download");
			intent.putExtra(DocumentsContract.EXTRA_INITIAL_URI, downloads);
		} catch (Exception e) {
			// A hint, not a requirement: any provider that does not recognise
			// this just opens wherever it would have.
			Log.w(LOG, "could not point the picker at Downloads", e);
		}
	}

	void askWhereTheDataIs() {
		AlertDialog.Builder builder = new AlertDialog.Builder(getActivity());
		builder.setTitle("Import Game Data");
		builder.setItems(new String[] { "From a zip file",
				"From a folder or disc image" },
			new DialogInterface.OnClickListener() {
				public void onClick(DialogInterface dialog, int which) {
					if (which == 0) {
						Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
						i.addCategory(Intent.CATEGORY_OPENABLE);
						// Not application/zip: a zip arrives under half a dozen
						// different types depending on where it came from, and a
						// narrow filter greys out the file the player is looking at.
						i.setType("*/*");
						startAtDownloads(i);
						startActivityForResult(i, REQUEST_IMPORT_ZIP);
					} else {
						Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
						startAtDownloads(i);
						startActivityForResult(i, REQUEST_IMPORT_FOLDER);
					}
				}
			});
		builder.show();
	}

	@Override
	public void onActivityResult(int requestCode, int resultCode, Intent data) {
		if ((requestCode != REQUEST_IMPORT_ZIP && requestCode != REQUEST_IMPORT_FOLDER)
			|| data == null || data.getData() == null) {
			super.onActivityResult(requestCode, resultCode, data);
			return;
		}

		final Uri uri = data.getData();
		final boolean fromZip = requestCode == REQUEST_IMPORT_ZIP;
		dataStatusTextView.setText("Importing...");

		// Twenty-odd megabytes through a content provider is not something to
		// do on the UI thread, and the progress line is the only sign the
		// player has that it is working.
		new Thread(new Runnable() {
			public void run() {
				String result;
				try {
					GameDataImport.Listener progress = new GameDataImport.Listener() {
						public void onProgress(final String name) {
							post("Importing " + name + "...");
						}
					};
					int copied = fromZip
						? GameDataImport.importFromZip(
							getActivity().getContentResolver(), uri, gameDir(), progress)
						: GameDataImport.importFromTree(
							getActivity().getContentResolver(), uri, gameDir(), progress);
					result = copied == 0
						? "Nothing to import there. Point it at the folder holding "
							+ "MAPTEMP.CO7, or a zip containing it."
						: null;
				} catch (Exception e) {
					Log.e(LOG, "import failed", e);
					result = "Import failed: " + e.getMessage();
				}

				final String message = result;
				Activity activity = getActivity();
				if (activity == null) return;
				activity.runOnUiThread(new Runnable() {
					public void run() {
						refreshDataStatus();
						if (message != null && dataStatusTextView != null)
							dataStatusTextView.setText(message);
					}
				});
			}

			void post(final String text) {
				Activity activity = getActivity();
				if (activity == null) return;
				activity.runOnUiThread(new Runnable() {
					public void run() {
						if (dataStatusTextView != null) dataStatusTextView.setText(text);
					}
				});
			}
		}).start();
	}



	void startGame(final String base)
	{
		//Check prboom wad exists
		//File ecwolfpk3 = new File(base + "/ecwolf.pk3"  );
		//if (!ecwolfpk3.exists())
		{
			Utils.copyAsset(getActivity(),"ec7wolf.pk3",base);
		}


		String extraArgs = argsEditText.getText().toString().trim();

		if (extraArgs.length() > 0)
		{
			Iterator<String> it = argsHistory.iterator();
			while (it.hasNext()) { 
				String s = it.next();
				if (s.contentEquals(extraArgs))
					it.remove();
			}

			while (argsHistory.size()>50)  
				argsHistory.remove(argsHistory.size()-1);

			argsHistory.add(0, extraArgs);
			saveArgs();
		} 

		String args =  gameArgsTextView.getText().toString() + " " + argsEditText.getText().toString();

		Intent intent = new Intent(getActivity(), Game.class);
		intent.setAction(Intent.ACTION_MAIN);
		intent.addCategory(Intent.CATEGORY_LAUNCHER);

		intent.putExtra("game_path",base); 

		intent.putExtra("args"," --samplerate 11250 --bits 32"  + args + " ");                                                
		startActivity(intent);
	}                  


	void loadArgs()                         
	{ 
		File cacheDir = getActivity().getFilesDir();

		FileInputStream fis = null;
		ObjectInputStream in = null;
		try
		{
			fis = new FileInputStream(new File(cacheDir,"args_hist.dat"));
			in = new ObjectInputStream(fis);                
			argsHistory = (ArrayList<String>)in.readObject();
			in.close();
			return;
		}
		catch(IOException ex)
		{

		}  
		catch(ClassNotFoundException ex)
		{

		}

		//failed load, load default
		argsHistory = new ArrayList<String>();
	}  


	void saveArgs()
	{
		File cacheDir =  getActivity().getFilesDir();

		if (!cacheDir.exists())
			cacheDir.mkdirs();

		FileOutputStream fos = null;
		ObjectOutputStream out = null;
		try
		{
			fos = new FileOutputStream(new File(cacheDir,"args_hist.dat"));
			out = new ObjectOutputStream(fos);
			out.writeObject(argsHistory);
			out.close();
		}
		catch(IOException ex)         
		{
			Toast.makeText(getActivity(),"Error saving args History list: " + ex.toString(), Toast.LENGTH_LONG).show();
		}
	}              
}
