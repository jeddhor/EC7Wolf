/*
** wl_net.cpp
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


#include "wl_def.h"
#include "id_in.h"
#include "id_us.h"
#include "id_vh.h"
#include "g_mapinfo.h"
#include "thingdef/thingdef.h"
#include "wl_agent.h"
#include "wl_debug.h"
#include "wl_game.h"
#include "wl_menu.h"
#include "wl_play.h"
#include "wl_net.h"
#include "net_watchdog.h"
#include "m_swap.h"
#include "m_random.h"
#include "doomerrors.h"
#include "zdoomsupport.h"
#include "zstring.h"

#include <SDL.h>
#include <SDL_net.h>
#include <cassert>
#include <climits>

// Deep enough to hold a whole delay window of commands per player, plus room
// for them to arrive out of order. Four was enough when nothing was ever sent
// early; with input delay, every command is.
#define MAXEXTRATICS 64

// TODO: Handle transfer of arbiter status as client quit
#define Arbiter 0

namespace Net {

enum
{
	NET_RequestConnection,
	NET_ConnectionStart,
	NET_Ack,
	NET_TicCmd,
	NET_NewGame,
	NET_BlockPlaysim,
	NET_InAck,
	NET_DebugCmd,
	NET_EndGame,
};

#pragma pack(1)
// Convert player class FName to stable index
struct PlayerClass
{
	uint32_t index;

	static PlayerClass FromName(FName className)
	{
		for(uint32_t i = 0;i < gameinfo.PlayerClasses.Size();++i)
		{
			if(gameinfo.PlayerClasses[i] == className)
			{
				PlayerClass ret = {i};
				return ret;
			}
		}
		PlayerClass ret = {0};
		return ret;
	}

	operator FName() const
	{
		if(index < gameinfo.PlayerClasses.Size())
			return gameinfo.PlayerClasses[index];
		return NAME_None;
	}
};

struct RequestPacket
{
	// This could be static const BYTE, but I know old Mac compilers I use
	// sometimes have problems with that. :(
	enum { Type = NET_RequestConnection };

	BYTE type;

	void ByteSwap() {}
};

struct StartPacket
{
	enum { Type = NET_ConnectionStart };

	BYTE type;
	BYTE playerNumber;
	BYTE numPlayers;
	BYTE gameMode;
	// The host's, and everyone's. Input delay sets how far ahead commands are
	// stamped, so two players using different windows disagree about which tic
	// a command belongs to -- their warm-ups differ and their sequences never
	// line up. It is a property of the game, not of a preference, so it comes
	// down the wire with the rest of it.
	BYTE ticDelay;
	BYTE fragLimit;
	DWORD rngseed;
	struct Client
	{
		DWORD host;
		WORD port;
	} clients[];

	void ByteSwap()
	{
		rngseed = LittleLong(rngseed);
		for(BYTE i = 0;i < numPlayers;++i)
		{
			clients[i].host = LittleLong(clients[i].host);
			clients[i].port = LittleShort(clients[i].port);
		}
	}
};

struct NewGamePacket
{
	enum { Type = NET_NewGame };

	BYTE type;
	int32_t TimeCount;
	PlayerClass playerClass;
	BYTE difficulty;
	char map[9];

	void ByteSwap()
	{
		TimeCount = LittleLong(TimeCount);
		playerClass.index = LittleLong(playerClass.index);
	}
};

struct AckPacket
{
	enum { Type = NET_Ack };

	BYTE type;
	BYTE ackedType;
	int32_t TimeCount;

	void ByteSwap()
	{
		TimeCount = LittleLong(TimeCount);
	}
};

struct TicCmdPacket
{
	enum { Type = NET_TicCmd };

	BYTE type;
	int32_t TimeCount;
	int32_t controlx;
	int32_t controly;
	int32_t controlstrafe;
	BYTE buttonstate[NUMBUTTONS];
	BYTE buttonheld[NUMBUTTONS];

	void ByteSwap()
	{
		TimeCount = LittleLong(TimeCount);
		controlx = LittleLong(controlx);
		controly = LittleLong(controly);
		controlstrafe = LittleLong(controlstrafe);
	}
};

// Indicates that a player has temporarily left the playsim and other clients
// must wait for them to return.
struct BlockPlaysimPacket
{
	enum { Type = NET_BlockPlaysim };

	BYTE type;
	int32_t TimeCount;

	void ByteSwap()
	{
		TimeCount = LittleLong(TimeCount);
	}
};

// Waiting for some player to press a key
struct InAckPacket
{
	enum { Type = NET_InAck };

	BYTE type;
	int32_t TimeCount;
	uint32_t Number;

	void ByteSwap()
	{
		TimeCount = LittleLong(TimeCount);
		Number = LittleLong(Number);
	}
};

struct DebugCmdPacket
{
	enum { Type = NET_DebugCmd };

	BYTE type;
	int32_t TimeCount;
	int32_t CommandType;
	int32_t ArgI;
	char ArgS[256];

	void ByteSwap()
	{
		TimeCount = LittleLong(TimeCount);
		CommandType = LittleLong(CommandType);
		ArgI = LittleLong(ArgI);
	}

	// Returns false if truncated
	bool SetArgS(FString str)
	{
		strncpy(ArgS, str, sizeof(ArgS));
		ArgS[sizeof(ArgS)-1] = 0;
		return strlen(ArgS) == str.Len();
	}
};

struct EndGamePacket
{
	enum { Type = NET_EndGame };

	BYTE type;
	int32_t TimeCount;

	void ByteSwap()
	{
		TimeCount = LittleLong(TimeCount);
	}
};
#pragma pack()

NetInit InitVars = {
	MODE_SinglePlayer,
	GM_Cooperative,
	NET_DEFAULT_PORT,
	1,
	NULL,
	0,
	0,
};

struct NetClient
{
	IPaddress address;
	TicCmdPacket extratics[MAXEXTRATICS];
	unsigned short extrapos;
};

static NetClient Client[MAXPLAYERS];
static UDPsocket Socket;
static UDPpacket *Packet;
static int32_t PlaysimBlocked = INT_MIN;

static AckType AwaitingAckType = ACK_Local;
static uint32_t AwaitingAck = 0;
static uint32_t DidAck = 0;

// Just so that we know something is happening do a little animation.
static const char* const Waiting[4] = {"   ", ".  ", ".. ", "..." };

static FString IPaddressToString(IPaddress address)
{
	FString out;
	out.Format("%u.%u.%u.%u:%d", address.host&0xFF, (address.host&0xFF00)>>8, (address.host&0xFF0000)>>16, (address.host&0xFF000000)>>24, BigShort(address.port));
	return out;
}

// Returns the player number for a given ip address
static int FindClient(IPaddress address)
{
	for(unsigned int i = 0;i < InitVars.numPlayers;++i)
	{
		if(Client[i].address.host == address.host && Client[i].address.port == address.port)
			return i;
	}
	return -1;
}

static void DoEndGame()
{
	playstate = ex_died;
	for(unsigned int i = 0;i < Net::InitVars.numPlayers;++i)
	{
		players[i].lives = 0;
		players[i].killerobj = NULL;
		players[i].mo->Die();
	}
}

// Check if we have a potentially valid packet of a certain type
template<typename T>
static bool CheckPacketType(const UDPpacket *packet)
{
	if(packet->len >= (signed)sizeof(T) && ((T*)packet->data)->type == T::Type)
	{
		((T*)packet->data)->ByteSwap();
		return true;
	}
	return false;
}

// Sends an ACK packet to a given address
template<typename T>
static void SendAck(IPaddress address, int32_t TimeCount)
{
	AckPacket ackData;
	ackData.type = AckPacket::Type;
	ackData.ackedType = T::Type;
	ackData.TimeCount = TimeCount;
	ackData.ByteSwap();
	UDPpacket packet = { -1, (Uint8*)&ackData, sizeof(AckPacket), sizeof(AckPacket), 0, address };

	SDLNet_UDP_Send(Socket, -1, &packet);
}

template<typename T>
bool BufferPacket(int client, const T &packet)
{
	return false;
}

template<>
bool BufferPacket<TicCmdPacket>(int client, const TicCmdPacket &packet)
{
	if(packet.TimeCount > gamestate.TimeCount)
	{
		Client[client].extratics[Client[client].extrapos] = packet;
		Client[client].extrapos = (Client[client].extrapos+1)%MAXEXTRATICS;
	}
	return true;
}

template<typename T>
int UnbufferPacket(T (&packets)[MAXPLAYERS], bool (&received)[MAXPLAYERS])
{
	return 0;
}

template<>
int UnbufferPacket<TicCmdPacket>(TicCmdPacket (&packets)[MAXPLAYERS], bool (&received)[MAXPLAYERS])
{
	int unbufferedCount = 0;
	for(unsigned int i = 0;i < MAXEXTRATICS;++i)
	{
		for(unsigned int c = 0;c < InitVars.numPlayers;++c)
		{
			if(c == ConsolePlayer)
				continue;

			if(Client[c].extratics[i].TimeCount != 0 && Client[c].extratics[i].TimeCount == gamestate.TimeCount)
			{
				packets[c] = Client[c].extratics[i];
				Client[c].extratics[i].TimeCount = 0;
				if(received[c])
					continue;
				received[c] = true;
				++unbufferedCount;
			}
		}
	}
	return unbufferedCount;
}

static void HandleCommandPackets()
{
	if(CheckPacketType<BlockPlaysimPacket>(Packet))
	{
		const BlockPlaysimPacket *data = reinterpret_cast<BlockPlaysimPacket *>(Packet->data);

		SendAck<BlockPlaysimPacket>(Packet->address, data->TimeCount);
		if(data->TimeCount < gamestate.TimeCount-1) // Too old?
			return;

		PlaysimBlocked = data->TimeCount;
		PlayFrame();
	}
	else if(CheckPacketType<DebugCmdPacket>(Packet))
	{
		const DebugCmdPacket *data = reinterpret_cast<DebugCmdPacket *>(Packet->data);

		SendAck<DebugCmdPacket>(Packet->address, data->TimeCount);
		if(data->TimeCount != gamestate.TimeCount)
			Printf("Desync: Debug key command for tic %d arrived on %d\n", data->TimeCount, gamestate.TimeCount);

		int client = FindClient(Packet->address);
		if(client < 0)
		{
			Printf("Packet recieved from unknown source\n");
			return;
		}

		DebugCmd cmd;
		cmd.Type = static_cast<EDebugCmd>(data->CommandType);
		cmd.ArgI = data->ArgI;
		// ArgS is a fixed 256 bytes in the packet and nothing obliges a sender
		// to put a terminator in it. Handing that straight to FString reads off
		// the end of the datagram looking for one.
		cmd.ArgS = FString(data->ArgS,
			strnlen(data->ArgS, sizeof(data->ArgS)));
		DoDebugKey(client, cmd);
	}
	else if(CheckPacketType<EndGamePacket>(Packet))
	{
		const EndGamePacket *data = reinterpret_cast<EndGamePacket *>(Packet->data);

		SendAck<EndGamePacket>(Packet->address, data->TimeCount);
		DoEndGame();
	}
	else if(CheckPacketType<InAckPacket>(Packet))
	{
		const InAckPacket *data = reinterpret_cast<InAckPacket *>(Packet->data);

		SendAck<InAckPacket>(Packet->address, data->TimeCount);
		if(data->Number != AwaitingAck)
		{
			Printf("Received wrong ACK %d\n", data->Number);
			return;
		}

		DidAck = data->Number;
	}
	else if(CheckPacketType<StartPacket>(Packet))
	{
		// Host lost our start ack, so send another one
		SendAck<StartPacket>(Client[0].address, 0xFFFFFFFF);
	}
}

// Synchronously exchange a packet to all players and wait for ACK
template<typename T>
static void ExchangePacket(T (&packets)[MAXPLAYERS])
{
	bool acked[MAXPLAYERS] = { false };
	bool received[MAXPLAYERS] = { false };
	int numAcked = 1, numReceived = 1;
	acked[ConsolePlayer] = true;
	received[ConsolePlayer] = true;

	numReceived += UnbufferPacket(packets, received);

	UDPpacket outPacket = { -1, (Uint8*)&packets[ConsolePlayer], sizeof(T), sizeof(T), 0 };
	packets[ConsolePlayer].type = T::Type;
	packets[ConsolePlayer].TimeCount = gamestate.TimeCount;
	packets[ConsolePlayer].ByteSwap();

	// We need to keep an eye out for packets, but we also need to periodically
	// resend our packet in case it got lost.
	unsigned int resend = 0;
	bool waiting = false;
	// A synchronous exchange that cannot finish used to say nothing whatever:
	// the game simply stopped, with no indication of which player it was
	// waiting on or whether it was waiting to be heard or to hear. Both halves
	// matter, because they fail for different reasons -- a missing ack means
	// our packet is not arriving, a missing packet means theirs is not.
	unsigned int stuckFor = 0;
	while(numAcked != InitVars.numPlayers || numReceived != InitVars.numPlayers)
	{
		NetWatch("net: exchanging a tic");
		if(++stuckFor % 3000 == 0)
		{
			FString missing;
			for(unsigned int i = 0;i < InitVars.numPlayers;++i)
			{
				if(i == (unsigned)ConsolePlayer)
					continue;
				if(!received[i])
					missing.AppendFormat(" %u(no packet)", i + 1);
				else if(!acked[i])
					missing.AppendFormat(" %u(no ack)", i + 1);
			}
			Printf("Still exchanging tic %d after %us, waiting on:%s\n",
				(int)gamestate.TimeCount, stuckFor/1000,
				missing.IsEmpty() ? " nobody -- which should be impossible" :
					missing.GetChars());
		}
		if(resend == 0)
		{
			for(unsigned int i = 0;i < InitVars.numPlayers;++i)
			{
				if(acked[i])
					continue;

				outPacket.address = Client[i].address;
				SDLNet_UDP_Send(Socket, -1, &outPacket);
			}
			resend = 100;
		}

		--resend;
		IN_ProcessEvents();

		if(!waiting)
			waiting = true;
		else
		{
			// Allow user to enter control panels even if we're waiting for data
			if(ingame)
				CheckKeys();
			SDL_Delay(1);
		}

		while(SDLNet_UDP_Recv(Socket, Packet))
		{
			if(CheckPacketType<T>(Packet))
			{
				int client = FindClient(Packet->address);
				if(client < 0)
				{
					Printf("Packet recieved from unknown source\n");
					continue;
				}

				T &data = *reinterpret_cast<T *>(Packet->data);

				if(data.TimeCount != gamestate.TimeCount)
				{
					if(BufferPacket<T>(client, data))
						SendAck<T>(Packet->address, data.TimeCount);
					continue;
				}

				SendAck<T>(Packet->address, data.TimeCount);

				if(received[client])
					continue;
				received[client] = true;
				packets[client] = data;
				++numReceived;
			}
			else if(CheckPacketType<AckPacket>(Packet))
			{
				const AckPacket *data = reinterpret_cast<AckPacket *>(Packet->data);
				if(data->TimeCount != gamestate.TimeCount || data->ackedType != T::Type)
					continue;

				int client = FindClient(Packet->address);
				if(client < 0)
				{
					Printf("Packet recieved from unknown source\n");
					continue;
				}
				if(acked[client])
					continue;

				acked[client] = true;
				++numAcked;
			}
			else
			{
				HandleCommandPackets();
			}
		}

		// If a debug command changes the play state then we should abort
		if((int)T::Type == NET_TicCmd && playstate != ex_stillplaying)
			break;
	}
}

// Synchronously send a packet to all players and wait for ACK
template<typename T>
static void SendReliablePacket(T &packet)
{
	bool acked[MAXPLAYERS] = { false };
	int numAcked = 1;
	acked[ConsolePlayer] = true;

	UDPpacket outPacket = { -1, (Uint8*)&packet, sizeof(T), sizeof(T), 0 };
	packet.type = T::Type;
	packet.TimeCount = gamestate.TimeCount;
	packet.ByteSwap();

	// We need to keep an eye out for packets, but we also need to periodically
	// resend our packet in case it got lost.
	unsigned int resend = 0;
	bool waiting = false;
	while(numAcked != InitVars.numPlayers)
	{
		NetWatch("net: waiting for an ack");
		if(resend == 0)
		{
			for(unsigned int i = 0;i < InitVars.numPlayers;++i)
			{
				if(acked[i])
					continue;

				outPacket.address = Client[i].address;
				SDLNet_UDP_Send(Socket, -1, &outPacket);
			}
			resend = 100;
		}

		--resend;

		if(!waiting)
			waiting = true;
		else
		{
			LastScan = 0;
			IN_ProcessEvents();

			// Allow user to enter control panels even if we're waiting for data
			if(ingame && T::Type != (int)NET_BlockPlaysim)
				CheckKeys();
			SDL_Delay(1);
		}

		while(SDLNet_UDP_Recv(Socket, Packet))
		{
			if(CheckPacketType<AckPacket>(Packet))
			{
				const AckPacket *data = reinterpret_cast<AckPacket *>(Packet->data);
				if(data->TimeCount != gamestate.TimeCount || data->ackedType != T::Type)
					continue;

				int client = FindClient(Packet->address);
				if(client < 0)
				{
					Printf("Packet recieved from unknown source\n");
					continue;
				}
				if(acked[client])
					continue;

				acked[client] = true;
				++numAcked;
			}
			else
			{
				HandleCommandPackets();
			}
		}
	}
}

// A waiting screen has one job beyond waiting: to look unlike a crash. What it
// takes to do that is a picture that keeps moving and a sentence that says what
// is being waited for -- neither of which belongs here. This fills in the facts
// and lets whoever is drawing decide how to show them.
static void FillPeers(InitStatus &status, const bool acked[MAXPLAYERS])
{
	status.peers.Clear();
	for(unsigned int i = 1;i < InitVars.numPlayers;++i)
	{
		InitStatus::Peer peer;
		peer.name.Format("Player %u", i + 1);
		if(!Client[i].address.host)
			peer.state = "waiting";
		else if(acked[i])
			peer.state = "ready";
		else
			peer.state = IPaddressToString(Client[i].address);
		status.peers.Push(peer);
	}
}

// Every field of a start packet is a number a stranger chose.
//
// CheckPacketType only proves the packet is at least sizeof(T) and carries the
// right type byte. That is enough for the fixed-size packets and not enough for
// this one, which ends in a client array whose length is declared by a byte
// inside the packet -- so the size that matters is not the size of the struct.
//
// What the unchecked version allowed, from one forged UDP datagram: numPlayers
// up to 255 walking Client[MAXPLAYERS] off the end of itself and writing as it
// went, playerNumber up to 255 becoming an index into players[], a gameMode
// outside the enum, and a tic delay large enough to swamp the extratics ring.
// A client sitting on a "waiting for sync" screen is the most exposed the game
// ever is: it is holding an open socket, it has told nobody where it is, and
// it will believe the first thing that answers.
static bool ValidStartPacket(const StartPacket *data, int len)
{
	if(data->numPlayers < 1 || data->numPlayers > MAXPLAYERS)
		return false;
	if(data->playerNumber >= data->numPlayers)
		return false;
	if(data->gameMode > GM_TeamBattle)
		return false;
	// The delayed path stamps commands this far ahead and holds them in a ring
	// of MAXEXTRATICS; half of that leaves room for the tics still in flight.
	if(data->ticDelay > MAXEXTRATICS/2)
		return false;

	// The array the packet says it has, rather than the one the struct
	// declares: sizeof(StartPacket) counts none of it.
	const size_t needed =
		sizeof(StartPacket) + sizeof(StartPacket::Client)*(data->numPlayers - 1);
	if(len < 0 || (size_t)len < needed)
		return false;

	return true;
}

static bool StartHost(InitStatusCallback callback)
{
	unsigned int waitpos = 0;
	unsigned int nextclient = 1; // 0 is the host
	bool acked[MAXPLAYERS] = { false };

	if(!(Socket = SDLNet_UDP_Open(InitVars.port)))
		throw CFatalError("Could not open UDP socket.");

	// --host takes whatever number it is given, and Client[] holds MAXPLAYERS.
	if(InitVars.numPlayers < 1)
		InitVars.numPlayers = 1;
	if(InitVars.numPlayers > MAXPLAYERS)
		InitVars.numPlayers = MAXPLAYERS;

	// Step 1: Get connection requests from each player
	Printf("Waiting for %d players:\n   ", InitVars.numPlayers);

	InitStatus status;
	status.phase = InitStatus::PHASE_Hosting;
	status.detail.Format("port %u", (unsigned)InitVars.port);
	status.seconds = 0;
	FillPeers(status, acked);
	if(!callback(status))
		return false;

	const uint32_t hostStart = SDL_GetTicks();
	uint32_t lastSpin = hostStart;
	while(nextclient != InitVars.numPlayers)
	{
		// Redrawn at something like a frame rate rather than once per socket
		// poll: a waiting screen that only moves when a packet arrives is a
		// waiting screen that does not move.
		status.seconds = (SDL_GetTicks() - hostStart)/1000;
		FillPeers(status, acked);
		if(!callback(status))
			return false;

		if(SDL_GetTicks() - lastSpin >= 400)
		{
			lastSpin = SDL_GetTicks();
			waitpos = (waitpos+1)%4;
			Printf("\b\b\b%s", Waiting[waitpos]);
			fflush(stdout);
		}

		if(SDLNet_UDP_Recv(Socket, Packet))
		{
			const RequestPacket *data = reinterpret_cast<RequestPacket*>(Packet->data);
			if(CheckPacketType<RequestPacket>(Packet))
			{
				Printf("\b\b\b");

				int client = FindClient(Packet->address);
				if(client == -1)
				{
					Printf("[%d] New connection from %u.%u.%u.%u:%u!\n", nextclient, Packet->address.host&0xFF, (Packet->address.host&0xFF00)>>8, (Packet->address.host&0xFF0000)>>16, (Packet->address.host&0xFF000000)>>24, BigShort(Packet->address.port));
					Client[nextclient++].address = Packet->address;
					FillPeers(status, acked);
					if(!callback(status))
						return false;
				}

				Printf("   ");
			}
		}
		else
		{
			SDL_Delay(16);
			IN_ProcessEvents();
		}
	}

	// Once we found all of the players, send a syncronization packet which
	// contains anything needs to start the game as well as the address of each
	// other player in the game (they already know the host).
	Printf("\b\b\bAll players connected! Sending sync...\n");

	const int startSize = sizeof(StartPacket) + sizeof(StartPacket::Client)*(InitVars.numPlayers-1);
	StartPacket *startData = (StartPacket *)malloc(startSize);
	UDPpacket startPacket = { -1, (Uint8*)startData, startSize, startSize, 0 };
	startData->type = StartPacket::Type;
	startData->numPlayers = InitVars.numPlayers;
	startData->gameMode = InitVars.gameMode;
	startData->ticDelay = InitVars.ticDelay;
	startData->fragLimit = InitVars.fragLimit;
	startData->rngseed = rngseed;
	for(unsigned int i = 1;i < InitVars.numPlayers;++i)
	{
		startData->clients[i-1].host = Client[i].address.host;
		startData->clients[i-1].port = Client[i].address.port;
	}
	startData->ByteSwap();

	nextclient = 1;
	uint32_t lastSend = 0;
	while(nextclient != InitVars.numPlayers)
	{
		// Resent on a clock rather than once per pass, so that the redraw
		// below can run at a frame rate without turning into a packet flood.
		if(lastSend == 0 || SDL_GetTicks() - lastSend >= 100)
		{
			lastSend = SDL_GetTicks();
			// Send off start packet to players who have not acked
			for(unsigned int i = 1;i < InitVars.numPlayers;++i)
			{
				if(acked[i])
					continue;

				startPacket.address = Client[i].address;
				startData->playerNumber = i;

				SDLNet_UDP_Send(Socket, -1, &startPacket);
			}
		}

		status.seconds = (SDL_GetTicks() - hostStart)/1000;
		FillPeers(status, acked);
		if(!callback(status))
			return false;

		SDL_Delay(16);
		IN_ProcessEvents();

		// Look for ack packets
		while(SDLNet_UDP_Recv(Socket, Packet))
		{
			const AckPacket *data = reinterpret_cast<AckPacket*>(Packet->data);
			if(CheckPacketType<AckPacket>(Packet))
			{
				int client = FindClient(Packet->address);
				if(client > 0 && !acked[client])
				{
					acked[client] = true;
					++nextclient;
					FillPeers(status, acked);
					if(!callback(status))
						return false;
				}
			}
		}
	}

	free(startData);

	Printf("All acked starting game!\n");
	return true;
}

static bool StartJoin(InitStatusCallback callback)
{
	unsigned int waitpos = 0;
	if(!(Socket = SDLNet_UDP_Open(InitVars.port)))
		throw CFatalError("Could not open UDP socket.");
	IPaddress address;

	// Convert join string to IPaddress
	FString addrString(InitVars.joinAddress);
	uint16_t port = NET_DEFAULT_PORT;
	if(addrString.IndexOf(':') != -1)
	{
		long pos = addrString.IndexOf(':');
		port = atoi(addrString.Mid(pos+1));
		addrString = addrString.Left(pos);
	}
	SDLNet_ResolveHost(&address, addrString, port);

	Printf("Attempting to connect to %u.%u.%u.%u:%u :\n   ", address.host&0xFF, (address.host&0xFF00)>>8, (address.host&0xFF0000)>>16, (address.host&0xFF000000)>>24, BigShort(address.port));

	// Send a connection request to host
	Uint8 requestData[] = {NET_RequestConnection};
	UDPpacket packet = { -1, requestData, 1, 1, 0, address };

	InitStatus status;
	status.phase = InitStatus::PHASE_Joining;
	status.detail = IPaddressToString(address);
	status.seconds = 0;
	if(!callback(status))
		return false;

	const uint32_t joinStart = SDL_GetTicks();
	uint32_t lastSpin = joinStart, lastRequest = 0;
	for(;;)
	{
		status.seconds = (SDL_GetTicks() - joinStart)/1000;
		if(!callback(status))
			return false;

		if(SDL_GetTicks() - lastSpin >= 400)
		{
			lastSpin = SDL_GetTicks();
			waitpos = (waitpos+1)%4;
			Printf("\b\b\b%s", Waiting[waitpos]);
			fflush(stdout);
		}

		// Send request periodically as a heart beat. On a clock, because the
		// loop below now runs at a frame rate rather than ten times a second.
		if(lastRequest == 0 || SDL_GetTicks() - lastRequest >= 400)
		{
			lastRequest = SDL_GetTicks();
			SDLNet_UDP_Send(Socket, -1, &packet);
		}

		// Look for start sync packets
		if(SDLNet_UDP_Recv(Socket, Packet))
		{
			const StartPacket *data = reinterpret_cast<StartPacket *>(Packet->data);
			// Only from the host actually dialled. Without this the client
			// takes its player number, its player count and the addresses of
			// everyone else in the game from whoever answers first.
			if(Packet->address.host != address.host ||
				Packet->address.port != address.port)
				continue;
			if(CheckPacketType<StartPacket>(Packet))
			{
				if(!ValidStartPacket(data, Packet->len))
				{
					// Counted and reported at most once a second: somebody
					// firing these is firing a great many, and a line each
					// would bury everything else in the log. Flushed, because
					// this is the one thing here worth reading promptly, and
					// stdout to a file does not flush itself in time to be
					// read by anyone wondering what is going on.
					static uint32_t lastReport = 0;
					static unsigned int rejected = 0;
					++rejected;
					if(lastReport == 0 || SDL_GetTicks() - lastReport >= 1000)
					{
						lastReport = SDL_GetTicks();
						Printf("Rejected %u malformed start packet%s.\n",
							rejected, rejected == 1 ? "" : "s");
						fflush(stdout);
						rejected = 0;
					}
					continue;
				}

				ConsolePlayer = data->playerNumber;
				InitVars.numPlayers = data->numPlayers;
				InitVars.gameMode = static_cast<GameMode>(data->gameMode);
				// The host's window, not whatever this machine chose: see
				// StartPacket.
				InitVars.ticDelay = data->ticDelay;
				InitVars.fragLimit = data->fragLimit;
				rngseed = data->rngseed;

				Client[0].address = Packet->address;
				for(unsigned int i = 1;i < InitVars.numPlayers;++i)
				{
					Client[i].address.host = data->clients[i-1].host;
					Client[i].address.port = data->clients[i-1].port;
				}
				break;
			}
		}
		else
		{
			SDL_Delay(16);
			IN_ProcessEvents();
		}
	}

	Printf("\b\b\bRecieved sync from host! Sending ack...\n");
	status.detail = "Synchronised";
	callback(status);

	// Send ACK and forget, if we're waiting for ticcmd and we get a start, we'll send another ack then.
	SendAck<StartPacket>(address, 0xFFFFFFFF);
	return true;
}

static void Shutdown()
{
	// Registered with atterm and also called when a player abandons the wait,
	// so this runs twice on that path. Freeing twice is a crash on the way out
	// of an otherwise successful session, which is the worst possible time.
	if(Packet != NULL)
	{
		SDLNet_FreePacket(Packet);
		Packet = NULL;
	}
	if(Socket != NULL)
	{
		SDLNet_UDP_Close(Socket);
		Socket = NULL;
	}
}

// False when the player gave up waiting, in which case nothing was started and
// the caller must go back to where it came from rather than into a game.
bool Init(InitStatusCallback callback)
{
	if(InitVars.mode == MODE_SinglePlayer)
		return true;

	if(SDLNet_Init() < 0)
	{
		I_FatalError("Unable to init SDL_net: %s", SDLNet_GetError());
	}

	Packet = SDLNet_AllocPacket(1500);
	atterm(Shutdown);

	const bool connected = (InitVars.mode == MODE_Host)
		? StartHost(callback)
		: StartJoin(callback);

	if(!connected)
	{
		// Give the socket back rather than holding the port until the process
		// ends: the player who just cancelled is quite likely to try again on
		// the same port a moment later, and "address already in use" would be
		// a baffling thing to meet on the second attempt.
		Shutdown();
		InitVars.mode = MODE_SinglePlayer;
		ConsolePlayer = 0;
	}
	return connected;
}

bool IsArbiter()
{
	return ConsolePlayer == Arbiter;
}

bool IsBlocked()
{
	return PlaysimBlocked != INT_MIN;
}

void BlockPlaysim()
{
	if(InitVars.mode == MODE_SinglePlayer)
		return;

	if(!IsBlocked())
	{
		BlockPlaysimPacket packet;
		SendReliablePacket(packet);

		PlaysimBlocked = gamestate.TimeCount;
	}
}

void DebugKey(const DebugCmd &cmd)
{
	if(InitVars.mode != MODE_SinglePlayer)
	{
		DebugCmdPacket packet;
		packet.CommandType = cmd.Type;
		packet.ArgI = cmd.ArgI;
		if(packet.SetArgS(cmd.ArgS))
			NetDPrintf("DebugKey called with ArgS of \"%s\" which exceeds packet limit.\n", cmd.ArgS.GetChars());

		SendReliablePacket(packet);
	}

	DoDebugKey(ConsolePlayer, cmd);
}

void EndGame()
{
	if(InitVars.mode != MODE_SinglePlayer)
	{
		EndGamePacket packet;
		SendReliablePacket(packet);
	}

	DoEndGame();
}

static void ResetTicDelay();

byte PlayerTeam(unsigned int player)
{
	// The character you chose, which 9.5 says is the same thing as your side:
	// team play "prevents players controlling the same character from damaging
	// one another". Until M5 there was one character to choose and this dealt
	// sides by player number instead.
	//
	// Nothing about this crosses the wire on its own account. Every machine
	// already knows every player's class, because NewGamePacket carries one
	// per player and Net::NewGame keeps them all.
	if(player >= MAXPLAYERS || gamestate.playerClass[player] == NULL)
		return 0;

	const FName className = gamestate.playerClass[player]->GetName();
	for(unsigned int i = 0;i < gameinfo.PlayerClasses.Size();++i)
	{
		if(gameinfo.PlayerClasses[i] == className)
			return (byte)i;
	}
	return 0;
}

int TeamFrags(byte team)
{
	int total = 0;
	for(unsigned int i = 0;i < InitVars.numPlayers;++i)
	{
		if(PlayerTeam(i) == team)
			total += players[i].frags;
	}
	return total;
}

bool CanDamage(const AActor *attacker, const AActor *target)
{
	// Monsters are everyone's business, and anything without an attacker
	// behind it -- a wall, a laser, falling into something -- is not a
	// question about players at all.
	if(target == NULL || target->player == NULL)
		return true;
	if(attacker == NULL || attacker->player == NULL)
		return true;

	// Hurting yourself stays possible in every mode. It is how a player scores
	// -1 by walking into their own splash, and the rule below would otherwise
	// make you your own permanent teammate.
	if(attacker == target)
		return true;

	if(InitVars.gameMode == GM_Cooperative)
		return false;
	if(InitVars.gameMode != GM_TeamBattle)
		return true;

	return PlayerTeam(attacker->player->GetPlayerNum()) !=
	       PlayerTeam(target->player->GetPlayerNum());
}

void NewGame(int &difficulty, FString &map, FName (&playerClassNames)[MAXPLAYERS])
{
	// A new game starts the tic count again, so anything still buffered from
	// the last one is stamped for tics that will come round a second time.
	ResetTicDelay();

	if(InitVars.numPlayers > 1)
	{
		WindowX = WindowY = 0;
		WindowW = 320;
		WindowH = 200;
		Message("Waiting for all players to start");
	}

	NewGamePacket newGamePackets[MAXPLAYERS];
	NewGamePacket &myNewGameRequest = newGamePackets[ConsolePlayer];

	myNewGameRequest.difficulty = difficulty;
	myNewGameRequest.playerClass = PlayerClass::FromName(playerClassNames[ConsolePlayer]);
	strncpy(myNewGameRequest.map, map, 8);
	myNewGameRequest.map[8] = 0;

	ExchangePacket(newGamePackets);
	for(unsigned int client = 0;client < InitVars.numPlayers;++client)
	{
		playerClassNames[client] = newGamePackets[client].playerClass;

		if(client == Arbiter)
		{
			difficulty = newGamePackets[client].difficulty;
			newGamePackets[client].map[8] = 0;
			map = newGamePackets[client].map;
		}
	}
}

// Input delay: the whole of what makes this playable over the internet.
//
// ExchangePacket sends the command for the tic about to run and then blocks
// until every player has answered, so the game advances no faster than one
// network round trip. Measured on a link with an 80ms round trip that is 8.6
// tics a second against a TICRATE of 70.
//
// Here each command is instead stamped for a tic some way ahead and sent at
// once, and the tic about to run is simulated from commands that were sent
// that many tics ago. The round trip then has the whole window to complete in,
// and in the ordinary case every command has already arrived and nothing waits
// at all. The cost is that a player's own input takes the window to appear --
// eight tics is 114ms -- which is the trade every lockstep game of this era
// made.
//
// The local player's own command is delayed too, and must be: acting on it
// immediately while everyone else sees it a window later is precisely a
// desync. It goes through the same buffer as everybody else's.
// A sequence of our own, advanced once per exchange, rather than
// gamestate.TimeCount. TimeCount is a clock: it does not necessarily advance
// by exactly one between two exchanges, so a command stamped with it can be
// stepped straight over and then waited for for ever. Both sides advance this
// once per tic, so their sequences line up by construction.
static uint32_t TicSeq = 0;

// Every command we have sent, kept by sequence and never cleared.
//
// Resending from our own pending ring is not enough: an entry there is cleared
// as we consume it, so the moment we have moved past a command we can no
// longer send it again -- and the packet a peer lost is exactly one we have
// already used ourselves. Both sides then wait for each other for ever, which
// is what 2% packet loss did.
static TicCmdPacket SentHistory[MAXEXTRATICS];

static void StoreTicCmd(int client, const TicCmdPacket &packet)
{
	// Drop a duplicate rather than filling the ring with copies: a resend
	// arrives as the same sequence we already hold.
	for(unsigned int i = 0;i < MAXEXTRATICS;++i)
	{
		if(Client[client].extratics[i].TimeCount == packet.TimeCount)
			return;
	}
	Client[client].extratics[Client[client].extrapos] = packet;
	Client[client].extrapos = (Client[client].extrapos+1)%MAXEXTRATICS;
}

static bool GatherTicCmds(TicCmdPacket (&packets)[MAXPLAYERS], bool (&have)[MAXPLAYERS])
{
	unsigned int found = 0;
	for(unsigned int c = 0;c < InitVars.numPlayers;++c)
	{
		if(have[c])
		{
			++found;
			continue;
		}
		for(unsigned int i = 0;i < MAXEXTRATICS;++i)
		{
			TicCmdPacket &buffered = Client[c].extratics[i];
			if(buffered.TimeCount == TicSeq + 1)
			{
				packets[c] = buffered;
				buffered.TimeCount = 0;
				have[c] = true;
				++found;
				break;
			}
		}
	}
	return found == InitVars.numPlayers;
}

static void SendTicCmd(TicCmdPacket &packet)
{
	TicCmdPacket wire = packet;
	wire.type = TicCmdPacket::Type;
	wire.ByteSwap();

	UDPpacket outPacket = { -1, (Uint8*)&wire, sizeof(wire), sizeof(wire), 0 };
	for(unsigned int i = 0;i < InitVars.numPlayers;++i)
	{
		if(i == ConsolePlayer)
			continue;
		outPacket.address = Client[i].address;
		SDLNet_UDP_Send(Socket, -1, &outPacket);
	}
}

// The tic that the first stamped command belongs to. Every tic before it has
// no commands anywhere -- they were never sent, because at the first tic the
// window is still ahead of us -- so waiting for them is waiting for ever. Both
// machines enter the level on the same tic, so both work out the same value.
static void ResetTicDelay()
{
	TicSeq = 0;
	memset(SentHistory, 0, sizeof(SentHistory));
	for(unsigned int c = 0;c < MAXPLAYERS;++c)
	{
		for(unsigned int i = 0;i < MAXEXTRATICS;++i)
			Client[c].extratics[i].TimeCount = 0;
		Client[c].extrapos = 0;
	}
}

static void ExchangeDelayedTicCmds(TicCmdPacket (&packets)[MAXPLAYERS])
{
	bool have[MAXPLAYERS] = { false };

	// Ours, stamped for a tic in the future and put in our own buffer exactly
	// as a remote player's would be.
	// Sequences are stored one-based so that zero can mean "empty slot", which
	// is how the ring marks a command as consumed.
	TicCmdPacket &mine = packets[ConsolePlayer];
	mine.type = TicCmdPacket::Type;
	mine.TimeCount = TicSeq + InitVars.ticDelay + 1;
	StoreTicCmd(ConsolePlayer, mine);
	SentHistory[mine.TimeCount % MAXEXTRATICS] = mine;
	SendTicCmd(mine);

	// Before the window has filled there is nothing to wait for: nobody has a
	// command for this tic and nobody ever will. Everyone stands still for the
	// first few hundredths of a second, identically on every machine.
	if(TicSeq < InitVars.ticDelay)
	{
		for(unsigned int c = 0;c < InitVars.numPlayers;++c)
			memset(&packets[c], 0, sizeof(packets[c]));
		++TicSeq;
		return;
	}

	// Everything that has arrived since last tic. In the ordinary case this
	// already holds every command for the tic about to run.
	unsigned int resend = 0;
	bool waiting = false;
	// A tic that cannot be assembled used to stop the game in silence. It has
	// two quite different causes and the player deserves to be told which:
	// packets are being lost on a link bad enough to outrun the resends, or a
	// player has gone and is never going to send anything again. Nothing here
	// acts on it -- dropping a player is a decision every machine would have to
	// take in the same tic or they diverge -- but a game that has stopped
	// should at least say what it has stopped on.
	unsigned int stuckFor = 0;
	for(;;)
	{
		NetWatch("net: assembling a delayed tic");
		if(++stuckFor % 3000 == 0)
		{
			FString missing;
			for(unsigned int i = 0;i < InitVars.numPlayers;++i)
			{
				if(i != (unsigned)ConsolePlayer && !have[i])
					missing.AppendFormat(" %u", i + 1);
			}
			Printf("Waiting %us for tic %u from player%s\n",
				stuckFor/1000, (unsigned)(TicSeq + 1), missing.GetChars());
		}

		while(SDLNet_UDP_Recv(Socket, Packet))
		{
			if(CheckPacketType<TicCmdPacket>(Packet))
			{
				int client = FindClient(Packet->address);
				if(client < 0)
					continue;

				TicCmdPacket &data = *reinterpret_cast<TicCmdPacket *>(Packet->data);
				if(data.TimeCount > TicSeq)
					StoreTicCmd(client, data);
			}
			else if(!CheckPacketType<AckPacket>(Packet))
				HandleCommandPackets();
		}

		if(GatherTicCmds(packets, have))
			break;

		// Something is missing, so a packet was lost. Resend our whole window:
		// the commands still in our own buffer are exactly the ones a peer may
		// not have, and sending them again costs a few hundred bytes.
		if(resend == 0)
		{
			// Everything we have sent that a peer could still be waiting
			// for, whether or not we have consumed it ourselves.
			for(unsigned int i = 0;i < MAXEXTRATICS;++i)
			{
				TicCmdPacket &past = SentHistory[i];
				if(past.TimeCount != 0 &&
					past.TimeCount + MAXEXTRATICS > TicSeq)
					SendTicCmd(past);
			}
			resend = 100;
		}
		--resend;

		IN_ProcessEvents();
		if(!waiting)
			waiting = true;
		else
		{
			if(ingame)
				CheckKeys();
			SDL_Delay(1);
		}

		if(playstate != ex_stillplaying)
			break;
	}

	++TicSeq;
}

void PollControls()
{
	TicCmdPacket ticcmdPackets[MAXPLAYERS];
	bool controls[MAXPLAYERS] = { false };

	// We need to send a ticcmd to each player in the game.
	TicCmdPacket &ticcmdData = ticcmdPackets[ConsolePlayer];
	ticcmdData.controlx = control[ConsolePlayer].controlx;
	ticcmdData.controly = control[ConsolePlayer].controly;
	ticcmdData.controlstrafe = control[ConsolePlayer].controlstrafe;
	assert(sizeof(control[ConsolePlayer].buttonstate) == sizeof(ticcmdData.buttonstate));
	memcpy(ticcmdData.buttonstate, control[ConsolePlayer].buttonstate, sizeof(control[ConsolePlayer].buttonstate));
	memcpy(ticcmdData.buttonheld, control[ConsolePlayer].buttonheld, sizeof(control[ConsolePlayer].buttonheld));

	if(InitVars.ticDelay == 0)
	{
		// Unchanged: exchange the tic about to run and wait for everyone.
		ExchangePacket(ticcmdPackets);
		// Undo the byte swapping of our own packet that ExchangePacket does
		ticcmdData.ByteSwap();
	}
	else
		ExchangeDelayedTicCmds(ticcmdPackets);

	if(playstate != ex_stillplaying)
		return;

	for(unsigned int client = 0;client < InitVars.numPlayers;++client)
	{
		// With input delay our own command comes out of the buffer like
		// everyone else's, a window after it was pressed. Skipping ourselves
		// here would run the local player's input immediately and every other
		// machine's a window later, which is a desync by construction.
		if(client == ConsolePlayer && InitVars.ticDelay == 0)
			continue;

		TicCmdPacket &data = ticcmdPackets[client];
		control[client].controlx = data.controlx;
		control[client].controly = data.controly;
		control[client].controlstrafe = data.controlstrafe;
		memcpy(control[client].buttonstate, data.buttonstate, sizeof(control[client].buttonstate));
		memcpy(control[client].buttonheld, data.buttonheld, sizeof(control[client].buttonheld));
	}

	if(PlaysimBlocked == gamestate.TimeCount)
	{
		// Probably unneeded since CalcTic will single step while blocked, but
		// doesn't hurt to reset time count here
		ResetTimeCount();
	}
	else if(PlaysimBlocked != INT_MIN)
	{
		// Unblock on the next completed tic
		PlaysimBlocked = INT_MIN;
		ResetTimeCount();
	}
}

bool CheckAck(bool send)
{
	if(InitVars.mode == MODE_SinglePlayer || AwaitingAckType != ACK_Any)
		return send;

	if(DidAck == AwaitingAck)
		return true;

	while(SDLNet_UDP_Recv(Socket, Packet))
	{
		HandleCommandPackets();
	}

	if(DidAck == AwaitingAck)
		return true;

	if(send)
	{
		InAckPacket packet;
		packet.Number = AwaitingAck;

		SendReliablePacket(packet);
		return true;
	}

	return send;
}

void StartAck(AckType type)
{
	AwaitingAckType = type;

	switch(type)
	{
		case ACK_Local:
			break;
		case ACK_Block:
			BlockPlaysim();
			break;
		case ACK_Any:
			++AwaitingAck;
			break;
	}
}

}
