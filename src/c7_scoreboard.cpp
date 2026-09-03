/*
** c7_scoreboard.cpp
**
** Who is winning, and by how much.
**
** Both of the things here -- the overlay held up during a match and the page
** shown when one ends -- draw the same table, and draw it the way Corridor 7
** draws its high-score page: the same font, printed through the same stencil,
** on the same backdrop, with the same descending row colors. The alternative
** was to invent a look for it, and this game already has one.
**
** Everything shown is state every machine agrees on, so nobody's scoreboard
** disagrees with anybody else's. Nothing here is sent.
*/

#include "wl_def.h"
#include "g_session.h"
#include "wl_agent.h"
#include "wl_draw.h"
#include "wl_game.h"
#include "wl_inter.h"
#include "wl_menu.h"
#include "wl_net.h"
#include "wl_play.h"
#include "c7_scoreboard.h"
#include "r_capture.h"
#include "g_mapinfo.h"
#include "id_in.h"
#include "id_ca.h"
#include "id_vh.h"
#include "id_vl.h"
#include "v_font.h"
#include "v_video.h"
#include "textures/textures.h"
#include "thingdef/thingdef.h"

namespace
{
	// Lifted from the high-score page so the two read as one family: the title
	// in 0xB7, column headings in 0x24, and rows descending through the ramp so
	// the leader is brightest.
	const BYTE kTitleColor  = 0xB7;
	const BYTE kHeaderColor = 0x24;

	BYTE RowColor(unsigned int place)  { return (BYTE)(0x57 - 2*place); }
	BYTE TeamColor(unsigned int place) { return (BYTE)(0x6F - 2*place); }

	// The high-score page puts its first row at 62 and steps 18. Eleven players
	// will not fit at that stride, so the scoreboard steps 14 and starts a
	// little higher; everything else about the layout is the page's.
	const int kTitleY   = 20;
	const int kHeaderY  = 43;
	const int kFirstRow = 58;
	const int kRowStep  = 14;

	// How long the tally stands before the next round starts on its own.
	// Ten seconds at the engine's 70Hz.
	const longword kTallyTics = 700;

	struct Standing
	{
		unsigned int player;
		int frags;
		byte team;
	};

	// Sorted by frags, and by player number where those tie, so that every
	// machine puts the same player in the same row. A sort that broke ties by
	// anything else -- who was reached first, who scored most recently -- would
	// give two players a different table for the same game.
	void Collect(TArray<Standing> &standings)
	{
		for(unsigned int i = 0;i < Session::ActiveSlotCount();++i)
		{
			Standing s = { i, players[i].frags, Net::PlayerTeam(i) };
			standings.Push(s);
		}

		for(unsigned int i = 1;i < standings.Size();++i)
		{
			Standing key = standings[i];
			int j = (int)i - 1;
			while(j >= 0 && (standings[j].frags < key.frags ||
				(standings[j].frags == key.frags && standings[j].player > key.player)))
			{
				standings[j+1] = standings[j];
				--j;
			}
			standings[j+1] = key;
		}
	}

	const char *CharacterName(unsigned int player)
	{
		if(player >= MAXPLAYERS || gamestate.playerClass[player] == NULL)
			return "";
		const char *name =
			gamestate.playerClass[player]->Meta.GetMetaString(APMETA_DisplayName);
		return name ? name : "";
	}

	// Draws the table at the page's own coordinates. The caller has already put
	// something behind it and set the drawing mode; this only prints.
	void DrawTable(const char *title)
	{
		FFont *font = V_GetFont(gameinfo.HighScoresFont);
		const bool teams = (Net::InitVars.gameMode == Net::GM_TeamBattle);

		word w, h;
		VW_MeasurePropString(font, title, w, h);
		C7StencilPrintAt(font, 160 - w/2, kTitleY, title, kTitleColor);

		C7StencilPrintAt(font, 24, kHeaderY, "PLAYER", kHeaderColor);
		if(teams)
			C7StencilPrintAt(font, 200, kHeaderY, "TEAM", kHeaderColor);
		C7StencilPrintAt(font, 258, kHeaderY, "FRAGS", kHeaderColor);

		TArray<Standing> standings;
		Collect(standings);

		FString buffer;
		for(unsigned int i = 0;i < standings.Size();++i)
		{
			const Standing &s = standings[i];
			const int y = kFirstRow + kRowStep*(int)i;

			// The player's own row is marked, because with two of the same
			// character on the board there is otherwise no way to tell which
			// line is yours.
			const bool self = (s.player == (unsigned int)ConsolePlayer);
			C7StencilPrintAt(font, 8, y, self ? ">" : "", RowColor(i));

			// The character rather than a name, because a player has no name to
			// print -- nothing in the protocol carries one -- and in team play
			// the character is also the side.
			buffer.Format("%u  %s", s.player + 1, CharacterName(s.player));
			C7StencilPrintAt(font, 24, y, buffer, RowColor(i));

			if(teams)
			{
				buffer.Format("%u", s.team + 1);
				C7StencilPrintAt(font, 200, y, buffer, TeamColor(i));
			}

			buffer.Format("%d", s.frags);
			VW_MeasurePropString(font, buffer, w, h);
			C7StencilPrintAt(font, 300 - w, y, buffer, RowColor(i));
		}

		if(teams)
		{
			const int y = kFirstRow + kRowStep*((int)standings.Size() + 1);
			for(byte team = 0;team < 2;++team)
			{
				buffer.Format("TEAM %u", team + 1);
				C7StencilPrintAt(font, 24, y + 14*team, buffer, kHeaderColor);
				buffer.Format("%d", Net::TeamFrags(team));
				VW_MeasurePropString(font, buffer, w, h);
				C7StencilPrintAt(font, 300 - w, y + 14*team, buffer, kHeaderColor);
			}
		}
	}
}

void C7Scoreboard_DrawOverlay()
{
	if(Net::InitVars.mode == Net::MODE_SinglePlayer)
		return;

	// The table is printed at the 320x200 coordinates the page was authored
	// at, so it has to be placed the way a full-screen page is placed rather
	// than the way the menu is.
	const int oldpa = pa;
	pa = MENU_NONE;

	const int rows = (int)Session::ActiveSlotCount() +
		(Net::InitVars.gameMode == Net::GM_TeamBattle ? 3 : 0);
	const int panelH = kFirstRow + kRowStep*rows + 8 - (kTitleY - 8);
	DrawWindow(8, kTitleY - 8, 304, panelH, 0);

	DrawTable("SCOREBOARD");

	pa = oldpa;
}

void C7Scoreboard_ShowTally()
{
	if(Net::InitVars.mode == Net::MODE_SinglePlayer)
		return;

	VW_FadeOut();

	// C7G0016 is the high-score page's backdrop, which is where a page of
	// standings belongs.
	CA_CacheScreen(TexMan("C7G0016"));

	const int oldpa = pa;
	pa = MENU_NONE;
	DrawTable("FINAL SCORE");
	pa = oldpa;

	VW_UpdateScreen();
	VW_FadeIn();

	// Waits for a key, but not for ever. A deathmatch between rounds should
	// carry on by itself if everybody has wandered off to make tea, and a
	// tally that blocks until somebody presses something is a tally that can
	// hang a whole match on one absent player. ACK_Any so that anybody can cut
	// it short rather than everybody having to press something.
	Capture::WriteTallyShot();

	IN_UserInput(kTallyTics, ACK_Any);

	VW_FadeOut();
}
