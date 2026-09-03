// WL_PLAY.C

#include "c_cvars.h"
#include "wl_def.h"
#include "g_session.h"
#include "g_command.h"
#include "r_capture.h"
#include "render/r_renderer.h"
#include "render/r_interpolation.h"
#include "render/r_dynamicwalls.h"
#include "wl_menu.h"
#include "id_ca.h"
#include "id_sd.h"
#include "id_vl.h"
#include "id_vh.h"
#include "id_us.h"

#include "wl_cloudsky.h"
#include "wl_shade.h"
#include "language.h"
#include "lumpremap.h"
#include "m_random.h"
#include "thinker.h"
#include "actor.h"
#include "textures/textures.h"
#include "v_video.h"
#include "v_font.h"
#include "wl_agent.h"
#include "wl_debug.h"
#include "wl_draw.h"
#include "wl_game.h"
#include "wl_inter.h"
#include "wl_net.h"
#include "net_watchdog.h"
#include "c7_automap.h"
#include "c7_scoreboard.h"
#include "c7_cdaudio.h"
#include "wl_play.h"
#include "g_mapinfo.h"
#include "a_inventory.h"
#include "am_map.h"
#include "thingdef/thingdef.h"
#include "wl_iwad.h"

/*
=============================================================================

												LOCAL CONSTANTS

=============================================================================
*/

#define sc_Question     0x35

/*
=============================================================================

												GLOBAL VARIABLES

=============================================================================
*/

bool madenoise;              // true when shooting or screaming

exit_t playstate;

#ifdef __ANDROID__
extern bool ShadowingEnabled;
#endif

bool noclip, ammocheat, mouselook = false;
int godmode, singlestep;
bool notargetmode = false;
unsigned int extravbls = 0; // to remove flicker (gray stuff at the bottom)
unsigned short Paused;

//
// replacing refresh manager
//
bool noadaptive = false;
unsigned tics;

//
// control info
//
#define JoyAx(x) (32+(x<<1))
#define CS_AxisDigital -1
ControlScheme controlScheme[] =
{
	// Modern defaults: WASD to move and strafe, the mouse to turn, E to use.
	// The arrow keys stay on turning so the original layout still works for
	// anyone who reaches for it, and the mouse turns by default because
	// mousemovesforward is off (a mouse push no longer walks the player).
	//
	// Gamepad values >= 32 are axis directions, JoyAx(n) being axis n's negative
	// side and JoyAx(n)+1 its positive side (see the decode in PollControls).
	// Corridor 7 was built for keyboard and joystick, so the pad layout is a
	// choice rather than a reconstruction; it follows what an Xbox controller
	// does in any modern shooter:
	//
	//   left stick   move / strafe        A      use            LB / RB  weapons
	//   right stick  turn                 X      drop mine      LT / RT  alt / fire
	//   L3           run                  Y      visor mode     Back     floor map
	//   R3           full automap                                Start    menu
	//
	// Start is not listed in the table because it cannot be: id_in.cpp routes
	// SDL_CONTROLLER_BUTTON_START straight to bt_esc so a pad can always reach
	// the menu, and never reports it as a bindable button.
	{ bt_moveforward,		"Forward",		JoyAx(1),	sc_W,			-1, offsetof(TicCmd_t, controly), 1 },
	{ bt_movebackward,		"Backward",		JoyAx(1)+1,	sc_S,			-1, offsetof(TicCmd_t, controly), 0 },
	{ bt_strafeleft,		"Strafe Left",	JoyAx(0),	sc_A,			-1, offsetof(TicCmd_t, controlstrafe), 1 },
	{ bt_straferight,		"Strafe Right",	JoyAx(0)+1,	sc_D,			-1, offsetof(TicCmd_t, controlstrafe), 0 },
	{ bt_turnleft,			"Turn Left",	JoyAx(3),	sc_LeftArrow,	-1, offsetof(TicCmd_t, controlx), 1 },
	{ bt_turnright,			"Turn Right",	JoyAx(3)+1,	sc_RightArrow,	-1, offsetof(TicCmd_t, controlx), 0 },
	{ bt_attack,			"Attack",		JoyAx(5)+1,	sc_Control,		0,  CS_AxisDigital, 0},
	{ bt_strafe,			"Strafe",		-1,			sc_Alt,			-1, CS_AxisDigital, 0 },
	{ bt_run,				"Run",			7,			sc_LShift,		-1, CS_AxisDigital, 0 },
	{ bt_use,				"Use",			0,			sc_E,			-1, CS_AxisDigital, 0 },
	{ bt_slot1,				"Slot 1",		-1,			sc_1,			-1, CS_AxisDigital, 0 },
	{ bt_slot2,				"Slot 2", 		-1,			sc_2,			-1, CS_AxisDigital, 0 },
	{ bt_slot3,				"Slot 3",		-1,			sc_3,			-1, CS_AxisDigital, 0 },
	{ bt_slot4,				"Slot 4",		-1,			sc_4,			-1, CS_AxisDigital, 0 },
	{ bt_slot5,				"Slot 5",		-1,			sc_5,			-1, CS_AxisDigital, 0 },
	{ bt_slot6,				"Slot 6",		-1,			sc_6,			-1, CS_AxisDigital, 0 },
	{ bt_slot7,				"Slot 7",		-1,			sc_7,			-1, CS_AxisDigital, 0 },
	{ bt_slot8,				"Slot 8",		-1,			sc_8,			-1, CS_AxisDigital, 0 },
	{ bt_slot9,				"Slot 9",		-1,			sc_9,			-1, CS_AxisDigital, 0 },
	{ bt_slot0,				"Slot 0",		-1,			sc_0,			-1, CS_AxisDigital, 0 },
	// Shoulder buttons cycle weapons, which is where a modern pad puts them.
	// They were on Back and Guide, and Guide is the system button.
	{ bt_nextweapon,		"Next Weapon",	10,			-1,				-1, CS_AxisDigital, 0 },
	{ bt_prevweapon,		"Prev Weapon",	9, 			-1,				-1, CS_AxisDigital, 0 },
	{ bt_altattack,			"Alt Attack",	JoyAx(4)+1,	-1,				-1, CS_AxisDigital, 0 },
	{ bt_reload,			"Drop Mine",	2,			sc_M,			-1, CS_AxisDigital, 0 },
	{ bt_zoom,				"Visor Mode",	3,			sc_Enter,		-1, CS_AxisDigital, 0 },
	// Corridor 7 has two maps and both are kept. Tab raises the game's own
	// inset panel, which is what the original put there. ECWolf's
	// full-viewport automap goes on F1, which the original leaves unused
	// (F2 saves, F3 loads, and so on), so no original binding moves.
	// wl_debug.cpp jams its debug-key sequence for whichever of these holds
	// sc_Tab -- see schemeAutomapKey.
	{ bt_automap,			"Automap",		8,			sc_F1,			-1, CS_AxisDigital, 0 },
	{ bt_showstatusbar,		"Show Status",	-1,			-1,				-1,	CS_AxisDigital, 0 },
	// Back/Select raises the floor map, which is the map button on a modern pad.
	{ bt_c7map,				"Floor Map",	4,			sc_Tab,			-1, CS_AxisDigital, 0 },
	// The scoreboard is on the key a shooter usually puts it on once Tab is
	// spoken for. It does nothing outside a netgame.
	{ bt_scoreboard,		"Scoreboard",	-1,			sc_Grave,		-1, CS_AxisDigital, 0 },
	{ bt_pause,				"Pause",		-1,			sc_Pause,		-1, CS_AxisDigital, 0 },
	{ bt_esc,				"Main Menu",	-1,			-1,				-1, CS_AxisDigital, 0 },

	// End of List
	{ bt_nobutton,			NULL, -1, -1, -1, CS_AxisDigital, 0 }
};
// The entry wl_debug.cpp consults to decide whether a Tab press is a map
// key rather than the start of a debug chord. That is the Corridor 7 panel
// now, not bt_automap. When the input system is redone, hopefully we don't
// need this kind of thing.
ControlScheme &schemeAutomapKey = controlScheme[27];

