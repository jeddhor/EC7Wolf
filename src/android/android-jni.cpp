#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <jni.h>
#include <android/log.h>
#include <unistd.h>
// ES 3.0, which is the context this engine creates. The touch control headers
// pull in GLES2/gl2.h (via USE_GLES2), and that is a subset -- glBindVertexArray
// is not in it. Included first so the ES 3 declarations are the ones in scope.
#include <GLES3/gl3.h>

#include <mutex>
#include <atomic>

#include "TouchControlsContainer.h"
#include "OpenGLUtils.h"
#include "JNITouchControlsUtils.h"

extern "C"
{


#include "in_android.h"
#include "SDL_events.h"
#include "SDL_hints.h"
#include "SDL_keycode.h"
#include "SDL_system.h"

#define LOGI(...) ((void)__android_log_print(ANDROID_LOG_INFO,"JNI", __VA_ARGS__))
#define LOGW(...) ((void)__android_log_print(ANDROID_LOG_WARN, "JNI", __VA_ARGS__))
#define LOGE(...) ((void)__android_log_print(ANDROID_LOG_ERROR,"JNI", __VA_ARGS__))

#define JAVA_FUNC(x) Java_com_beloko_idtech_wolf3d_NativeLib_##x

int android_screen_width = 640;
int android_screen_height = 400;


#define KEY_SHOW_WEAPONS 0x1000
#define KEY_SHOOT        0x1001

#define KEY_SHOW_INV     0x1006
#define KEY_QUICK_CMD    0x1007

#define KEY_SHOW_KBRD    0x1009

float gameControlsAlpha = 0.5;
bool showWeaponCycle = false;
bool turnMouseMode = true;
bool invertLook = false;
bool precisionShoot = false;
bool showSticks = true;
bool hideTouchControls = true;
bool enableWeaponWheel = true;

bool shooting = false;

//set when holding down reload
bool sniperMode = false;

static int controlsCreated = 0;
touchcontrols::TouchControlsContainer controlsContainer;

touchcontrols::TouchControls *tcMenuMain=0;
touchcontrols::TouchControls *tcGameMain=0;
touchcontrols::TouchControls *tcGameWeapons=0;
touchcontrols::TouchControls *tcWeaponWheel=0;

//So can hide and show these buttons
touchcontrols::Button *nextWeapon=0;
touchcontrols::Button *prevWeapon=0;
touchcontrols::TouchJoy *touchJoyLeft;
touchcontrols::TouchJoy *touchJoyRight;

JNIEnv* env_;

int argc=1;
const char * argv[32];
std::string graphicpath;

GLint viewport[4];
// Saved across the overlay draw; see openGLStart.
static GLboolean savedDepthTest, savedStencilTest, savedCullFace;
static GLboolean savedScissor, savedBlend, savedDepthMask;

// The state the overlay needs, and nothing else.
//
// This used to be OpenGL ES 1.x: a projection matrix built with glOrthof, a
// modelview push, client-state arrays and glTexEnvf. None of that exists in ES
// 3.0, which is the context this engine asks for -- the calls resolved through
// libepoxy to nothing and the overlay drew nowhere. The control library's ES2
// path bakes its vertices straight into clip space (GLES2scaleX/Y in
// GLRect.cpp), so it wants no projection at all; it wants the viewport, alpha
// blending, and the depth test out of the way.
void openGLStart()
{
	// Drain anything the renderer left behind, so the check in openGLEnd is
	// reporting this overlay's mistakes and not somebody else's.
	{
		int guard = 0;
		while(glGetError() != GL_NO_ERROR && ++guard < 32) {}
	}

	glGetIntegerv(GL_VIEWPORT, viewport);
	// Saved so it can be put back. The renderer sets most of its state per
	// frame, but not all of it, and leaving depth writes off was enough to make
	// the whole world render black on the following frame while the overlay
	// itself looked perfect.
	savedDepthTest = glIsEnabled(GL_DEPTH_TEST);
	savedStencilTest = glIsEnabled(GL_STENCIL_TEST);
	savedCullFace = glIsEnabled(GL_CULL_FACE);
	savedScissor = glIsEnabled(GL_SCISSOR_TEST);
	savedBlend = glIsEnabled(GL_BLEND);
	glGetBooleanv(GL_DEPTH_WRITEMASK, &savedDepthMask);

	// Everything the overlay depends on, set explicitly. It draws after a full
	// frame of somebody else's rendering, and assuming any of this survived
	// that is how an overlay comes to run without drawing a pixel: the shaders
	// compile, the textures load, the draw calls are issued, and the result
	// lands in a framebuffer nobody presents or is masked out.
	glBindFramebuffer(GL_FRAMEBUFFER, 0);
	// Vertex array object 0, and no buffers. The overlay draws from client-side
	// arrays -- it hands glVertexAttribPointer a pointer into its own memory --
	// and that is only legal on ES 3 with the default VAO. Worse, if the
	// renderer leaves an array buffer bound, those pointers stop being pointers
	// and are read as byte offsets into it, which is not an error the driver has
	// to report and not a picture anybody wants.
	glBindVertexArray(0);
	glBindBuffer(GL_ARRAY_BUFFER, 0);
	glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
	glDisable(GL_SCISSOR_TEST);
	glDisable(GL_DEPTH_TEST);
	glDisable(GL_STENCIL_TEST);
	glDisable(GL_CULL_FACE);
	glDepthMask(GL_FALSE);
	glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
	glEnable(GL_BLEND);
	glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
	glActiveTexture(GL_TEXTURE0);

	// Over the whole window, so the controls sit on the black bars too when the
	// game's aspect does not fill the screen.
	glViewport(0, 0, android_screen_width, android_screen_height);
}

void openGLEnd()
{
	// Exactly what was there before, back again.
	if(savedDepthTest) glEnable(GL_DEPTH_TEST); else glDisable(GL_DEPTH_TEST);
	if(savedStencilTest) glEnable(GL_STENCIL_TEST); else glDisable(GL_STENCIL_TEST);
	if(savedCullFace) glEnable(GL_CULL_FACE); else glDisable(GL_CULL_FACE);
	if(savedScissor) glEnable(GL_SCISSOR_TEST); else glDisable(GL_SCISSOR_TEST);
	if(savedBlend) glEnable(GL_BLEND); else glDisable(GL_BLEND);
	glDepthMask(savedDepthMask);
	glViewport(viewport[0], viewport[1], viewport[2], viewport[3]);
	// The overlay leaves its own program and buffers bound. Unbind, so a stale
	// binding cannot quietly change what the next frame draws with.
	glUseProgram(0);
	glBindBuffer(GL_ARRAY_BUFFER, 0);
	glBindTexture(GL_TEXTURE_2D, 0);
}

void gameSettingsButton(int state)
{
	//LOGTOUCH("gameSettingsButton %d",state);
	if (state == 1)
	{
		showTouchSettings();
	}
}

extern unsigned int Sys_Milliseconds(void);

static unsigned int reload_time_down;
void gameButton(int state,int code)
{
	if (code == KEY_SHOOT)
	{
		shooting = state;
		PortableAction(state,PORT_ACT_ATTACK);
	}
	else if (code == PORT_ACT_RELOAD)
	{


		sniperMode = state; //Use reload button for precision aim also
	}
	else if (code == KEY_SHOW_WEAPONS)
	{
		if (state == 1)
			if (!tcGameWeapons->enabled)
			{

				tcGameWeapons->animateIn(5);
			}
	}
	else if  (code == KEY_SHOW_KBRD)
	{
		if (state)
			showKeyboard(true);
	}
	else
	{
		PortableAction(state, code);
	}
}


//Weapon wheel callbacks
void weaponWheelSelected(int enabled)
{
	if (enabled)
		tcWeaponWheel->fade(touchcontrols::FADE_IN,5); //fade in
	else
		tcWeaponWheel->fade(touchcontrols::FADE_OUT,5);
}
void weaponWheel(int segment)
{
	LOGI("weaponWheel %d",segment);
	int code;
	if (segment == 9)
		code = '0';
	else
		code = '1' + segment;

	PortableKeyEvent(1,code,0);
	PortableKeyEvent(0, code,0);
}

void menuButton(int state,int code)
{
	if (code == KEY_SHOW_KBRD)
	{
		if (state)
			toggleKeyboard();
		return;
	}
	PortableKeyEvent(state, code, 0);
}



int left_double_action;
int right_double_action;

void left_double_tap(int state)
{
	//LOGTOUCH("L double %d",state);
	if (left_double_action)
		PortableAction(state,left_double_action);
}

void right_double_tap(int state)
{
	//LOGTOUCH("R double %d",state);
	if (right_double_action)
		PortableAction(state,right_double_action);
}



//To be set by android
float strafe_sens,forward_sens;
float pitch_sens,yaw_sens;

void left_stick(float joy_x, float joy_y,float mouse_x, float mouse_y)
{
	joy_x *=10;
	//float strafe = joy_x*joy_x;
	float strafe = joy_x;
	//if (joy_x < 0)
	//	strafe *= -1;

	PortableMove(joy_y * 15 * forward_sens,-strafe * strafe_sens);
}
void right_stick(float joy_x, float joy_y,float mouse_x, float mouse_y)
{
	//LOGI(" mouse x = %f",mouse_x);
	int invert = invertLook?-1:1;

	float scale;

	if (sniperMode)
		scale = 0.1;
	else
		scale = (shooting && precisionShoot)?0.3:1;

	PortableLookPitch(LOOK_MODE_MOUSE,-mouse_y  * pitch_sens * invert * scale);

	if (turnMouseMode)
		PortableLookYaw(LOOK_MODE_MOUSE,mouse_x*2*yaw_sens * scale);
	else
		PortableLookYaw(LOOK_MODE_JOYSTICK,joy_x*6*yaw_sens * scale);

}

//Weapon select callbacks
void selectWeaponButton(int state, int code)
{
	PortableKeyEvent(state, code, 0);
	if (state == 0)
		tcGameWeapons->animateOut(5);
}

void weaponCycle(bool v)
{
	if (v)
	{
		if (nextWeapon) nextWeapon->setEnabled(true);
		if (prevWeapon) prevWeapon->setEnabled(true);
	}
	else
	{
		if (nextWeapon) nextWeapon->setEnabled(false);
		if (prevWeapon) prevWeapon->setEnabled(false);
	}
}

void setHideSticks(bool v)
{
	if (touchJoyLeft) touchJoyLeft->setHideGraphics(v);
	if (touchJoyRight) touchJoyRight->setHideGraphics(v);
}


// Serialised, because two things call it and they are not on the same thread.
//
// Android_SetScreenSize runs once from the initial display mode, on the SDL
// thread, and again from an SDL window resize event on whichever thread is
// pumping events -- and at start-up the display settles from portrait to
// landscape, so both happen at once. The controls, the texture cache and the
// file handle the PNG reader uses are all shared globals, so the two runs
// corrupt each other. It crashed in vsnprintf, which is not a place anybody
// would go looking for a threading bug.
void initControls(int width, int height,const char * graphics_path,const char *settings_file)
{
	static std::mutex controlsInitMutex;
	std::lock_guard<std::mutex> lock(controlsInitMutex);

	touchcontrols::GLScaleWidth = (float)width;
	touchcontrols::GLScaleHeight = (float)height;

	LOGI("initControls %d x %d,x path = %s, settings = %s",width,height,graphics_path,settings_file);

	if (!controlsCreated)
	{
		LOGI("creating controls");
		setControlsContainer(&controlsContainer);

		touchcontrols::setGraphicsBasePath(graphics_path);

		controlsContainer.openGL_start.connect( sigc::ptr_fun(&openGLStart));
		controlsContainer.openGL_end.connect( sigc::ptr_fun(&openGLEnd));


		tcMenuMain = new touchcontrols::TouchControls("menu",true,false);
		tcGameMain = new touchcontrols::TouchControls("game",false,true);
		tcGameWeapons = new touchcontrols::TouchControls("weapons",false,false);
		tcWeaponWheel = new touchcontrols::TouchControls("weapon_wheel",false,false);

		tcGameMain->signal_settingsButton.connect(  sigc::ptr_fun(&gameSettingsButton) );

		//Menu
		tcMenuMain->addControl(new touchcontrols::Button("down_arrow",touchcontrols::RectF(20,13,23,16),"arrow_down",SDL_SCANCODE_DOWN));
		tcMenuMain->addControl(new touchcontrols::Button("up_arrow",touchcontrols::RectF(20,10,23,13),"arrow_up",SDL_SCANCODE_UP));
		tcMenuMain->addControl(new touchcontrols::Button("left_arrow",touchcontrols::RectF(17,13,20,16),"arrow_left",SDL_SCANCODE_LEFT));
		tcMenuMain->addControl(new touchcontrols::Button("right_arrow",touchcontrols::RectF(23,13,26,16),"arrow_right",SDL_SCANCODE_RIGHT));
		tcMenuMain->addControl(new touchcontrols::Button("enter",touchcontrols::RectF(0,12,4,16),"enter",SDL_SCANCODE_RETURN));
		tcMenuMain->signal_button.connect(  sigc::ptr_fun(&menuButton) );

		tcMenuMain->setAlpha(0.8);


		//Game
		tcGameMain->setAlpha(gameControlsAlpha);
		tcGameMain->addControl(new touchcontrols::Button("attack",touchcontrols::RectF(20,7,23,10),"shoot",KEY_SHOOT));
		tcGameMain->addControl(new touchcontrols::Button("use",touchcontrols::RectF(23,6,26,9),"use",PORT_ACT_USE));
		// The two verbs a player reaches for mid-fight, under the same thumb as
		// fire and use. The infrared visor is how Corridor 7 is played in the
		// dark, and it is on a button rather than in a menu for that reason.
		tcGameMain->addControl(new touchcontrols::Button("visor",touchcontrols::RectF(23,9,26,12),"binocular",PORT_ACT_C7_VISOR));
		tcGameMain->addControl(new touchcontrols::Button("mine",touchcontrols::RectF(20,10,23,13),"mine",PORT_ACT_C7_MINE));
		tcGameMain->addControl(new touchcontrols::Button("quick_save",touchcontrols::RectF(24,0,26,2),"save",PORT_ACT_QUICKSAVE));
		tcGameMain->addControl(new touchcontrols::Button("quick_load",touchcontrols::RectF(20,0,22,2),"load",PORT_ACT_QUICKLOAD));
		// Corridor 7 has two maps and both get a picture of one. The game's own
		// inset floor panel takes the level-overview icon; ECWolf's
		// full-viewport automap takes a folded paper map. It used to be
		// labelled "F1" after the key it is bound to, which tells a player
		// holding a tablet nothing at all.
		tcGameMain->addControl(new touchcontrols::Button("floor_map",touchcontrols::RectF(4,0,6,2),"map",PORT_ACT_C7_FLOORMAP));
		tcGameMain->addControl(new touchcontrols::Button("map",touchcontrols::RectF(2,0,4,2),"foldmap",PORT_ACT_MAP));
		tcGameMain->addControl(new touchcontrols::Button("run",touchcontrols::RectF(7,0,9,2),"run",PORT_ACT_ALWAYS_RUN));
		tcGameMain->addControl(new touchcontrols::Button("keyboard",touchcontrols::RectF(9,0,11,2),"keyboard",KEY_SHOW_KBRD,false,true));

		tcGameMain->addControl(new touchcontrols::Button("plus",touchcontrols::RectF(17,0,19,2),"key_+",PORT_ACT_MAP_ZOOM_IN));
		tcGameMain->addControl(new touchcontrols::Button("minus",touchcontrols::RectF(15,0,17,2),"key_-",PORT_ACT_MAP_ZOOM_OUT));

//		tcGameMain->addControl(new touchcontrols::Button("show_weapons",touchcontrols::RectF(11,14,13,16),"show_weapons",KEY_SHOW_WEAPONS));

		nextWeapon = new touchcontrols::Button("next_weapon",touchcontrols::RectF(0,3,3,5),"next_weap",PORT_ACT_NEXT_WEP);
		tcGameMain->addControl(nextWeapon);
		prevWeapon = new touchcontrols::Button("prev_weapon",touchcontrols::RectF(0,7,3,9),"prev_weap",PORT_ACT_PREV_WEP);
		tcGameMain->addControl(prevWeapon);

		touchJoyLeft = new touchcontrols::TouchJoy("stick",touchcontrols::RectF(0,7,8,16),"strafe_arrow");
		tcGameMain->addControl(touchJoyLeft);
		touchJoyLeft->signal_move.connect(sigc::ptr_fun(&left_stick) );
		touchJoyLeft->signal_double_tap.connect(sigc::ptr_fun(&left_double_tap) );

		touchJoyRight = new touchcontrols::TouchJoy("touch",touchcontrols::RectF(17,4,26,16),"look_arrow");
		tcGameMain->addControl(touchJoyRight);
		touchJoyRight->signal_move.connect(sigc::ptr_fun(&right_stick) );
		touchJoyRight->signal_double_tap.connect(sigc::ptr_fun(&right_double_tap) );

		tcGameMain->signal_button.connect(  sigc::ptr_fun(&gameButton) );
/*
		//Weapons
		tcGameWeapons->addControl(new touchcontrols::Button("weapon1",touchcontrols::RectF(1,14,3,16),"1",SDL_SCANCODE_1));
		tcGameWeapons->addControl(new touchcontrols::Button("weapon2",touchcontrols::RectF(3,14,5,16),"2",SDL_SCANCODE_2));
		tcGameWeapons->addControl(new touchcontrols::Button("weapon3",touchcontrols::RectF(5,14,7,16),"3",SDL_SCANCODE_3));
		tcGameWeapons->addControl(new touchcontrols::Button("weapon4",touchcontrols::RectF(7,14,9,16),"4",SDL_SCANCODE_4));
		tcGameWeapons->addControl(new touchcontrols::Button("weapon5",touchcontrols::RectF(9,14,11,16),"5",SDL_SCANCODE_5));

		tcGameWeapons->addControl(new touchcontrols::Button("weapon6",touchcontrols::RectF(15,14,17,16),"6",'6'));
		tcGameWeapons->addControl(new touchcontrols::Button("weapon7",touchcontrols::RectF(17,14,19,16),"7",SDL_SCANCODE_7));
		tcGameWeapons->addControl(new touchcontrols::Button("weapon8",touchcontrols::RectF(19,14,21,16),"8",SDL_SCANCODE_8));
		tcGameWeapons->addControl(new touchcontrols::Button("weapon9",touchcontrols::RectF(21,14,23,16),"9",SDL_SCANCODE_9));
		tcGameWeapons->addControl(new touchcontrols::Button("weapon0",touchcontrols::RectF(23,14,25,16),"0",SDL_SCANCODE_0));
		tcGameWeapons->signal_button.connect(  sigc::ptr_fun(&selectWeaponButton) );
		tcGameWeapons->setAlpha(0.8);
*/
		//Weapon wheel
		touchcontrols::WheelSelect *wheel = new touchcontrols::WheelSelect("weapon_wheel",touchcontrols::RectF(7,2,19,14),"weapon_wheel",10);
		wheel->signal_selected.connect(sigc::ptr_fun(&weaponWheel) );
		wheel->signal_enabled.connect(sigc::ptr_fun(&weaponWheelSelected));
		tcWeaponWheel->addControl(wheel);
		tcWeaponWheel->setAlpha(0.5);


		controlsContainer.addControlGroup(tcGameMain);
		controlsContainer.addControlGroup(tcGameWeapons);
		controlsContainer.addControlGroup(tcMenuMain);
//		controlsContainer.addControlGroup(tcWeaponWheel);
		controlsCreated = 1;

		tcGameMain->setXMLFile(settings_file);
	}
	else
		LOGI("NOT creating controls");

	controlsContainer.initGL();
}

}

