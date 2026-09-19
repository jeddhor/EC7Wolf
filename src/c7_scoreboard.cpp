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
	//
	// Fourteen is not enough either, and the comment above used to claim it
	// was. Eleven rows from 58 reach y=198 on a 200-line page whose bottom
	// forty are the status bar, so a full roster was drawn straight through
	// the floor: the board showed seven players and simply stopped. Nothing
	// said so -- the missing four looked like players who had not joined.
	//
	// So the layout is computed from the number of rows rather than fixed,
	// and tightens only when it has to. A four player game looks exactly as
	// it did.
	const int kTitleY   = 20;
	const int kHeaderY  = 43;
	const int kFirstRow = 58;
	// The last line the overlay may touch. The status bar owns what is below
	// it, and drawing there is not clipped, just wrong.
	const int kBottomLimit = 150;
	// And the bottom of the page itself, used when the roster will not fit
	// above the status bar at a legible stride.
	const int kDeepLimit = 190;
	// The frags column, named once rather than repeated: the row text is
	// trimmed against it, so a layout change that moved one and not the other
	// would put names back over the numbers.
	const int kFragsColumn = 258;
	const int kRowStep  = 14;

	// What the table actually uses this time.
	struct Layout
	{
		int titleY;
		int headerY;
		int firstRow;
		int step;
		int height;		// of the window behind it
	};

	Layout LayoutFor(int rows, int glyphHeight)
	{
		Layout l;
		l.titleY = kTitleY;
		l.headerY = kHeaderY;
		l.firstRow = kFirstRow;
		l.step = kRowStep;
		// Two limits. The first is where the status bar begins, and a board
		// that fits above it leaves the player's health and ammunition
		// visible while they read it. The second is the bottom of the page:
		// a roster too big for the first gets the whole screen, because a
		// scoreboard missing four of its eleven players is worse than one
		// that covers the status bar for as long as the key is held.
		if(rows > 0 && l.firstRow + l.step*(rows - 1) > kBottomLimit)
		{
			// Move the whole table up first -- the gap under the title is the
			// cheapest space there is -- and only then tighten the rows.
			l.titleY = 12;
			l.headerY = 30;
			l.firstRow = 44;
			if(rows > 1)
			{
				const int room = l.firstRow + glyphHeight*(rows - 1) >
					kBottomLimit ? kDeepLimit : kBottomLimit;
				l.step = (room - l.firstRow)/(rows - 1);
				if(l.step > kRowStep) l.step = kRowStep;
				// Never shorter than the glyphs. A guessed floor of nine was
				// tried and printed eleven rows through each other: this font
				// is thirteen tall, so nine was not a tight layout, it was an
				// unreadable one. Measured now, and if the rows then do not
				// fit above the status bar the panel is allowed to cover it
				// -- see kDeepLimit.
				if(l.step < glyphHeight) l.step = glyphHeight;
			}
		}
		l.height = l.firstRow + l.step*rows + 8 - (l.titleY - 8);
		return l;
	}

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
		word gw, gh;
		VW_MeasurePropString(font, "Ay", gw, gh);
		const int entries = (int)Session::ActiveSlotCount();

		// Two columns when one will not hold them legibly.
		//
		// The play view ends where the status bar begins, and this font is
		// fifteen lines tall, so a single column holds seven rows and no
		// amount of tightening changes that -- nine was tried and printed the
		// rows through each other. Eleven players is the supported maximum
		// and a board that shows seven of them is not a scoreboard, so past
		// the point where one column stops fitting the table splits.
		const int perColumn = (kBottomLimit - kFirstRow)/(int)gh + 1;
		const bool split = !teams && entries > perColumn;
		const int rowsDown = split ? (entries + 1)/2 : entries;
		const Layout layout = LayoutFor(rowsDown + (teams ? 3 : 0), (int)gh);

		word w, h;
		VW_MeasurePropString(font, title, w, h);
		C7StencilPrintAt(font, 160 - w/2, layout.titleY, title, kTitleColor);

		// Column geometry, worked out once. In two-column mode the row loses
		// its slot number: it is redundant beside a name, and the sixteen
		// pixels it costs are the difference between "Bot 10 [BOT]" fitting
		// and being cut to "Bot 1" -- which reads as a different player.
		// Written out rather than derived. Deriving both columns from one
		// width put the second column's frags at x=316 on a 304-wide panel,
		// and the header read "FRAGSPLAYER" where the two ran together.
		const int nameX0   = 24;
		const int fragsR0  = split ? 150 : 300;
		const int nameX1   = 168;
		const int fragsR1  = 300;

		C7StencilPrintAt(font, nameX0, layout.headerY, "PLAYER", kHeaderColor);
		{
			word hw, hh;
			VW_MeasurePropString(font, "FRAGS", hw, hh);
			C7StencilPrintAt(font, fragsR0 - (int)hw, layout.headerY, "FRAGS",
				kHeaderColor);
			if(split)
			{
				C7StencilPrintAt(font, nameX1, layout.headerY, "PLAYER",
					kHeaderColor);
				C7StencilPrintAt(font, fragsR1 - (int)hw, layout.headerY,
					"FRAGS", kHeaderColor);
			}
		}
		if(teams)
			C7StencilPrintAt(font, 200, layout.headerY, "TEAM", kHeaderColor);

		TArray<Standing> standings;
		Collect(standings);

		FString buffer;
		for(unsigned int i = 0;i < standings.Size();++i)
		{
			const Standing &s = standings[i];
			// Down the first column, then down the second: the leader is
			// still the top-left name.
			const int column = split && (int)i >= rowsDown ? 1 : 0;
			const int within = column ? (int)i - rowsDown : (int)i;
			const int nameX = column ? nameX1 : nameX0;
			const int fragsRight = column ? fragsR1 : fragsR0;
			const int y = layout.firstRow + layout.step*within;

			// The player's own row is marked, because with two of the same
			// character on the board there is otherwise no way to tell which
			// line is yours.
			const bool self = (s.player == (unsigned int)ConsolePlayer);
			C7StencilPrintAt(font, nameX - 16, y, self ? ">" : "", RowColor(i));

			// Identity first, then the character if there is room.
			//
			// Section 18.6: every normal presentation path uses roster
			// identity. This printed the character alone -- "Marine, Marine,
			// Marine" -- because player_t has no name and nothing in the
			// protocol carried one. The roster does carry one, and with bots
			// in the game the character says nothing about who is who.
			//
			// The class is dropped whole rather than cut short when it does
			// not fit: "Corridor 7 Ma" is not more informative than no class
			// at all and looks like a bug. Identity is what the row is for.
			// Measured rather than counted in characters, because the font is
			// proportional.
			// The marker shrinks when the column does.
			//
			// "[BOT]" is six characters of a proportional font and a split
			// column has about ten to spare, so a full roster printed
			// "Bot 10 [BOT" -- a truncation that reads as a different player.
			// An asterisk costs one, and the legend under the table says what
			// it means, which a cut-off bracket never did.
			const char *who = Session::NameOf(s.player);
			const bool isBot = Session::SlotIsBot(s.player);
			if(split)
				buffer.Format("%s%s", who, isBot ? "*" : "");
			else
				buffer.Format("%u  %s%s", s.player + 1, who,
					isBot ? " [BOT]" : "");

			word tw, th;
			if(!isBot)
			{
				FString withClass;
				withClass.Format("%s  %s", buffer.GetChars(),
					CharacterName(s.player));
				VW_MeasurePropString(font, withClass, tw, th);
				if(nameX + (int)tw < fragsRight - 46)
					buffer = withClass;
			}

			// And if even the name alone does not fit, the name is what gets
			// shortened -- it must never reach the numbers.
			VW_MeasurePropString(font, buffer, tw, th);
			while(buffer.Len() > 4 && nameX + (int)tw >= fragsRight - 46)
			{
				buffer.Truncate(buffer.Len() - 1);
				VW_MeasurePropString(font, buffer, tw, th);
			}
			C7StencilPrintAt(font, nameX, y, buffer, RowColor(i));

			if(teams)
			{
				buffer.Format("%u", s.team + 1);
				C7StencilPrintAt(font, 200, y, buffer, TeamColor(i));
			}

			buffer.Format("%d", s.frags);
			VW_MeasurePropString(font, buffer, tw, th);
			C7StencilPrintAt(font, fragsRight - (int)tw, y, buffer, RowColor(i));
		}

		// What the asterisk meant.
		if(split)
			C7StencilPrintAt(font, nameX0,
				layout.firstRow + layout.step*rowsDown + 2, "* BOT",
				kHeaderColor);

		if(teams)
		{
			const int y = layout.firstRow + layout.step*((int)standings.Size() + 1);
			for(byte team = 0;team < 2;++team)
			{
				buffer.Format("TEAM %u", team + 1);
				C7StencilPrintAt(font, 24, y + layout.step*team, buffer, kHeaderColor);
				buffer.Format("%d", Net::TeamFrags(team));
				VW_MeasurePropString(font, buffer, w, h);
				C7StencilPrintAt(font, 300 - w, y + layout.step*team, buffer, kHeaderColor);
			}
		}
	}
}