// Whether a raw scancode is the one bt_automap is bound to, so CheckKeys can
// keep it out of the control-panel F-key range.
static bool IsAutomapKeyboardScan(int scan)
{
	for(int i = 0;controlScheme[i].button != bt_nobutton;++i)
	{
		if(controlScheme[i].button == bt_automap)
			return controlScheme[i].keyboard != -1 && scan == controlScheme[i].keyboard;
	}
	return false;
}

ControlScheme amControlScheme[] =
{
	{ bt_zoomin,			"Zoom In",		JoyAx(2),	sc_Equals,		-1, -1, 0 },
	{ bt_zoomout,			"Zoom Out",		JoyAx(2)+1,	sc_Minus,		-1, -1, 0 },
	{ bt_panup,				"Pan Up",		JoyAx(1),	sc_UpArrow,		-1, offsetof(TicCmd_t, controlpany), 0 },
	{ bt_pandown,			"Pan Down",		JoyAx(1)+1,	sc_DownArrow,	-1, offsetof(TicCmd_t, controlpany), 1 },
	{ bt_panleft,			"Pan Left",		JoyAx(0),	sc_LeftArrow,	-1, offsetof(TicCmd_t, controlpanx), 0 },
	{ bt_panright,			"Pan Right",	JoyAx(0)+1,	sc_RightArrow,	-1, offsetof(TicCmd_t, controlpanx), 1 },

	{ bt_nobutton,			NULL, -1, -1, -1, -1, 0 }
};

void ControlScheme::setKeyboard(ControlScheme* scheme, Button button, int value)
{
	for(int i = 0;scheme[i].button != bt_nobutton;i++)
	{
		if(scheme[i].keyboard == value)
			scheme[i].keyboard = -1;
		if(scheme[i].button == button)
			scheme[i].keyboard = value;
	}
}

void ControlScheme::setJoystick(ControlScheme* scheme, Button button, int value)
{
	for(int i = 0;scheme[i].button != bt_nobutton;i++)
	{
		if(scheme[i].joystick == value)
			scheme[i].joystick = -1;
		if(scheme[i].button == button)
			scheme[i].joystick = value;
	}
}

void ControlScheme::setMouse(ControlScheme* scheme, Button button, int value)
{
	for(int i = 0;scheme[i].button != bt_nobutton;i++)
	{
		if(scheme[i].mouse == value)
			scheme[i].mouse = -1;
		if(scheme[i].button == button)
			scheme[i].mouse = value;
	}
}

int viewsize;

bool demorecord, demoplayback;
int8_t *demoptr, *lastdemoptr;
memptr demobuffer;

//
// current user input
//
unsigned int ConsolePlayer = 0;
TicCmd_t control[MAXPLAYERS];

//===========================================================================


void CenterWindow (word w, word h);
int StopMusic (void);
void StartMusic (void);
void ContinueMusic (int offs);
void PlayLoop (void);

/*
=============================================================================

							TIMING

=============================================================================
*/

static int32_t lasttimecount;

// --- Fixed-step frame pacing (renderer redesign Phase 3) ------------------
bool            g_interpFrameTiming = false;	// gameplay loop decoupled timing
static uint64_t s_perfLast          = 0;		// high-res counter, last frame
static double   s_accumulator        = 0.0;		// unspent sim time (seconds)
static float    s_interpAlpha        = 0.0f;	// fraction into next tic [0,1)
static uint64_t s_frameLimitMark     = 0;		// high-res counter for vid_maxfps

static double PerfSeconds(uint64_t later, uint64_t earlier)
{
	return (double)(later - earlier) / (double)SDL_GetPerformanceFrequency();
}

int32_t GetTimeCount()
{
	return MS2TICS(SDL_GetTicks());
}

float R_GetInterpolationAlpha()
{
	return (g_interpFrameTiming && r_interpolate) ? s_interpAlpha : 0.0f;
}

void R_ResetFrameTiming()
{
	s_perfLast = SDL_GetPerformanceCounter();
	s_frameLimitMark = s_perfLast;
	s_accumulator = 0.0;
	s_interpAlpha = 0.0f;
}

