/*
** net_watchdog.cpp
**
** See net_watchdog.h. The reporting thread only reads; the game thread only
** writes. Neither takes a lock, because the worst a torn read can do is name
** the wrong loop for one line, and a diagnostic that can deadlock the thing it
** is diagnosing would be worse than none.
*/

#include <SDL.h>

#include "wl_def.h"
#include "net_watchdog.h"
#include "wl_game.h"
#include "wl_net.h"
#include "wl_play.h"

const char * volatile NetWatch_Phase = "starting";
volatile uint64_t NetWatch_Tick = 0;

// Off by default: this prints every few seconds for as long as a netgame lasts,
// which is exactly what you want while hunting a freeze and exactly what you do
// not want otherwise. Turned on with --netwatchdog, which on Android goes in
// the launcher's Args box like any other argument.
bool netwatchdog = false;

static SDL_Thread *WatchThread = NULL;
static volatile bool WatchRunning = false;

static int WatchMain(void *)
{
	uint64_t lastTick = 0;
	int32_t lastTime = 0;
	unsigned int quiet = 0;

	while(WatchRunning)
	{
		// Two seconds is short enough to catch a freeze while the player still
		// remembers what they pressed, and long enough not to bury the log.
		for(int i = 0;i < 20 && WatchRunning;++i)
			SDL_Delay(100);
		if(!WatchRunning)
			break;

		const uint64_t tick = NetWatch_Tick;
		const char *phase = NetWatch_Phase;
		const int32_t timeCount = gamestate.TimeCount;

		// A game that is simulating is a game that is fine. Say nothing.
		if(timeCount != lastTime)
		{
			lastTime = timeCount;
			lastTick = tick;
			quiet = 0;
			continue;
		}

		quiet += 2;
		// "spinning" and "stuck" are different faults and want different
		// answers: one is a loop that will not exit, the other is a loop that
		// has stopped being run at all.
		Printf("NETWATCH: playsim has not advanced for %us -- in '%s', which is %s (tic=%d)\n",
			quiet, phase != NULL ? phase : "?",
			tick != lastTick ? "spinning" : "stuck",
			(int)timeCount);
		lastTick = tick;
	}
	return 0;
}

void NetWatch_Start()
{
	if(WatchThread != NULL || !netwatchdog)
		return;
	if(!Net::IsNetworked())
		return;

	WatchRunning = true;
	WatchThread = SDL_CreateThread(WatchMain, "netwatch", NULL);
	if(WatchThread == NULL)
	{
		WatchRunning = false;
		Printf("NETWATCH: could not start the watchdog thread\n");
		return;
	}
	Printf("NETWATCH: watching. Set netwatchdog 0 to silence it.\n");
}

void NetWatch_Stop()
{
	if(WatchThread == NULL)
		return;
	WatchRunning = false;
	SDL_WaitThread(WatchThread, NULL);
	WatchThread = NULL;
}