void C7Scoreboard_DrawOverlay()
{
	if(!Session::HasMultiplePlayers())
		return;

	// The table is printed at the 320x200 coordinates the page was authored
	// at, so it has to be placed the way a full-screen page is placed rather
	// than the way the menu is.
	const int oldpa = pa;
	pa = MENU_NONE;

	const int rows = (int)Session::ActiveSlotCount() +
		(Net::InitVars.gameMode == Net::GM_TeamBattle ? 3 : 0);
	FFont *panelFont = V_GetFont(gameinfo.HighScoresFont);
	word pw, ph;
	VW_MeasurePropString(panelFont, "Ay", pw, ph);
	const Layout layout = LayoutFor(rows, (int)ph);
	DrawWindow(8, layout.titleY - 8, 304, layout.height, 0);

	// With a time limit, the title says how long is left. It is the one place
	// a player looks to see how a round stands, and a limit nobody can see
	// coming ends a round as a surprise. Computed from the same level clock
	// that ends the round, rounded up, so it never reads 0:00 while the round
	// is still running.
	FString title = "SCOREBOARD";
	if(Net::Deathmatch() && Net::InitVars.timeLimit != 0)
	{
		const int32_t limit = (int32_t)Net::InitVars.timeLimit*60*TICRATE;
		int32_t left = limit - gamestate.TimeCount;
		if(left < 0)
			left = 0;
		const int seconds = (int)((left + TICRATE - 1)/TICRATE);
		title.AppendFormat("  %d:%02d", seconds/60, seconds%60);
	}
	DrawTable(title);

	pa = oldpa;
}

void C7Scoreboard_ShowTally()
{
	if(!Session::HasMultiplePlayers())
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