//
// Decoupled frame pacing: render as often as the frame limit allows, running
// 0..MAXTICS whole simulation tics per frame and exposing the residual as the
// interpolation alpha. Used by the gameplay loop; the legacy blocking CalcTics
// path is kept for intermission/animation loops.
//
static void CalcTicsInterpolated()
{
	const double TicSeconds = 1.0 / 70.0;

	// Optional frame-rate cap. Sleeping here folds the wait into the elapsed
	// time measured below, so the accumulator stays accurate.
	if(vid_maxfps > 0)
	{
		const double minPeriod = 1.0 / (double)vid_maxfps;
		double since = PerfSeconds(SDL_GetPerformanceCounter(), s_frameLimitMark);
		while(since < minPeriod)
		{
			if(minPeriod - since > 0.0015)
				SDL_Delay(1);
			since = PerfSeconds(SDL_GetPerformanceCounter(), s_frameLimitMark);
		}
	}
	s_frameLimitMark = SDL_GetPerformanceCounter();

	const uint64_t now = SDL_GetPerformanceCounter();
	if(s_perfLast == 0)
		s_perfLast = now;
	double elapsed = PerfSeconds(now, s_perfLast);
	s_perfLast = now;

	// Clamp catch-up so a long stall (load, pause, debugger) can't spiral.
	const double maxElapsed = (double)MAXTICS * TicSeconds;
	if(elapsed > maxElapsed) elapsed = maxElapsed;
	if(elapsed < 0.0)        elapsed = 0.0;

	s_accumulator += elapsed;

	int wholeTics = (int)(s_accumulator / TicSeconds);
	if(wholeTics > MAXTICS)
		wholeTics = MAXTICS;
	if(wholeTics < 0)
		wholeTics = 0;

	tics = (unsigned)wholeTics;
	s_accumulator -= (double)wholeTics * TicSeconds;
	// If we clamped tics, cap the residual so alpha never exceeds one tic.
	if(s_accumulator >= TicSeconds)
		s_accumulator = TicSeconds * 0.999;

	s_interpAlpha = (float)(s_accumulator / TicSeconds);

	// Keep the tic-based clock (texture animations etc.) monotonic.
	lasttimecount = GetTimeCount();
}

/*
=====================
=
= CalcTics
=
=====================
*/

void CalcTics()
{
	// Gameplay loop uses decoupled frame pacing + interpolation; other loops
	// (intermission, animation) keep the legacy blocking behavior below.
	if(g_interpFrameTiming)
	{
		CalcTicsInterpolated();
		return;
	}

//
// calculate tics since last refresh for adaptive timing
//

	// Have we arrived too soon?
	while(lasttimecount == GetTimeCount()+1)
		SDL_Delay(1);

	// Detect rollover, particularly if the game were paused for a LONG time
	if(lasttimecount > GetTimeCount())
		ResetTimeCount();

	uint32_t curtime = SDL_GetTicks();
	tics = MS2TICS(curtime) - lasttimecount;
	if(!tics)
	{
		// wait until end of current tic
		SDL_Delay(TICS2MS(lasttimecount + 1) - curtime);
		tics = 1;
	}
	else if(noadaptive || Net::IsBlocked())
		tics = 1;

	lasttimecount += tics;

	if (tics>MAXTICS)
		tics = MAXTICS;
}

void ResetTimeCount()
{
	lasttimecount = GetTimeCount();
}

void Delay(int wolfticks)
{
	if(wolfticks>0)
		SDL_Delay(TICS2MS(wolfticks));
}

/*
=============================================================================

							USER CONTROL

=============================================================================
*/

/*
===================
=
= PollKeyboardButtons
=
===================
*/

// Alt+Enter is the fullscreen chord (see CheckKeys). Enter is also Corridor 7's
// visor button, and PollControls runs before CheckKeys in the frame, so without
// this the same press toggles the visor as a side effect of going fullscreen.
// That is not cosmetic: visor mode 2 sets extralight to 20, which zeroes the
// first 20 plane shade bands, so the floor and ceiling go flat and it reads as
// the renderer losing its lighting. The cost is that the visor cannot be toggled
// while strafe (Alt) is held.
static inline bool KeyboardChordJammed(int key)
{
	return key == sc_Enter && Keyboard[sc_Alt];
}

void PollKeyboardButtons (void)
{
	if(automap == AMA_Normal)
	{
		// HACK
		bool jam[512] = {false};
		bool jamall = !!(Paused & 2); // Paused for automap

		for(int i = 0;jamall ? amControlScheme[i].button != bt_nobutton : amControlScheme[i].button <= bt_zoomout;i++)
		{
			if(amControlScheme[i].keyboard != -1 && Keyboard[amControlScheme[i].keyboard])
			{
				control[ConsolePlayer].ambuttonstate[amControlScheme[i].button] = true;
				jam[amControlScheme[i].keyboard] = true;
			}
		}
		for(int i = 0;controlScheme[i].button != bt_nobutton;i++)
		{
			if(controlScheme[i].keyboard != -1 && Keyboard[controlScheme[i].keyboard] &&
				!jam[controlScheme[i].keyboard] &&
				!KeyboardChordJammed(controlScheme[i].keyboard))
				control[ConsolePlayer].buttonstate[controlScheme[i].button] = true;
		}
	}
	else
	{
		for(int i = 0;controlScheme[i].button != bt_nobutton;i++)
		{
			if(controlScheme[i].keyboard != -1 && Keyboard[controlScheme[i].keyboard] &&
				!KeyboardChordJammed(controlScheme[i].keyboard))
				control[ConsolePlayer].buttonstate[controlScheme[i].button] = true;
		}
	}
}


/*
===================
=
= PollMouseButtons
=
===================
*/

void PollMouseButtons (void)
{
	int buttons = IN_MouseButtons();
	for (int i = 0; controlScheme[i].button != bt_nobutton; i++)
	{
		if (controlScheme[i].mouse == -1)
			continue;

		BYTE &state = control[ConsolePlayer].buttonstate[controlScheme[i].button];
		switch(controlScheme[i].mouse)
		{
		case ControlScheme::MWheel_Left:
			if (MouseWheel[di_west])
				state = true;
			break;
		case ControlScheme::MWheel_Right:
			if (MouseWheel[di_east])
				state = true;
			break;
		case ControlScheme::MWheel_Down:
			if (MouseWheel[di_south])
				state = true;
			break;
		case ControlScheme::MWheel_Up:
			if (MouseWheel[di_north])
				state = true;
			break;
		default:
			if ((buttons & (1 << controlScheme[i].mouse)))
				state = true;
			break;
		}
	}

	IN_ClearWheel();
}



/*
===================
=
= PollJoystickButtons
=
===================
*/