static void ApplyPendingScreenSize();

int inMenuLast = 1;
int inAutomapLast = 0;
void frameControls()
{
	//LOGI("frameControls\n");

	ApplyPendingScreenSize();
	// Nothing to drive until the controls exist; the pointers below are null.
	if(!controlsCreated)
		return;

	// A context the overlay's objects do not belong to any more. Rebuild them
	// before drawing, or every draw this frame is against dead names.
	if(touchcontrols::GLES2ContextLost())
	{
		LOGI("touch overlay: GL context changed, rebuilding");
		touchcontrols::GLES2Forget();
		controlsContainer.initGL();
	}

	int inMenuNew = PortableInMenu();
	if (inMenuLast != inMenuNew)
	{
		inMenuLast = inMenuNew;
		if (!inMenuNew)
		{
			tcGameMain->setEnabled(true);
			if (enableWeaponWheel)
				tcWeaponWheel->setEnabled(true);
			tcMenuMain->setEnabled(false);
		}
		else
		{
			tcGameMain->setEnabled(false);
			tcGameWeapons->setEnabled(false);
			tcWeaponWheel->setEnabled(false);
			tcMenuMain->setEnabled(true);
		}
	}


	weaponCycle(showWeaponCycle);
	setHideSticks(!showSticks);
	controlsContainer.draw();

	// glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
	// glClear(GL_COLOR_BUFFER_BIT);
}

