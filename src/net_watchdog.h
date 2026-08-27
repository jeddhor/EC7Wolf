/*
** net_watchdog.h
**
** A netgame that stops has, so far, said nothing useful about where it
** stopped. The engine's network waits all announce themselves -- "Waiting 3s
** for tic 225 from player 2" -- but that only tells you which machine went
** quiet, not what the quiet one is doing. Chasing one of these by hand cost an
** afternoon and did not find it: the evidence (a pegged CPU and a receive queue
** filling up unread) proved only that the stuck machine was in *some* loop that
** does no networking, which is most of the engine.
**
** So each loop that can run long says which one it is, and a watchdog thread
** reports that periodically while a netgame is up. The freeze then names
** itself, on a phone as readily as on a desktop, because it goes through
** Printf and so reaches logcat.
**
** Cost when nothing is wrong: one string assignment and one increment per
** iteration of loops that were already doing far more than that.
*/

#ifndef __NET_WATCHDOG_H__
#define __NET_WATCHDOG_H__

#include <stdint.h>

// Where the main thread currently is. Assigned, never freed -- always a string
// literal, so the watchdog thread can read it without a lock.
extern const char * volatile NetWatch_Phase;
// Bumped by whichever loop is running. A phase whose counter has stopped is
// stuck; a phase whose counter climbs while the game is frozen is spinning.
extern volatile uint64_t NetWatch_Tick;

inline void NetWatch(const char *phase)
{
	NetWatch_Phase = phase;
	++NetWatch_Tick;
}

// Set by --netwatchdog.
extern bool netwatchdog;

// Starts once a netgame is running; does nothing in single player, and nothing
// at all unless netwatchdog is on.
void NetWatch_Start();
void NetWatch_Stop();

#endif