void PollJoystickButtons (void)
{
	if(automap == AMA_Normal)
	{
		// HACK
		bool jam[64] = {false};
		bool jamall = !!(Paused & 2); // Paused for automap

		int buttons = IN_JoyButtons();
		int axes = IN_JoyAxes();
		for(int i = 0;jamall ? amControlScheme[i].button != bt_nobutton : amControlScheme[i].button <= bt_zoomout;i++)
		{
			if(amControlScheme[i].joystick != -1)
			{
				if(amControlScheme[i].joystick < 32 && (buttons & (1<<amControlScheme[i].joystick)))
				{
					control[ConsolePlayer].ambuttonstate[amControlScheme[i].button] = true;
					jam[amControlScheme[i].joystick] = true;
				}
				else if(amControlScheme[i].axis == -1 && amControlScheme[i].joystick >= 32 && (axes & (1<<(amControlScheme[i].joystick-32))))
				{
					control[ConsolePlayer].ambuttonstate[amControlScheme[i].button] = true;
					jam[amControlScheme[i].joystick] = true;
				}
			}
		}
		for(int i = 0;controlScheme[i].button != bt_nobutton;i++)
		{
			if(controlScheme[i].joystick != -1 && !jam[controlScheme[i].joystick])
			{
				if(controlScheme[i].joystick < 32 && (buttons & (1<<controlScheme[i].joystick)))
					control[ConsolePlayer].buttonstate[controlScheme[i].button] = true;
				else if(controlScheme[i].axis == -1 && controlScheme[i].joystick >= 32 && (axes & (1<<(controlScheme[i].joystick-32))))
					control[ConsolePlayer].buttonstate[controlScheme[i].button] = true;
			}
		}
	}
	else
	{
		int buttons = IN_JoyButtons();
		int axes = IN_JoyAxes();
		for(int i = 0;controlScheme[i].button != bt_nobutton;i++)
		{
			if(controlScheme[i].joystick != -1)
			{
				if(controlScheme[i].joystick < 32 && (buttons & (1<<controlScheme[i].joystick)))
					control[ConsolePlayer].buttonstate[controlScheme[i].button] = true;
				else if(controlScheme[i].axis == -1 && controlScheme[i].joystick >= 32 && (axes & (1<<(controlScheme[i].joystick-32))))
					control[ConsolePlayer].buttonstate[controlScheme[i].button] = true;
			}
		}
	}
}


/*
===================
=
= PollKeyboardMove
=
===================
*/

void PollKeyboardMove (void)
{
	TicCmd_t &cmd = control[ConsolePlayer];

	int delta = (!alwaysrun && cmd.buttonstate[bt_run]) || (alwaysrun && !cmd.buttonstate[bt_run]) ? RUNMOVE : BASEMOVE;

	if(cmd.buttonstate[bt_moveforward])
		cmd.controly -= delta;
	if(cmd.buttonstate[bt_movebackward])
		cmd.controly += delta;
	if(cmd.buttonstate[bt_turnleft])
		cmd.controlx -= delta;
	if(cmd.buttonstate[bt_turnright])
		cmd.controlx += delta;
	if(cmd.buttonstate[bt_strafeleft])
		cmd.controlstrafe -= delta;
	if(cmd.buttonstate[bt_straferight])
		cmd.controlstrafe += delta;
}


/*
===================
=
= PollMouseMove
=
===================
*/

void PollMouseMove (void)
{
	SDL_GetRelativeMouseState(&control[ConsolePlayer].controlpanx, &control[ConsolePlayer].controlpany);

	control[ConsolePlayer].controlx += control[ConsolePlayer].controlpanx * 20 / (21 - mousexadjustment);
	if(mouselook)
	{
		// The one place a human still reaches past the command boundary and
		// writes simulated state directly. Every other input this function
		// samples ends up in a TicCmd_t, gets sent, and is applied by every
		// machine; pitch is written straight onto the pawn and TicCmdPacket
		// carries no pitch field, so in a netgame each machine holds a
		// different value for the same actor.
		//
		// That is not cosmetic. ChecksumThisTic() hashes actor pitch, so
		// mouselook desynchronizes the determinism harness -- the instrument
		// the whole netgame is verified with -- and reports it as a
		// simulation divergence, which is a long way to chase a mouse.
		//
		// Mouselook is a debug toggle with no menu entry, so refusing it
		// online costs a player nothing today. Carrying a bounded pitch field
		// in the canonical command is the real answer and belongs with the
		// protocol work: docs/multiplayer-bots-and-server.md, S1 and 24.3.
		if(Net::IsNetworked())
			return;

		int mousey = control[ConsolePlayer].controlpany;

		if(players[ConsolePlayer].ReadyWeapon && players[ConsolePlayer].ReadyWeapon->fovscale > 0)
			mousey = xs_ToInt(control[ConsolePlayer].controlpany*fabs(players[ConsolePlayer].ReadyWeapon->fovscale));

		players[ConsolePlayer].mo->pitch += mousey * (ANGLE_1 / (21 - mouseyadjustment));
		if(players[ConsolePlayer].mo->pitch+ANGLE_180 > ANGLE_180+56*ANGLE_1)
			players[ConsolePlayer].mo->pitch = 56*ANGLE_1;
		else if(players[ConsolePlayer].mo->pitch+ANGLE_180 < ANGLE_180-56*ANGLE_1)
			players[ConsolePlayer].mo->pitch = ANGLE_NEG(56*ANGLE_1);
	}
	else if(mousemovesforward)
		control[ConsolePlayer].controly += control[ConsolePlayer].controlpany * 40 / (21 - mouseyadjustment);
}


/*
===================
=
= PollJoystickMove
=
===================
*/

void PollJoystickMove (void)
{
	const bool useam = automap == AMA_Normal && Paused;
	const ControlScheme *scheme = useam ? amControlScheme+2 : controlScheme;
	do
	{
		if(scheme->joystick >= 32)
		{
			int axisnum = (scheme->joystick-32)>>1;
			bool positive = (scheme->joystick&1) != 0;
			// Scale to -100 - 100
			const int rawaxis = clamp(IN_GetJoyAxis(axisnum), -0x7FFF, 0x7FFF);
			const int dzfactor = clamp(JoySensitivity[axisnum].deadzone*0x8000/20, 0, 0x7FFF);
			int axis = clamp(abs(rawaxis)+1-dzfactor, 0, 0x8000)*5*JoySensitivity[axisnum].sensitivity/(0x8000-dzfactor);
			if(useam)
				axis >>= 2;
			else if(control[ConsolePlayer].buttonstate[bt_run])
				axis <<= 1;
			if(positive ^ (rawaxis < 0))
				*(int*)((char*)&control[ConsolePlayer] + scheme->axis) += scheme->negative ? -axis : axis;
		}
	}
	while((++scheme)->axis != CS_AxisDigital);
}