extern "C" {

void setTouchSettings(float alpha,float strafe,float fwd,float pitch,float yaw,int other)
{

	gameControlsAlpha = alpha;
	if (tcGameMain)
		tcGameMain->setAlpha(gameControlsAlpha);

	showWeaponCycle = other & 0x1?true:false;
	turnMouseMode   = other & 0x2?true:false;
	invertLook      = other & 0x4?true:false;
	precisionShoot  = other & 0x8?true:false;
	showSticks      = other & 0x1000?true:false;
	enableWeaponWheel  = other & 0x2000?true:false;

	if (tcWeaponWheel)
		tcWeaponWheel->setEnabled(enableWeaponWheel);


	hideTouchControls = other & 0x80000000?true:false;


	switch ((other>>4) & 0xF)
	{
	case 1:
		left_double_action = PORT_ACT_ATTACK;
		break;
	case 2:
		left_double_action = PORT_ACT_JUMP;
		break;
	default:
		left_double_action = 0;
	}

	switch ((other>>8) & 0xF)
	{
	case 1:
		right_double_action = PORT_ACT_ATTACK;
		break;
	case 2:
		right_double_action = PORT_ACT_JUMP;
		break;
	default:
		right_double_action = 0;
	}

	strafe_sens = strafe;
	forward_sens = fwd;
	pitch_sens = pitch;
	yaw_sens = yaw;

}

int quit_now = 0;

#define EXPORT_ME __attribute__ ((visibility("default")))


std::string game_path;

const char * getGamePath()
{
	return game_path.c_str();
}

std::string home_env;
}

