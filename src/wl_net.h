/*
** wl_net.h
**
**---------------------------------------------------------------------------
** Copyright 2014 Braden Obrzut
** All rights reserved.
**
** Redistribution and use in source and binary forms, with or without
** modification, are permitted provided that the following conditions
** are met:
**
** 1. Redistributions of source code must retain the above copyright
**    notice, this list of conditions and the following disclaimer.
** 2. Redistributions in binary form must reproduce the above copyright
**    notice, this list of conditions and the following disclaimer in the
**    documentation and/or other materials provided with the distribution.
** 3. The name of the author may not be used to endorse or promote products
**    derived from this software without specific prior written permission.
**
** THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
** IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
** OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
** IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
** INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
** NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
** DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
** THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
** (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
** THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
**---------------------------------------------------------------------------
**
**
*/ 

#ifndef __WL_NET_H__
#define __WL_NET_H__

#include <SDL_net.h>

#include "id_in.h"
#include "wl_def.h"
#include "zstring.h"

// The port the original's successors have used and the one the setup screen
// offers. Here rather than in the implementation because the menu needs it too.
#define NET_DEFAULT_PORT 5029

namespace Net {

typedef bool (*InitStatusCallback)(FString);

enum Mode
{
	MODE_SinglePlayer,
	MODE_Host,
	MODE_Client
};

enum GameMode
{
	GM_Cooperative,
	GM_Battle,
	// Corridor 7's team play, per the compendium's 9.5: players controlling
	// the same character cannot damage one another, and their kills count
	// together.
	GM_TeamBattle
};

struct NetInit
{
	Mode mode;
	GameMode gameMode;
	uint16_t port;
	byte numPlayers;
	const char* joinAddress;

	// How many tics ahead each player's commands are sent, so that a round
	// trip has that many tics to complete in rather than one. Zero is the
	// original behaviour: exchange the current tic and block until everyone
	// answers, which is free on a LAN and unusable over the internet -- at
	// 70 tics a second it needs a reply every 14.3ms. See
	// docs/multiplayer.md.
	byte ticDelay;
	// Kills that end a match, or 0 for a match that only ends when someone
	// leaves. Counted per team in team play, per player otherwise.
	byte fragLimit;
};

extern NetInit InitVars;

bool IsArbiter();
bool IsBlocked();
void BlockPlaysim();
void DebugKey(const struct DebugCmd &cmd);
void EndGame();
void Init(InitStatusCallback callback);
void NewGame(int &difficulty, class FString &map, class FName (&playerClassNames)[MAXPLAYERS]);
void PollControls();

bool CheckAck(bool send);
void StartAck(AckType type);

// TODO: Redo these as proper options (and probably move to wl_game or something)
//
// Everything that used to ask "is this GM_Battle" was really asking "is this a
// deathmatch", and answered wrongly the moment a second deathmatch mode
// existed. Team play has no monsters and respawns items exactly as free-for-all
// does; the only thing it changes is who may shoot whom.
static bool Deathmatch() { return InitVars.gameMode != GM_Cooperative; }
static bool RespawnItems() { return Deathmatch(); }
static bool NoMonsters() { return Deathmatch(); }

// Which side a player is on. Two teams, and the intent is that a team is the
// character you chose -- 9.5 describes them as the same thing. The characters
// arrive in M5; until then the sides are dealt by player number, which every
// machine already agrees on and so needs nothing on the wire.
byte PlayerTeam(unsigned int player);

// Kills for a side: every member's frags added up, which is what 9.5 means by
// team kills aggregating.
int TeamFrags(byte team);

// May this attacker hurt this target?
//
// This replaced a global FriendlyFire() flag, which could only answer "is
// player-versus-player on at all". That is the wrong shape of question for a
// mode whose whole rule is that the answer depends on which two players are
// involved.
bool CanDamage(const AActor *attacker, const AActor *target);

}

#endif