/*
===================
=
= PollControls
=
= Gets user or demo input
= Enable absolute positioning once per frame. This prevents absolute devices
= from being carried over to adaptive tics.
=
= controlx              set between -100 and 100 per tic
= controly
= buttonheld[]  the state of the buttons LAST frame
= buttonstate[] the state of the buttons THIS frame
=
===================
*/

void PollControls (bool absolutes)
{
	int i;
	byte buttonbits;

	TicCmd_t &cmd = control[ConsolePlayer];

	cmd.controlx = 0;
	cmd.controly = 0;
	cmd.controlpanx = 0;
	cmd.controlpany = 0;
	cmd.controlstrafe = 0;
	memcpy (cmd.buttonheld, cmd.buttonstate, sizeof (cmd.buttonstate));
	memset (cmd.buttonstate, 0, sizeof (cmd.buttonstate));
	if (automap)
	{
		memcpy (cmd.ambuttonheld, cmd.ambuttonstate, sizeof (cmd.ambuttonstate));
		memset (cmd.ambuttonstate, 0, sizeof (cmd.ambuttonstate));
	}

	if (demoplayback)
	{
		//
		// read commands from demo buffer
		//
		buttonbits = *demoptr++;
		for (i = 0; i < NUMBUTTONS; i++)
		{
			cmd.buttonstate[i] = buttonbits & 1;
			buttonbits >>= 1;
		}

		cmd.controlx = *demoptr++;
		cmd.controly = *demoptr++;

		if (demoptr == lastdemoptr)
			playstate = ex_completed;   // demo is done

		Command::SetLocalUi(cmd);
		return;
	}


//
// get button states
//
	PollKeyboardButtons ();

	if (mouseenabled && IN_IsInputGrabbed())
		PollMouseButtons ();

	if (joystickenabled && IN_JoyPresent())
		PollJoystickButtons ();

//
// get movements
//
	PollKeyboardMove ();

	if (absolutes && mouseenabled && IN_IsInputGrabbed())
		PollMouseMove ();

	if (joystickenabled && IN_JoyPresent())
		PollJoystickMove ();

#ifdef __ANDROID__
	extern void pollAndroidControls();
	pollAndroidControls();
#endif

	// Capture-time button presses, before the command is recorded or sent, so
	// they travel like real ones.
	Capture::InjectControls(cmd);

	// What this keyboard asked for, kept before finalization removes the parts
	// that are nobody else's business. The automap, the scoreboard and pause
	// are read from here; the simulation never sees them.
	Command::SetLocalUi(cmd);

	if (demorecord)
	{
		//
		// save info out to demo buffer
		//
		buttonbits = 0;

		// TODO: Support 32-bit buttonbits
		for (i = NUMBUTTONS - 1; i >= 0; i--)
		{
			buttonbits <<= 1;
			if (cmd.buttonstate[i])
				buttonbits |= 1;
		}

		*demoptr++ = buttonbits;
		*demoptr++ = cmd.controlx;
		*demoptr++ = cmd.controly;

		if (demoptr >= lastdemoptr - 8)
			playstate = ex_completed;
	}
	else if(Net::IsNetworked())
		Net::PollControls();

	// The canonical frame for the tic about to run: one command for every
	// active slot, all of them finalized before any thinker moves anything, so
	// that one slot's movement cannot change another slot's command.
	//
	// A slot with a producer is asked; a slot without one already has its
	// command, either sampled from this keyboard or delivered by the network,
	// and goes through the same finalizer so that clamping, the gameplay
	// whitelist and held-state derivation happen in exactly one place.
	{
		const uint32_t sequence = (uint32_t)gamestate.TimeCount;
		Command::BeginFrame(sequence);
		for(unsigned int slot = 0;slot < Session::ActiveSlotCount();++slot)
		{
			if(Command::HasProducer(slot))
				Command::ProduceAndInstall(slot, sequence);
			else
				Command::InstallSampled(slot, control[slot]);
		}
		Command::FinishFrame();
	}

	// Local UI, from what this keyboard asked for rather than from the
	// finalized command -- which no longer carries these, and in a netgame
	// would be a delay window out of date if it did.
	const TicCmd_t &ui = Command::LocalUi();

	// Check automap toggle before we set any buttons as held
	if (ui.buttonstate[bt_c7map] && !ui.buttonheld[bt_c7map])
		C7Map_Toggle();

	if (ui.buttonstate[bt_automap] && !ui.buttonheld[bt_automap])
	{
		AM_Toggle();
	}
	if (automap)
	{
		AM_CheckKeys();
	}

	// Pause is this machine stopping its own world. It used to be read out of
	// every slot's command, which meant a remote player's pause key stopped
	// yours -- and once pause stops being a button that travels, there is
	// nothing in a command to read.
	{
		if (ui.buttonstate[bt_pause] && !ui.buttonheld[bt_pause])
		{
			Paused ^= 1;

			static int lastoffs;
			if(Paused & 1)
			{
				lastoffs = StopMusic();
				IN_ReleaseMouse();
			}
			else
			{
				IN_GrabMouse();
				ContinueMusic(lastoffs);
				if (MousePresent && IN_IsInputGrabbed())
					IN_CenterMouse();     // Clear accumulated mouse movement
				ResetTimeCount();
			}
		}
	}
}

// This should be called once per frame
void ProcessEvents()
{
	IN_ProcessEvents();

//
// get timing info for last frame
//
	if (demoplayback || demorecord)   // demo recording and playback needs to be constant
	{
		// wait up to DEMOTICS Wolf tics
		uint32_t curtime = SDL_GetTicks();
		lasttimecount += DEMOTICS;
		int32_t timediff = TICS2MS(lasttimecount) - curtime;
		if(timediff > 0)
			SDL_Delay(timediff);

		if(timediff < -2 * DEMOTICS)       // more than 2-times DEMOTICS behind?
			lasttimecount = MS2TICS(curtime);    // yes, set to current timecount

		tics = DEMOTICS;
	}
	else
		CalcTics ();
}

//===========================================================================


void BumpGamma()
{
	screenGamma += 0.1f;
	if(screenGamma > 3.0f)
		screenGamma = 1.0f;
	screen->SetGamma(screenGamma);
	US_CenterWindow (10,2);
	FString msg;
	msg.Format("Gamma: %g", screenGamma);
	US_PrintCentered (msg);
	VW_UpdateScreen();
	IN_Ack(ACK_Block);
}

/*
=====================
=
= CheckKeys
=
= This should only cover control panel keys, debug mode key checks have been
= moved to CheckDebugKeys.
=
=====================
*/