extern int WL_Main(int, char*[]);
extern "C"
int SDL_main(int argc, char* argv[])
{
	// The control overlay draws itself with ES 2 shaders over the game's
	// context; see android-libs/TouchControls.
	SDL_SetHint(SDL_HINT_RENDER_DRIVER, "opengles");

	SDL_SetHint(SDL_HINT_ACCELEROMETER_AS_JOYSTICK, "false");

	// Corridor 7 is a landscape game and the manifest says sensorLandscape,
	// but SDL overrides that: with no orientation hint set it derives the
	// activity's orientation from whatever window it is creating, and a window
	// at least as tall as it is wide counts as portrait. The GL probe's window
	// is 32x32, so probing for a core context flipped the whole activity into
	// portrait (1440x3120) until the real window flipped it back -- a visible
	// portrait flash at every launch, and the resize storm underneath the
	// start-up races in Android_SetScreenSize.
	SDL_SetHint(SDL_HINT_ORIENTATIONS, "LandscapeLeft LandscapeRight");

	JNIEnv *env = env_ = static_cast<JNIEnv*>(SDL_AndroidGetJNIEnv());
	JavaVM *vm;
	env_->GetJavaVM(&vm);
	setTCJNIEnv(vm);

	for(int i = 0;i < argc;++i)
		LOGI("Arg%d = %s\n", i, argv[i]);

	game_path = argv[1];

	LOGI("game_path = %s",getGamePath());

	//Needed for ecwolf to run
	//home_env = "HOME=/" + game_path;
	//putenv(home_env.c_str());
	setenv("HOME", getGamePath(),1);

	setenv("XDG_CONFIG_HOME", getGamePath(),1);

	chdir(getGamePath());


	const char * p = argv[2];
	LOGI("graphicpath = %s\n", p);
	graphicpath =  std::string(p);

	WL_Main(argc-2,argv+2); //Never returns!!

	return 0;
}

// Recorded here, acted on in frameControls.
//
// This runs from an SDL window-event watcher, and a watcher runs on whichever
// thread pushed the event -- for a resize on Android that is the Java main
// thread. initControls builds GL textures, and the GL context belongs to the
// SDL thread, so calling it from here ran it on a thread with no context at
// all: the texture loader took a failure path, threw, and the exception
// unwound out through SDL into the JNI trampoline, where there is no handler.
// That is the 0xebad8084 crash. Only the size is recorded here.
static std::atomic<bool> screenSizePending(false);

void Android_SetScreenSize(int w, int h)
{
	android_screen_width = w;
	android_screen_height = h;
	screenSizePending.store(true);
}

// Called from frameControls, which runs on the SDL thread with the context
// current, so this is the one place control textures can be built.
static void ApplyPendingScreenSize()
{
	if(!screenSizePending.exchange(false))
		return;

	try
	{
		initControls(android_screen_width,-android_screen_height,graphicpath.c_str(),(graphicpath + "/game_controls.xml").c_str());
	}
	catch(const std::exception &e)
	{
		LOGI("initControls failed: %s", e.what());
	}
	catch(...)
	{
		LOGI("initControls failed");
	}
}

static int Android_EventWatch(void *, SDL_Event *event)
{
	switch(event->common.type)
	{
	case SDL_FINGERMOTION:
		controlsContainer.processPointer(P_MOVE, event->tfinger.fingerId, event->tfinger.x, event->tfinger.y);
		break;
	case SDL_FINGERDOWN:
		controlsContainer.processPointer(P_DOWN, event->tfinger.fingerId, event->tfinger.x, event->tfinger.y);
		break;
	case SDL_FINGERUP:
		controlsContainer.processPointer(P_UP, event->tfinger.fingerId, event->tfinger.x, event->tfinger.y);
		break;
	}

	return 0;
}