void CheckKeys (void)
{
	static bool changeSize = true;
	ScanCode scan;


	if (screenfaded || demoplayback)    // don't do anything with a faded screen
		return;

	scan = LastScan;

	// [BL] Allow changing the screen size with the -/= keys a la Doom.
	if(automap != AMA_Normal && changeSize)
	{
		if(Keyboard[sc_Equals] && !Keyboard[sc_Minus])
			NewViewSize(viewsize+1);
		else if(!Keyboard[sc_Equals] && Keyboard[sc_Minus])
			NewViewSize(viewsize-1);
		if(Keyboard[sc_Equals] || Keyboard[sc_Minus])
		{
			// Upstream plays world/hitwall here. Corridor 7's wall thud is a
			// harsh, low sample that sounds like a glitch on a menu action, so
			// resizing the view is silent.
			if (viewsize < 21)
				DrawPlayScreen();
			changeSize = false;
		}
	}
	else if(!Keyboard[sc_Equals] && !Keyboard[sc_Minus])
		changeSize = true;

	// Edge-triggered: CheckKeys runs every frame, so a level test re-entered the
	// video mode change on every frame the chord was held -- which under OpenGL
	// means tearing down and rebuilding the window's GL context each time.
	{
		static bool altEnterHeld = false;
		if(Keyboard[sc_Alt] && Keyboard[sc_Enter])
		{
			if(!altEnterHeld)
			{
				altEnterHeld = true;
				VL_ToggleFullscreen();
			}
		}
		else
			altEnterHeld = false;
	}

//
// F1-F7/ESC to enter control panel
//
	if (scan == sc_F10 ||
		scan == sc_F9 || scan == sc_F7 || scan == sc_F8)     // pop up quit dialog
	{
		ClearSplitVWB ();
		US_ControlPanel (scan);

		DrawPlayBorderSides ();

		IN_ClearKeysDown ();

		if(screenfaded && Net::IsBlocked())
			PlayFrame();
		return;
	}

	// The key the automap is bound to must not also open the control panel.
	// Wolf3D put help on F1; Corridor 7 leaves F1 unused (F2 saves, F3 loads),
	// which is why the full-viewport automap sits there.
	if ((scan >= sc_F1 && scan <= sc_F9 && !IsAutomapKeyboardScan(scan)) ||
		scan == sc_Escape || control[ConsolePlayer].buttonstate[bt_esc])
	{
		int lastoffs = StopMusic ();
		SD_StopDigitized();

		US_ControlPanel (control[ConsolePlayer].buttonstate[bt_esc] ? sc_Escape : scan);

		IN_ClearKeysDown ();

		if(screenfaded)
		{
			if (!startgame && !loadedgame)
			{
				VW_FadeOut();
				ContinueMusic (lastoffs);
				if(viewsize != 21)
					DrawPlayScreen ();
			}
			if (loadedgame)
				playstate = ex_abort;
			if (MousePresent && IN_IsInputGrabbed())
				IN_CenterMouse();     // Clear accumulated mouse movement

			// If another player is blocking the play sim we may need to refresh
			// the frame now before we wait for input.
			if (Net::IsBlocked())
				PlayFrame();
		}
		else
		{
			ContinueMusic (lastoffs);
		}
		return;
	}

	if(scan == sc_F11)
	{
		BumpGamma();
		return;
	}
}


//===========================================================================

/*
=============================================================================

												MUSIC STUFF

=============================================================================
*/


/*
=================
=
= StopMusic
=
=================
*/
int StopMusic (void)
{
	// The disc plays straight through a floor change, the control panel and the
	// pause key -- StartLevelTrack only moves the playlist on once a song has
	// actually run out, so stopping here would restart the soundtrack every
	// time the player opened a menu.
	if(C7CD::Available())
		return 0;

	return SD_MusicOff();
}

static FString currentLevelMusic;
static FRandom pr_c7music("Corridor7Music");

static FString SelectLevelMusic()
{
	if(!IWad::CheckGameFilter("Corridor7"))
		return levelInfo->GetMusic(map);

	// Exact 36-entry selector table at 4557:0bd0 in CORR7CD.EXE. Levels
	// 1-30 index it directly; the released CD code deliberately randomizes
	// the selection for later and bonus floors.
	static const byte schedule[36] = {
		29, 18, 20, 9, 2, 14, 7, 8, 27, 22, 13, 4,
		31, 25, 15, 5, 12, 33, 24, 6, 20, 27, 28, 26,
		29, 32, 2, 25, 11, 10, 16, 1, 3, 23, 26, 30
	};
	const int floor = atoi(levelInfo->FloorNumber.GetChars());
	const int selection = floor >= 1 && floor <= 30 ?
		schedule[floor - 1] : schedule[pr_c7music(36)];
	FString music;
	music.Format("C7MUS%02d", selection);
	return music;
}

//==========================================================================


/*
=================
=
= StartMusic
=
=================
*/

void StartMusic ()
{
	// Chosen even when the disc's soundtrack is in use. Floors past 30 draw
	// their AdLib song out of the random number stream, and skipping that draw
	// would make a game with the CD music installed play out differently from
	// one without it.
	const FString adlibMusic = SelectLevelMusic();

	if(C7CD::Available())
	{
		C7CD::StartLevelTrack();
		return;
	}

	SD_MusicOff ();
	currentLevelMusic = adlibMusic;
	SD_StartMusic(currentLevelMusic);
}

void ContinueMusic (int offs)
{
	if(C7CD::Available())
		return;

	// Switched off the disc from the menu mid-level: no AdLib song was ever
	// picked for this floor, so pick one now rather than resuming nothing.
	if(currentLevelMusic.IsEmpty() && C7CD::Present())
	{
		StartMusic();
		return;
	}

	SD_MusicOff ();
	if(!(Paused & 1))
		SD_ContinueMusic(currentLevelMusic.IsEmpty() ? levelInfo->GetMusic(map) : currentLevelMusic, offs);
}

/*
=============================================================================

										PALETTE SHIFTING STUFF

=============================================================================
*/

#define NUMREDSHIFTS    6
#define REDSTEPS        8

#define NUMWHITESHIFTS  3
#define WHITESTEPS      20
#define WHITETICS       6

int damagecount, bonuscount;
static int c7ChamberFlashCount, c7ElectricFlashCount;
bool palshifted;

/*
=====================
=
= ClearPaletteShifts
=
=====================
*/