static int Android_WindowEventWatch(void *, SDL_Event *event)
{
	switch(event->common.type)
	{
	case SDL_WINDOWEVENT:
		if(event->window.event == SDL_WINDOWEVENT_SIZE_CHANGED)
			Android_SetScreenSize(event->window.data1, event->window.data2);
		break;
	}

	return 0;
}

void Android_InitGraphics()
{
	// Finger events must be captured before the SDL_Renderer is initialized
	// otherwise it will clip the input range to the viewport.
	SDL_AddEventWatch(Android_EventWatch, NULL);
}

void PostSDLCreateRenderer(SDL_Window *Screen)
{
	SDL_AddEventWatch(Android_WindowEventWatch, NULL);

	SDL_DisplayMode mode;
	SDL_GetWindowDisplayMode(Screen, &mode);
	Android_SetScreenSize(mode.w, mode.h);
}

extern "C" {

void EXPORT_ME
JAVA_FUNC(keypress) (JNIEnv *env, jobject obj,jint down, jint keycode, jint unicode)
{
	//LOGI("keypress %d",keycode);
	if (controlsContainer.isEditing())
	{
		if (down && (keycode == SDL_SCANCODE_ESCAPE ))
			controlsContainer.finishEditing();
		return;
	}
	PortableKeyEvent(down,keycode,unicode);
}


void EXPORT_ME
JAVA_FUNC(touchEvent) (JNIEnv *env, jobject obj,jint action, jint pid, jfloat x, jfloat y)
{
	//LOGI("TOUCHED");
	controlsContainer.processPointer(action,pid,x,y);
}


void EXPORT_ME
JAVA_FUNC(doAction) (JNIEnv *env, jobject obj,	jint state, jint action)
{
	//gamepadButtonPressed();
	if (hideTouchControls)
		if (tcGameMain)
			if (tcGameMain->isEnabled())
				tcGameMain->animateOut(30);
	//LOGI("doAction %d %d",state,action);
	PortableAction(state,action);
}

void EXPORT_ME
JAVA_FUNC(analogFwd) (JNIEnv *env, jobject obj,	jfloat v)
{
	PortableMoveFwd(v);
}

void EXPORT_ME
JAVA_FUNC(analogSide) (JNIEnv *env, jobject obj,jfloat v)
{
	PortableMoveSide(v);
}

void EXPORT_ME
JAVA_FUNC(analogPitch) (JNIEnv *env, jobject obj, jint mode,jfloat v)
{
	PortableLookPitch(mode, v);
}

void EXPORT_ME
JAVA_FUNC(analogYaw) (JNIEnv *env, jobject obj,	jint mode,jfloat v)
{
	PortableLookYaw(mode, v);
}

void EXPORT_ME
JAVA_FUNC(setTouchSettings) (JNIEnv *env, jobject obj,	jfloat alpha,jfloat strafe,jfloat fwd,jfloat pitch,jfloat yaw,int other)
{
	setTouchSettings(alpha,strafe,fwd,pitch,yaw,other);
}

std::string quickCommandString;
jint EXPORT_ME
JAVA_FUNC(quickCommand) (JNIEnv *env, jobject obj,	jstring command)
{
	const char * p = env->GetStringUTFChars(command,NULL);
	quickCommandString =  std::string(p) + "\n";
	env->ReleaseStringUTFChars(command, p);
	PortableCommand(quickCommandString.c_str());
	return 0;
}

}