void ClearPaletteShifts (void)
{
	bonuscount = damagecount = c7ChamberFlashCount = c7ElectricFlashCount = 0;
	V_SetCorridor7PaletteMode(0);
	palshifted = false;
}


/*
=====================
=
= StartBonusFlash
=
=====================
*/

void StartBonusFlash (void)
{
	bonuscount = NUMWHITESHIFTS * WHITETICS;    // white shift palette
}


/*
=====================
=
= StartDamageFlash
=
=====================
*/

void StartDamageFlash (int damage)
{
	damagecount += damage;
}

void StartC7ChamberFlash (void)
{
	// Long and strong enough to be unmistakable, while retaining the native
	// yellow treatment flash instead of replacing it with a white pickup blink.
	c7ChamberFlashCount = 24;
}

void StartC7ElectricFlash (void)
{
	c7ElectricFlashCount = 18;
}


/*
=====================
=
= UpdatePaletteShifts
=
=====================
*/

void UpdatePaletteShifts (void)
{
	int red, white;
	int visorMode = 0;
	int c7InvulnerabilityStrobe = 0;
	if(IWad::CheckGameFilter("Corridor7") && players[ConsolePlayer].mo)
	{
		AInventory *mode = players[ConsolePlayer].mo->FindInventory(
			ClassDef::FindClass("C7VisorMode"));
		if(mode)
			visorMode = mode->amount == 2 ? 1 : (mode->amount == 3 ? 2 : 0);
		AInventory *sphere = players[ConsolePlayer].mo->FindInventory(
			ClassDef::FindClass("C7Invulnerability"));
		if(sphere)
			c7InvulnerabilityStrobe = (int)sphere->amount;
	}
	if(c7ElectricFlashCount > 0)
	{
		c7ElectricFlashCount = MAX(0, c7ElectricFlashCount-static_cast<int>(tics));
		V_SetCorridor7PaletteMode(3, gamestate.TimeCount>>1);
	}
	else
		V_SetCorridor7PaletteMode(visorMode);

	if (bonuscount)
	{
		white = bonuscount / WHITETICS + 1;
		if (white > NUMWHITESHIFTS)
			white = NUMWHITESHIFTS;
		bonuscount -= tics;
		if (bonuscount < 0)
			bonuscount = 0;
	}
	else
		white = 0;


	if (damagecount)
	{
		red = damagecount / 10 + 1;
		if (red > NUMREDSHIFTS)
			red = NUMREDSHIFTS;

		damagecount -= tics;
		if (damagecount < 0)
			damagecount = 0;
	}
	else
		red = 0;

	if (red)
	{
		V_SetBlend(RPART(players[ConsolePlayer].mo->damagecolor),
                             GPART(players[ConsolePlayer].mo->damagecolor),
                             BPART(players[ConsolePlayer].mo->damagecolor), red*(174/NUMREDSHIFTS));
		palshifted = true;
	}
	else if(c7ChamberFlashCount > 0)
	{
		c7ChamberFlashCount = MAX(0, c7ChamberFlashCount-static_cast<int>(tics));
		V_SetBlend(0xFF, 0xF0, 0x00, 192);
		palshifted = true;
	}
	// The Invulnerability Sphere announces itself for as long as it is running:
	// the screen strobes yellow, which is the only thing that tells the player
	// the timer has not expired -- there is no counter for it on the status bar.
	// It sits below the damage and chamber flashes so a pickup still reads, and
	// above the pickup shimmer so it is not interrupted by one.
	else if(c7InvulnerabilityStrobe > 0)
	{
		// Eight tics lit, eight clear: fast enough to read as a strobe rather
		// than a pulse, slow enough to live with for the sphere's full 30
		// seconds. The dark half is a clean zero rather than a dim tint -- it
		// makes the strobe unmistakable, and it gives back an untinted view of
		// the level every other beat, which matters when the effect is on
		// screen for half a minute. The lit alpha is well below the health
		// chamber's 192 for the same reason.
		const bool lit = ((gamestate.TimeCount >> 3) & 1) != 0;
		V_SetBlend(0xFF, 0xF8, 0x00, lit ? 96 : 0);
		palshifted = true;
	}
	else if (white)
	{
		// [BL] More of a yellow if you ask me.
		V_SetBlend(0xFF, 0xF8, 0x00, white*(38/NUMWHITESHIFTS));
		palshifted = true;
	}
	else if (palshifted)
	{
		V_SetBlend(0, 0, 0, 0);
		palshifted = false;
	}
}


/*
=====================
=
= FinishPaletteShifts
=
= Resets palette to normal if needed
=
=====================
*/

void FinishPaletteShifts (void)
{
	damagecount = bonuscount = c7ChamberFlashCount = c7ElectricFlashCount = 0;
	V_SetCorridor7PaletteMode(0);

	if (palshifted)
	{
		V_SetBlend(0, 0, 0, 0);
		VH_UpdateScreen();
		palshifted = false;
	}
}


/*
=============================================================================

												CORE PLAYLOOP

=============================================================================
*/

/*
===================
=
= PlayFrame
=
===================
*/

// The 2D PlayFrame draws over the 3D view, split into pure function-pointer
// thunks for the renderer seam (see IRenderer::DrawViewOverlay). A compositing
// backend may run each of these more than once per frame, so they must draw and
// nothing else. They stay separate rather than merged into one call because the
// automap draws between them and must keep its place in the paint order.
static void DrawTopOverlayThunk()
{
	StatusBar->DrawTopOverlay();
}

static void DrawPausedOverlay()
{
	if(!(Paused & 1))
		return;

	// Corridor 7 has its own pause picture; it was being drawn as stencilled
	// text because the chunk holding it was still under its numeric name and
	// TexMan("PAUSED") found nothing. co7map.txt now names it, so both games
	// take the same path -- and the DOS release happens to put it at the same
	// place this always did: a DOSBox capture of the CD version matches the
	// 64x32 picture at exactly (128, 64), centered in the view above the status
	// bar.
	VWB_DrawGraphic(TexMan("PAUSED"), (20 - 4)*8, 80 - 2*8);
}

static void DrawC7MapOverlay()
{
	C7Map_Draw();
}

// Held rather than toggled: a scoreboard is something you glance at without
// letting go of anything else.
static void DrawScoreboardOverlay()
{
	if(Command::LocalUi().buttonstate[bt_scoreboard])
		C7Scoreboard_DrawOverlay();
}

void R_DrawPlayViewOverlays()
{
	DrawTopOverlayThunk();
	DrawC7MapOverlay();
	DrawScoreboardOverlay();
	DrawPausedOverlay();
}

void PlayFrame()
{
	// Palette-flash decay is simulation-rate state: advance it only on frames
	// where at least one tic elapsed so pure interpolation frames (tics == 0)
	// don't accelerate damage/bonus fades at high refresh rates. The tint stays
	// applied to the palette between updates.
	if(tics)
		UpdatePaletteShifts ();

	Capture::ApplyPaletteOverride(); // opt-in capture flash override (render test)

	// Interpolate actor/camera transforms for this frame, render, then restore
	// the authoritative simulation state. Apply/Restore are no-ops when
	// interpolation is disabled, so this path is unchanged in that case.
	Interpolation::Apply(R_GetInterpolationAlpha());
	Renderer->RenderScene(); // routed through the backend-neutral renderer seam
	Interpolation::Restore();
	// Routed through the renderer seam: this 2D lands over the 3D view, and a
	// compositing backend has to be told which texels it painted (see
	// IRenderer::DrawViewOverlay). The software backend just draws it.
	Renderer->DrawViewOverlay(DrawTopOverlayThunk);
	// Corridor 7's inset panel sits over the view in the same way, so it
	// goes through the same seam.
	Renderer->DrawViewOverlay(DrawC7MapOverlay);
	// And the standings, on the same seam. R_DrawPlayViewOverlays below is the
	// GL backend's coverage pass and is not the draw: an overlay added only
	// there is told about but never painted.
	Renderer->DrawViewOverlay(DrawScoreboardOverlay);

	if(automap && !gamestate.victoryflag)
		BasicOverhead();
	// PAUSED also lands over the 3D view -- and in Corridor 7 it carries the same
	// black drop shadow the top message does, which a key-based compositor cannot
	// see. Same seam, drawn after the automap so the paint order is unchanged.
	Renderer->DrawViewOverlay(DrawPausedOverlay);

	if(Net::IsBlocked())
	{
		ClearSplitVWB();
		Message("Waiting for players to return");
	}

	if (!loadedgame)
	{
		// Advance HUD animation at simulation rate; keep drawing every frame.
		if(tics)
			StatusBar->Tick();
		if ((gamestate.TimeCount & 1) || !(tics & 1))
			StatusBar->DrawStatusBar();
	}

	if (screenfaded)
	{
		VW_FadeIn ();
		ResetTimeCount();
	}

	VH_UpdateScreen();
}

/*
===================
=
= PlayLoop
=
===================
*/
int32_t funnyticount;


void PlayLoop (void)
{
#if 0 // USE_CLOUDSKY
	if(GetFeatureFlags() & FF_CLOUDSKY)
		InitSky();
#endif

	playstate = ex_stillplaying;
	ResetTimeCount();
	// A level entered from another one keeps its player pawn: FinishTravel moves
	// the surviving actor to the new map's start. Its render snapshot still holds
	// the OLD map's position, and Restore() writes that snapshot back into the
	// actor after the first frame is drawn -- teleporting the player to wherever
	// they stood on the previous level, which on most maps is inside a wall.
	//
	// DynamicWalls::Reset() already does this for doors and pushwalls in
	// SetupGameLevel; actors were missed. It has to happen here rather than
	// there, because SetupGameLevel runs BEFORE FinishTravel moves the pawn.
	Interpolation::Reset();
	// Decouple frame pacing from the 70 Hz simulation for smooth high-refresh
	// motion. Disabled cleanly on exit so intermission/animation loops keep the
	// legacy blocking timing.
	g_interpFrameTiming = r_interpolate;
	R_ResetFrameTiming();
	frameon = 0;
	funnyticount = 0;
	memset (control[ConsolePlayer].buttonstate, 0, sizeof (control[ConsolePlayer].buttonstate));
	ClearPaletteShifts ();

	if(automap != AMA_Off)
	{
			// Force the automap to off if it were previously on, unpause the game if am_pause
		automap = AMA_Off;

		if(am_pause) Paused &= ~2;
	}


	if (MousePresent && IN_IsInputGrabbed())
		IN_CenterMouse();         // Clear accumulated mouse movement

	if (demoplayback)
		IN_StartAck (ACK_Local);

	StatusBar->NewGame();

	do
	{
		NetWatch("playing");
		ProcessEvents();

//
// actor thinking
//
		madenoise = false;

		// Run tics
		for (unsigned int i = 0;i < tics;++i)
		{
			PollControls(!i);

			// Net code may require this loop to abort early
			if(playstate != ex_stillplaying)
				break;

			if(!Paused)
			{
				++gamestate.TimeCount;

				// Snapshot render history around the tic (current -> previous).
				Interpolation::BeginTic();
				DynamicWalls::BeginTic();

				Capture::PreTic(); // capture-time world overrides (opt-in)

				CheckSpawnPlayer();

				// With nobody else in the world, death stops it; with somebody
				// else in it, the world has to keep running for them. players[0]
				// is only reached when there is exactly one slot, which is the
				// local one.
				if(Session::HasMultiplePlayers() || players[0].state != player_t::PST_DEAD)
					thinkerList.Tick();
				else
					thinkerList.Tick(ThinkerList::PLAYER);

				AActor::FinishSpawningActors();

				// Capture post-tic transforms for interpolation, then fold the
				// deterministic state into the checksum (reads real, not
				// interpolated, state).
				Interpolation::EndTic();
				DynamicWalls::EndTic();

				Capture::PerTic(); // fold deterministic state into the checksum
			}
		}

		PlayFrame();

		Capture::PostFrame(); // screenshot-on-frame-N and capture auto-quit

		//
		// MAKE FUNNY FACE IF BJ DOESN'T MOVE FOR AWHILE
		//
		funnyticount += tics;

		TexMan.UpdateAnimations(lasttimecount*14);
		GC::CheckGC();

		UpdateSoundLoc ();      // JAB

		CheckKeys ();
		CheckDebugKeys ();

//
// debug aids
//
		if (singlestep)
		{
			VW_WaitVBL (singlestep);
			ResetTimeCount();
		}
		if (extravbls)
			VW_WaitVBL (extravbls);

		if (demoplayback)
		{
			if (IN_CheckAck ())
			{
				IN_ClearKeysDown ();
				playstate = ex_abort;
			}
		}
	}
	while (!playstate && !startgame);

	// Restore legacy blocking timing for intermission/animation loops.
	g_interpFrameTiming = false;

	if (playstate != ex_died)
		FinishPaletteShifts ();
}
