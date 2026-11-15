// WL_INTER.C

#include "wl_def.h"
#include "g_session.h"
#include "wl_menu.h"
#include "wl_play.h"
#include "id_ca.h"
#include "id_sd.h"
#include "id_vl.h"
#include "id_vh.h"
#include "id_us.h"
#include "language.h"
#include "v_video.h"
#include "wl_agent.h"
#include "wl_game.h"
#include "wl_inter.h"
#include "r_artscale.h"
#include "wl_net.h"
#include "wl_text.h"
#include "g_mapinfo.h"
#include "wl_iwad.h"
#include "colormatcher.h"

LRstruct LevelRatios;

static int32_t lastBreathTime = 0;

//==========================================================================

/*
==================
=
= CLearSplitVWB
=
==================
*/

void
ClearSplitVWB (void)
{
	WindowX = 0;
	WindowY = 0;
	WindowW = 320;
	WindowH = 160;
}

//==========================================================================

static void Erase (int x, int y, const char *string, bool rightAlign=false)
{
	double nx = x*8;
	double ny = y*8;

	word width, height;
	VW_MeasurePropString(IntermissionFont, string, width, height);

	if(rightAlign)
		nx -= width;

	double fw = width;
	double fh = height;
	screen->VirtualToRealCoords(nx, ny, fw, fh, 320, 200, true, true);
	VWB_DrawFill(TexMan(levelInfo->GetBorderTexture()), nx, ny, nx+fw, ny+fh);
}

static void WritePixel (int nx, int ny, const char *string, bool rightAlign=false, bool bonusfont=false)
{
	FFont *font = IWad::CheckGameFilter("Corridor7") ? SmallFont :
		(bonusfont ? V_GetFont("BonusFont") : IntermissionFont);
	FRemapTable *remap = font->GetColorTranslation(
		IWad::CheckGameFilter("Corridor7") ? CR_YELLOW : CR_UNTRANSLATED);

	const int x = nx;

	if(rightAlign)
	{
		word width, height;
		VW_MeasurePropString(font, string, width, height);
		nx -= width;
	}

	int width;
	while(*string != '\0')
	{
		if(*string != '\n')
		{
			FTexture *glyph = font->GetChar(*string, &width);
			if(glyph)
				VWB_DrawGraphic(glyph, nx, ny, MENU_NONE, remap);
			nx += width;
		}
		else
		{
			nx = x;
			ny += font->GetHeight();
		}
		++string;
	}
}

static void Write (int x, int y, const char *string, bool rightAlign=false, bool bonusfont=false)
{
	WritePixel(x*8, y*8, string, rightAlign, bonusfont);
}


static const unsigned int PAR_AMOUNT = 500;
static struct IntermissionState
{
	unsigned int kr, sr, tr;
	int timeleft;
	uint32_t bonus;
	bool acked;
	bool graphical;
} InterState;
enum
{
	WI_LEVEL,
	WI_FLOOR,
	WI_FINISH,
	WI_BONUS,
	WI_TIME,
	WI_PAR,
	WI_KILLS,
	WI_TREASR,
	WI_SECRTS,
	WI_PERFCT,
	WI_RATING,

	NUM_WI
};
static const char* const GraphicalTexNames[NUM_WI] = {
	"WILEVEL", "WIFLOOR", "WIFINISH", "WIBONUS", "WITIME", "WIPAR",
	"WIKILLS", "WITREASR", "WISECRTS", "WIPERFCT", "WIRATING"
};
static FTextureID GraphicalTexID[NUM_WI];

//
// Breathe Mr. BJ!!!
//
void BJ_Breathe (bool drawOnly=false)
{
	// Corridor 7 has no BJ breathing-face resources. Its exact status bar is
	// retained underneath the generic score-counting intermission instead.
	if(IWad::CheckGameFilter("Corridor7"))
	{
		if(!drawOnly) SDL_Delay(5);
		return;
	}

	static int which = 0, max = 10;
	static FTexture* const pics[2] = { TexMan("L_GUY1"), TexMan("L_GUY2") };
	unsigned int height = InterState.graphical ? 8 : 16;

	if(drawOnly)
	{
		VWB_DrawGraphic(pics[which], 0, height);
		return;
	}

	SDL_Delay(5);

	if ((int32_t) GetTimeCount () - lastBreathTime > max)
	{
		which ^= 1;
		VWB_DrawGraphic(pics[which], 0, height);
		VW_UpdateScreen ();
		lastBreathTime = GetTimeCount();
		max = 35;
	}
}

static void InterWriteCounter(int start, int end, int step, unsigned int x, unsigned int y, const char* sound, unsigned int sndfreq, bool bonusfont=false)
{
	const unsigned int tx = x>>3, ty = y>>3;

	if(InterState.acked)
	{
		FString tempstr;
		tempstr.Format("%d", end);
		Write(tx, ty, tempstr, true, bonusfont);
		return;
	}

	bool cont = true;
	unsigned int i = 0;
	FString tempstr("0");
	do
	{
		if(start > end)
		{
			start = end;
			cont = false;
		}

		if(start) Erase (tx, ty, tempstr, true);
		tempstr.Format("%d", start);
		Write (tx, ty, tempstr, true, bonusfont);
		if (sndfreq == 0)
		{
			if(cont)
				SD_PlaySound(sound);
		}
		else if(!((i++) % sndfreq))
			SD_PlaySound (sound);
		if(!(start & 1)) VW_UpdateScreen ();
		do
		{
			BJ_Breathe ();
		}
		while (sndfreq && SD_SoundPlaying ());

		if (IN_CheckAck ())
		{
			InterState.acked = true;
			if(start != end)
			{
				start = end;
				continue;
			}
		}

		start += step;
	}
	while(cont);
}

static void InterWriteTime(unsigned int time, unsigned int x, unsigned int y, bool hours=false)
{
	unsigned int m, s;
	FString timestamp;
	if(hours)
	{
		unsigned int h = clamp<unsigned int>(time/3600, 0, 9);
		if(h < 9)
			m = (time / 60) % 60;
		else
			m = clamp<unsigned int>((time - 3600*9)/60, 0, 99);

		if(m < 99)
			s = time % 60;
		else
			s = clamp<unsigned int>(time - (3600*9 + 60*99), 0, 99);

		timestamp.Format("%u:%02u:%02u", h, m, s);
	}
	else
	{
		m = clamp<unsigned int>(time/60, 0, 99);

		if(m < 99)
			s = time % 60;
		else
			s = clamp<unsigned int>(time - (3600*9 + 60*99), 0, 99);

		timestamp.Format("%02u:%02u", m, s);
	}

	Write(x>>3, y>>3, timestamp, false);
}

static void InterAddBonus(unsigned int bonus, bool count=false)
{
	const unsigned int y = InterState.graphical ? 72 : 56;
	if(count)
	{
		InterState.bonus += bonus;
		InterWriteCounter(0, bonus, PAR_AMOUNT, 288, y, "misc/end_bonus1", PAR_AMOUNT/10, InterState.graphical);
		return;
	}

	FString bonusstr;
	bonusstr.Format("%u", InterState.bonus);
	Erase (36, y>>3, bonusstr, true);
	InterState.bonus += bonus;
	bonusstr.Format("%u", InterState.bonus);
	Write (36, y>>3, bonusstr, true, InterState.graphical);
	VW_UpdateScreen ();
}

// Divy up bonus points to all players
static void InterGiveBonus(unsigned int bonus)
{
	unsigned int commonBonus = bonus/Session::ActiveSlotCount();
	unsigned int extraBonus = bonus%Session::ActiveSlotCount();

	// We'll give the remainder points to the lowest scoring player because why not?
	player_t *extraRecipient = players;
	for(unsigned int i = 1;i < Session::ActiveSlotCount();++i)
	{
		if(players[i].score < extraRecipient->score)
			extraRecipient = &players[i];
	}

	for(unsigned int i = 0;i < Session::ActiveSlotCount();++i)
		players[i].GivePoints(commonBonus + (&players[i] == extraRecipient ? extraBonus : 0));
}

/**
 * Displays a percentage ratio, counting up to the ratio.
 * Returns true if the intermission has been acked and should be skipped.
 */
static void InterCountRatio(int ratio, unsigned int x, unsigned int y)
{
	static const unsigned int VBLWAIT = 30;
	static const unsigned int PERCENT100AMT = 10000;

	if (InterState.graphical)
		InterWriteCounter(1, ratio, 1, x, y, "misc/end_bonus1", 0);
	else
		InterWriteCounter(0, ratio, 1, x, y, "misc/end_bonus1", 10);
	if (ratio >= 100)
	{
		if(!InterState.acked)
			VW_WaitVBL (VBLWAIT);
		SD_StopSound ();
		InterAddBonus(PERCENT100AMT);
		if(InterState.acked)
			return;
		SD_PlaySound ("misc/100percent");
	}
	else if (!ratio)
	{
		if(InterState.acked)
			return;
		VW_WaitVBL (VBLWAIT);
		SD_StopSound ();
		SD_PlaySound ("misc/no_bonus");
	}
	else
	{
		if(InterState.acked)
			return;
		SD_PlaySound ("misc/end_bonus2");
	}

	VW_UpdateScreen ();
	while (SD_SoundPlaying ())
		BJ_Breathe ();
}

static void InterWaitForAck()
{
	InterState.acked = false;
	IN_StartAck (ACK_Any);
	while (!IN_CheckAck ())
		BJ_Breathe ();
	IN_ClearKeysDown();
}

static void InterDrawNormalTop()
{
	FString completedString;
	if(!levelInfo->CompletionString.IsEmpty())
	{
		if(levelInfo->CompletionString[0] == '$')
			completedString = language[levelInfo->CompletionString.Mid(1)];
		else
			completedString = levelInfo->CompletionString;

		FString formattedString;
		formattedString.Format(completedString, levelInfo->FloorNumber.GetChars());
		Write (14, 2, formattedString);
	}
	else
	{
		if(levelInfo->TitlePatch.isValid())
		{
			VWB_DrawGraphic(TexMan(levelInfo->TitlePatch), 112, 16);
		}
		else
		{
			completedString.Format("%s %s", language["STR_FLOOR"], levelInfo->FloorNumber.GetChars());
			Write (14, 2, completedString);
		}
		Write(14, 4, language["STR_COMPLETED"]);
	}
}

static void InterDrawGraphicalTop()
{
	// Handle X-Y floor numbers. If not in that format emulate the normal
	// mode by just using floor X.
	int dash = levelInfo->FloorNumber.IndexOf('-');
	if(dash != -1)
	{
		if(levelInfo->TitlePatch.isValid())
		{
			VWB_DrawGraphic(TexMan(levelInfo->TitlePatch), 104, 8);
			VWB_DrawGraphic(TexMan(GraphicalTexID[WI_LEVEL]), 104, 24);
			Write(23, 3, levelInfo->FloorNumber.Left(dash), false);
		}
		else
		{
			VWB_DrawGraphic(TexMan(GraphicalTexID[WI_LEVEL]), 104, 8);
			Write(23, 1, levelInfo->FloorNumber.Left(dash), false);
			VWB_DrawGraphic(TexMan(GraphicalTexID[WI_FLOOR]), 104, 24);
			Write(23, 3, levelInfo->FloorNumber.Mid(dash+1), false);
		}
		VWB_DrawGraphic(TexMan(GraphicalTexID[WI_FINISH]), 104, 40);
	}
	else
	{
		VWB_DrawGraphic(TexMan(GraphicalTexID[WI_FLOOR]), 104, 8);
		VWB_DrawGraphic(TexMan(GraphicalTexID[WI_FINISH]), 104, 24);
		Write(23, 1, levelInfo->FloorNumber, false);
	}
}

static void InterDoBonus()
{
	if(InterState.graphical)
		InterDrawGraphicalTop();
	else
		InterDrawNormalTop();

	FString bonusString;
	bonusString.Format("%d bonus!", levelInfo->LevelBonus);
	Write (34, 16, bonusString, true);

	VW_UpdateScreen ();
	VW_FadeIn ();

	InterGiveBonus (levelInfo->LevelBonus);
}

static void InterDoNormal()
{
	InterDrawNormalTop();

	Write (24, 7, language["STR_BONUS"], true);
	Write (24, 10, language["STR_TIME"], true);
	Write (24, 12, language["STR_PAR"], true);

	// Write the starting value based on InterState.bonus in case ForceTally is on
	FString bonusstr;
	bonusstr.Format("%u", InterState.bonus);
	Write (36, 7, bonusstr, true);

	Write (37, 14, "%");
	Write (37, 16, "%");
	Write (37, 18, "%");
	Write (29, 14, language["STR_RAT2KILL"], true);
	Write (29, 16, language["STR_RAT2SECRET"], true);
	Write (29, 18, language["STR_RAT2TREASURE"], true);

	InterWriteTime(levelInfo->Par, 26*8, 12*8);

	//
	// PRINT TIME
	//
	InterWriteTime(gamestate.TimeCount/TICRATE, 26*8, 10*8);

	VW_UpdateScreen ();
	VW_FadeIn ();

	//
	// PRINT TIME BONUS
	//
	if(InterState.timeleft)
		InterAddBonus(InterState.timeleft * PAR_AMOUNT, true);
	if (InterState.bonus)
	{
		VW_UpdateScreen ();

		SD_PlaySound ("misc/end_bonus2");
		while (SD_SoundPlaying ())
			BJ_Breathe ();
	}

	InterCountRatio(InterState.kr, 296, 112);
	InterCountRatio(InterState.sr, 296, 112+16);
	InterCountRatio(InterState.tr, 296, 112+32);

	InterGiveBonus (InterState.bonus);
}

static void InterDoGraphical()
{
	InterDrawGraphicalTop();

	VWB_DrawGraphic(TexMan(GraphicalTexID[WI_BONUS]), 104, 72);
	// Write the starting value based on InterState.bonus in case ForceTally is on
	FString bonusstr;
	bonusstr.Format("%u", InterState.bonus);
	Write (36, 9, bonusstr, true, true);

	VW_UpdateScreen ();
	VW_FadeIn ();

	//
	// PRINT TIME BONUS
	//
	if(InterState.timeleft)
		InterAddBonus(InterState.timeleft * PAR_AMOUNT, true);
	if (InterState.bonus)
	{
		VW_UpdateScreen ();

		SD_PlaySound ("misc/end_bonus2");
		while (SD_SoundPlaying ())
			BJ_Breathe ();
	}

	VWB_DrawGraphic(TexMan(GraphicalTexID[WI_TIME]), 88, 128);
	VWB_DrawGraphic(TexMan(GraphicalTexID[WI_PAR]), 96, 112);

	InterWriteTime(levelInfo->Par, 19*8, 14*8);

	//
	// PRINT TIME
	//
	InterWriteTime(gamestate.TimeCount/TICRATE, 19*8, 16*8);

	double cleary = 104;
	{
		// Really all we care about here is finding the starting y
		// since we need to over clear a bit in order to account for
		// rounding errors and so we don't need to worry about fonts.
		double clearx = 0, clearw = 0, clearh = 0;
		screen->VirtualToRealCoords(clearx, cleary, clearw, clearh, 320, 200, true, true);
	}

	InterWaitForAck();

	VWB_DrawFill(TexMan(levelInfo->GetBorderTexture()), 0., cleary, (double)screenWidth, (double)statusbary2);
	VWB_DrawGraphic(TexMan(GraphicalTexID[WI_KILLS]), 80, 104);
	VWB_DrawGraphic(TexMan(GraphicalTexID[WI_TREASR]), 104, 120);
	VWB_DrawGraphic(TexMan(GraphicalTexID[WI_SECRTS]), 72, 136);
	Write (27, 13, "0%");
	Write (27, 15, "0%");
	Write (27, 17, "0%");

	InterCountRatio(InterState.kr, 232, 104);
	InterCountRatio(InterState.tr, 232, 104+16);
	InterCountRatio(InterState.sr, 232, 104+32);

	InterGiveBonus (InterState.bonus);

	if(InterState.kr == 100 && InterState.sr == 100 && InterState.tr == 100)
	{
		VWB_DrawFill(TexMan(levelInfo->GetBorderTexture()), 0., cleary, (double)screenWidth, (double)statusbary2);
		VWB_DrawGraphic(TexMan(GraphicalTexID[WI_PERFCT]), 96, 120);
		SD_PlaySound ("misc/100percent");
	}
}

static void DetermineIntermissionMode()
{
	static bool modeUndetermined = true;
	if(modeUndetermined)
	{
		modeUndetermined = false;
		InterState.graphical = true;
		for(unsigned int i = 0;i < NUM_WI;++i)
		{
			if(!(GraphicalTexID[i] = TexMan.CheckForTexture(GraphicalTexNames[i], FTexture::TEX_Any)).isValid())
			{
				InterState.graphical = false;
				break;
			}
		}
	}
}

static void C7PrintAt(FFont *font, int x, int y, const char *text,
	EColorRange color, bool rightAlign=false)
{
	word width, height;
	if(rightAlign)
	{
		VW_MeasurePropString(font, text, width, height);
		x -= width;
	}
	PrintX = x;
	PrintY = y;
	US_Print(font, text, color);
}

// Not static: the multiplayer scoreboard draws in the same language and on the
// same backdrop as the high-score page, and a second copy of this would be a
// second place for the two to drift apart.
void C7StencilPrintAt(FFont *font, int x, int y, const char *text,
	BYTE paletteIndex)
{
	px = x;
	py = y;
	VWB_DrawPropString(font, text, CR_UNTRANSLATED, true, paletteIndex);
}

// Corridor 7 tiles its skull backdrop across the original 320x200 screen, so
// the pattern has to scale with the virtual screen rather than the output
// resolution. VWB_DrawFill goes through DCanvas::FlatFill, which repeats the
// texture at native texel size in REAL pixels: the 32x40 tile covered a tenth
// of the width at 320x200 but only a twentieth at 640x480, so every tile came
// out half the size the original shows (and smaller still above that).
// Draws one of the Corridor 7 plates -- the loading bar's surround, the death
// report's panel -- upscaled, but into exactly the rectangle it has always
// occupied.
//
// The size has to be passed explicitly. The short form of VWB_DrawGraphic takes
// the destination rectangle from the texture's own dimensions, which is right
// only while the texture is still the size it was authored at; handed an
// upscaled one it would place the plate several times too large. Reading the
// authored size first and passing it through keeps the layout fixed, which
// matters here beyond neatness: the loading meter is drawn at hard-coded
// coordinates inside the plate and would otherwise no longer sit in it.
static void C7DrawPlate(FTexture *tex, int x, int y)
{
	if(tex == NULL)
		return;
	const double w = tex->GetScaledWidthDouble();
	const double h = tex->GetScaledHeightDouble();
	VWB_DrawGraphic(R_UpscaledArt(tex), x, y, w, h);
}

// The skull pattern behind those plates.
//
// It cannot be upscaled one tile at a time: xBRZ reads the edges of what it is
// given as edges of the image, and these are seams in the middle of a repeating
// pattern, so every tile boundary would come out filtered as though the pattern
// stopped there -- a grid of seams across the backdrop. Tiling the whole page
// first and upscaling that fixes it, because then the seams are interior pixels
// like any other and the only edges the filter sees are the screen's own. Left
// unfiltered until now, which is why this was the most obviously blocky thing on
// the loading screen while the plate in front of it was smooth.
static void C7DrawTiledBackdrop(FTexture *tex)
{
	if(tex == NULL)
		return;

	FTexture *const page = R_UpscaledTiledPage(tex, 320, 200);
	if(page != NULL && page != tex)
	{
		// Sized in real pixels: the upscaled page is no longer 320x200.
		screen->DrawTexture(page, 0, 0,
			DTA_DestWidth, screenWidth, DTA_DestHeight, screenHeight,
			DTA_TopOffset, 0, DTA_LeftOffset, 0, TAG_DONE);
		return;
	}

	// No upscale to be had (the window is no bigger than the art): tile it.
	const int tileW = tex->GetScaledWidth();
	const int tileH = tex->GetScaledHeight();
	if(tileW <= 0 || tileH <= 0)
		return;
	for(int y = 0;y < 200;y += tileH)
	{
		for(int x = 0;x < 320;x += tileW)
		{
			screen->DrawTexture(tex, x, y,
				DTA_VirtualWidth, 320, DTA_VirtualHeight, 200,
				DTA_TopOffset, 0, DTA_LeftOffset, 0, TAG_DONE);
		}
	}
}

/*
==================
=
= Corridor 7's end-of-floor report
=
==================
*/

// CORR7CD.EXE a335. Every floor ends on the status report; a bonus floor then
// shows a second page, the hit/miss ratio (a552), and each page pays its own
// award. The port used to have one page paying the hit/miss award under the
// status report's "BONUS" -- so every campaign floor paid an accuracy award the
// original pays only after a bonus floor, the status report's own award was
// never paid at all, and the hit/miss page was missing (GitHub #23).
//
// Scoring is kept apart from drawing so that each award is paid exactly once,
// and to every player, whichever screen is looking.
struct C7StatusReport
{
	bool bonusFloor;
	int aliens, restricted, efficiency;
	int32_t award;
};

// Fills a rectangle of the original's 320x200 screen with a palette colour,
// in the full-screen pictures' stretched mapping -- VWB_Bar in the original.
static void C7FillRect(int x, int y, int w, int h, BYTE color)
{
	double rx = x, ry = y, rw = w, rh = h;
	screen->VirtualToRealCoords(rx, ry, rw, rh, 320, 200, true, true);
	const int left = static_cast<int>(rx), top = static_cast<int>(ry);
	VWB_Clear(color, left, top, MAX(left+1, static_cast<int>(rx+rw)),
		MAX(top+1, static_cast<int>(ry+rh)));
}

// CORR7CD.EXE's text routine (214a:2965) puts every string over a black drop
// shadow one pixel down and to the right. It is black even where the caller
// sets DS:8b68 to the navy of the high-score bar, so that byte is not its
// colour. Compared against DOS captures of the report pages, the mission page
// and the high-score table, glyph for glyph.
static void C7ShadowPrintAt(FFont *font, int x, int y, const char *text,
	BYTE color, BYTE shadow=0)
{
	C7StencilPrintAt(font, x+1, y+1, text, shadow);
	C7StencilPrintAt(font, x, y, text, color);
}

static C7StatusReport C7ScoreStatusReport()
{
	C7StatusReport report;
	report.bonusFloor = levelInfo->BonusLevel;

	// Both start at zero and are divided only when there is a total, so a
	// floor with no aliens has eliminated none of them. Aliens are capped at
	// 100; restricted areas are not.
	report.aliens = gamestate.killtotal ?
		(gamestate.killcount*100)/gamestate.killtotal : 0;
	if(report.aliens > 100)
		report.aliens = 100;
	if(report.bonusFloor)
	{
		// Shown as N/A. A bonus floor is rated on its aliens alone.
		report.restricted = 100;
		report.efficiency = report.aliens;
	}
	else
	{
		report.restricted = gamestate.secrettotal ?
			(gamestate.secretcount*100)/gamestate.secrettotal : 0;
		report.efficiency = (report.aliens + report.restricted)/2;
	}
	report.award = report.efficiency*100;
	return report;
}

static void C7DrawStatusReport(const C7StatusReport &report)
{
	CA_CacheScreen(TexMan("C7G0014"));

	// Full-screen picture page: the text shares the picture's stretched
	// 320x200 mapping. The values go in the small font at the colon column,
	// x=208, on the rows a335 passes (70/85/100 and 126/140/155), in its own
	// formats: "%3d%%" and "%6ld" pad with spaces, which is what lines the
	// digits up under one another. The floor's results are green (0x87) and
	// its rating yellow (0x6f), matching the DOS capture.
	const int oldpa = pa;
	pa = MENU_NONE;
	static const BYTE RESULT_COLOR = 0x87, RATING_COLOR = 0x6f;
	FString value;
	C7ShadowPrintAt(SmallFont, 208, 70, report.bonusFloor ? "BONUS" : "SECURED",
		RESULT_COLOR);
	value.Format("%3d%%", report.aliens);
	C7ShadowPrintAt(SmallFont, 208, 85, value, RESULT_COLOR);
	if(report.bonusFloor)
		value = "N/A";
	else
		value.Format("%3d%%", report.restricted);
	C7ShadowPrintAt(SmallFont, 208, 100, value, RESULT_COLOR);
	value.Format("%3d%%", report.efficiency);
	C7ShadowPrintAt(SmallFont, 208, 126, value, RATING_COLOR);
	value.Format("%6d", report.award);
	C7ShadowPrintAt(SmallFont, 208, 140, value, RATING_COLOR);
	value.Format("%6d", players[ConsolePlayer].score);
	C7ShadowPrintAt(SmallFont, 208, 155, value, RATING_COLOR);
	pa = oldpa;
}

// The accuracy award (a73c): the percentage of shots that hit, times ten for
// every started hundred shots. A floor without a shot earns nothing.
static int32_t C7AccuracyAward(uint32_t shots, uint32_t hits, unsigned int &accuracy)
{
	hits = MIN(hits, shots);
	accuracy = shots ? (hits*100)/shots : 0;
	return static_cast<int32_t>(accuracy * (shots/100 + 1) * 10);
}

// One row of the hit/miss page's tally: a 3x3 block per shot (per hundred on
// the mission page), four pixels apart from x=90, wrapping to a new row four
// pixels down once x passes 300 -- 53 to a row. The row advances after the
// block that fills it, so an exact multiple of 53 leaves an empty row below,
// as the original's does. Returns the y of the row it finished on.
//
// The original redraws the screen after every block and then calls TicDelay(50)
// (a6a4), which returns at once unless a direction is held. Nobody holding one
// sees the finished page; somebody who is sees the tally count up a block every
// 50 tics for as long as they hold it, and the rest appear the moment they let
// go -- a DOS run holding Right showed exactly that. Both are kept: the redraw
// happens only while a direction is held, which is when it could be seen.
//
// "Held" is asked of the live keyboard as well as the control state: the key
// that dismissed the status report was cleared from the key table, and an
// arrow already down when the page began would otherwise not count.
static bool C7DirectionHeld()
{
	ControlInfo ci;
	ReadAnyControl(&ci);
	return ci.dir != dir_None || IN_DirectionHeld();
}

static int C7DrawHitMissBlocks(unsigned int count, int y, BYTE color)
{
	int x = 90;
	for(unsigned int i = 0;i < count;++i)
	{
		// Anything below the page would have been drawn off it.
		if(y+1 < 200)
			C7FillRect(x, y+1, 3, 3, color);
		x += 4;
		if(x > 300)
		{
			x = 90;
			y += 4;
		}

		if(C7DirectionHeld())
		{
			VW_UpdateScreen();
			const int32_t start = GetTimeCount();
			do
				SDL_Delay(5);
			while((int32_t)GetTimeCount() - start < 50 && C7DirectionHeld());
		}
	}
	return y;
}

static void C7PrintCentered(FFont *font, int y, const char *text, BYTE color)
{
	word width, height;
	VW_MeasurePropString(font, text, width, height);
	C7ShadowPrintAt(font, 160 - width/2, y, text, color);
}

// The second page after a bonus floor, laid out as a552 draws it: the large
// font for the title and the three results, the small font for the two tally
// labels and their counts. The same routine, entered at a559, ends the
// campaign as MISSION HIT/MISS RATIO over the whole mission's shooting, with a
// block per hundred shots rather than per shot.
static void C7DrawHitMissPage(bool mission, uint32_t shots, uint32_t hits,
	unsigned int accuracy, int32_t award)
{
	const unsigned int perBlock = mission ? 100 : 1;
	C7DrawTiledBackdrop(TexMan("C7G0004"));

	const int oldpa = pa;
	pa = MENU_NONE;
	static const BYTE YELLOW = 0x6f, WHITE = 0x27, BLUE = 0x3f;
	static const BYTE SHOTS_COLOR = 0x57, HITS_COLOR = 0xb7;
	FString value;

	C7PrintCentered(BigFont, 10,
		mission ? "MISSION HIT/MISS RATIO" : "BONUS LEVEL HIT/MISS RATIO", YELLOW);

	int y = 40;
	C7ShadowPrintAt(SmallFont, 10, y, "Shots fired:", YELLOW);
	value.Format("%u", shots);
	C7ShadowPrintAt(SmallFont, 13, y+10, value, WHITE);
	y = C7DrawHitMissBlocks(shots/perBlock, y, SHOTS_COLOR) + 20;

	C7ShadowPrintAt(SmallFont, 10, y, "Shots hit:", YELLOW);
	value.Format("%u", hits);
	C7ShadowPrintAt(SmallFont, 13, y+10, value, WHITE);
	y = C7DrawHitMissBlocks(hits/perBlock, y, HITS_COLOR) + 20;

	value.Format("Accuracy = %u%%", accuracy);
	C7PrintCentered(BigFont, y, value, BLUE);
	y += 20;
	value.Format("Bonus = %d points", award);
	C7PrintCentered(BigFont, y, value, BLUE);
	y += 20;
	value.Format("Score = %d points", players[ConsolePlayer].score);
	C7PrintCentered(BigFont, y, value, YELLOW);
	pa = oldpa;
}

// The status report is dismissed with a press that may still be held, and SDL
// repeats a held key: without this, one long press dismissed both pages.
static void C7WaitForFreshAck()
{
	IN_StartAck(ACK_Any);
	while(IN_AnyInputHeld())
	{
		// A peer's acknowledgement still ends the page in a netgame.
		if(Net::CheckAck(false))
		{
			IN_ClearKeysDown();
			return;
		}
		SDL_Delay(5);
	}
	IN_ClearKeysDown();
	while(!IN_CheckAck())
		BJ_Breathe();
	IN_ClearKeysDown();
}

// After the floor's status report, a552 shows a second page in two cases. A
// won campaign (playstate 6, which a0ab sets on leaving the last floor) gets
// MISSION HIT/MISS RATIO over the whole mission's shooting -- every floor's
// counts were added at the next floor's setup (216b4), and this floor's are
// added here. A bonus floor gets BONUS LEVEL HIT/MISS RATIO over its own. The
// finale is tested first, so a pack whose last floor is a bonus floor ends on
// the mission page, as the original's check order would have it.
static void InterDoCorridor7(bool finale)
{
	const C7StatusReport report = C7ScoreStatusReport();
	InterGiveBonus(report.award);
	C7DrawStatusReport(report);
	VW_UpdateScreen();
	VW_FadeIn();
	InterWaitForAck();

	if(!finale && !report.bonusFloor)
		return;

	// Each player is paid for their own shooting, so every machine in a
	// netgame pays the same points; the page shows this screen's player.
	unsigned int accuracy = 0;
	int32_t award = 0;
	uint32_t shots = 0, hits = 0;
	for(unsigned int i = 0;i < Session::ActiveSlotCount();++i)
	{
		const player_t &player = players[i];
		uint32_t playerShots = player.levelShotsFired;
		uint32_t playerHits = player.levelShotsHit;
		if(finale)
		{
			playerShots += player.c7MissionShotsFired;
			playerHits += player.c7MissionShotsHit;
		}
		unsigned int playerAccuracy;
		const int32_t playerAward = C7AccuracyAward(playerShots, playerHits,
			playerAccuracy);
		players[i].GivePoints(playerAward);
		if(i == ConsolePlayer)
		{
			accuracy = playerAccuracy;
			award = playerAward;
			shots = playerShots;
			hits = MIN(playerHits, playerShots);
		}
	}

	Printf("Corridor 7 %s hit/miss: %u shots, %u hits, %u%% accuracy, %d point bonus\n",
		finale ? "mission" : "bonus floor", shots, hits, accuracy, award);

	// The original draws this page straight over the first, without a fade.
	C7DrawHitMissPage(finale, shots, hits, accuracy, award);
	VW_UpdateScreen();
	C7WaitForFreshAck();
}

void Corridor7Death(void)
{
	ClearSplitVWB();
	StartCPMusic(gameinfo.IntermissionMusic);
	IN_ClearKeysDown();
	IN_StartAck(ACK_Any);

	// Full-screen picture page: all text shares the picture's stretched
	// 320x200 mapping rather than the menu scaling.
	const int oldpa = pa;
	pa = MENU_NONE;

	// The DOS death report uses the small repeating skull tile and the
	// centered 128x120 death plate, not the per-floor status-report artwork.
	C7DrawTiledBackdrop(TexMan("C7G0004"));
	C7DrawPlate(TexMan("C7G0003"), 96, 40);

	const unsigned int thisAliens = gamestate.killtotal ?
		(static_cast<unsigned int>(gamestate.killcount)*100)/gamestate.killtotal : 100;
	const unsigned int thisSecrets = gamestate.secrettotal ?
		(static_cast<unsigned int>(gamestate.secretcount)*100)/gamestate.secrettotal : 0;
	const unsigned int floors = LevelRatios.numLevels;
	const unsigned int divisor = floors+1;
	const unsigned int aliens = (LevelRatios.killratio+thisAliens)/divisor;
	const unsigned int secrets = (LevelRatios.secretsratio+thisSecrets)/divisor;
	const unsigned int rating = (aliens+secrets)/2;

	// The released page centers the large-font title over the death plate.
	word titleWidth, titleHeight;
	VW_MeasurePropString(BigFont, "YOU'RE DEAD", titleWidth, titleHeight);
	C7PrintAt(BigFont, 160-titleWidth/2, 70, "YOU'RE DEAD", CR_RED);
	// Measured from the released death report: labels at x=80 on rows ten
	// pixels apart from y=90, values in a fixed column at x=240.
	static const char *labels[] = {
		"Total floors secured", "Alien kill ratio", "Secret room ratio",
		"Total score", "Overall rating"
	};
	for(unsigned int i = 0;i < countof(labels);++i)
		C7PrintAt(SmallFont, 80, 90+i*10, labels[i], CR_TAN);

	FString value;
	value.Format("%u", floors);
	C7PrintAt(SmallFont, 240, 90, value, CR_TAN);
	value.Format("%u%%", aliens);
	C7PrintAt(SmallFont, 240, 100, value, CR_TAN);
	value.Format("%u%%", secrets);
	C7PrintAt(SmallFont, 240, 110, value, CR_TAN);
	value.Format("%d", players[ConsolePlayer].score);
	C7PrintAt(SmallFont, 240, 120, value, CR_TAN);
	value.Format("%u%%", rating);
	C7PrintAt(SmallFont, 240, 130, value, CR_TAN);
	VW_UpdateScreen();
	pa = oldpa;
	VW_FadeIn();
	InterWaitForAck();
	VW_FadeOut();
}

/*
==================
=
= LevelCompleted
=
= Entered with the screen faded out
= Still in split screen mode with the status bar
=
= Exit with the screen faded out
=
==================
*/

void LevelCompleted (bool finale)
{
	DetermineIntermissionMode();

	InterState.bonus = 0;
	InterState.acked = false;

	//
	// FIGURE RATIOS OUT BEFOREHAND
	//
	InterState.kr = InterState.sr = InterState.tr = 100;
	if (gamestate.killtotal)
		InterState.kr = (gamestate.killcount * 100) / gamestate.killtotal;
	if (gamestate.secrettotal)
		InterState.sr = (gamestate.secretcount * 100) / gamestate.secrettotal;
	if (gamestate.treasuretotal)
		InterState.tr = (gamestate.treasurecount * 100) / gamestate.treasuretotal;

	InterState.timeleft = 0;
	if ((unsigned)gamestate.TimeCount < levelInfo->Par * TICRATE)
		InterState.timeleft = (int) (levelInfo->Par - gamestate.TimeCount/TICRATE);

	if((levelInfo->LevelBonus == -1 || levelInfo->ForceTally) &&
		!(IWad::CheckGameFilter("Corridor7") && levelInfo->BonusLevel))
	{
		//
		// SAVE RATIO INFORMATION FOR ENDGAME
		//
		LevelRatios.killratio += InterState.kr;
		LevelRatios.secretsratio += InterState.sr;
		LevelRatios.treasureratio += InterState.tr;
		LevelRatios.time += gamestate.TimeCount/TICRATE;
		LevelRatios.par += levelInfo->Par;
		++LevelRatios.numLevels;
	}

//
// do the intermission
//
	ClearSplitVWB ();           // set up for double buffering in split screen
	VWB_DrawFill(TexMan(levelInfo->GetBorderTexture()), 0, 0, screenWidth, screenHeight);
	DrawPlayScreen(true);

	StartCPMusic (gameinfo.IntermissionMusic);

	IN_ClearKeysDown ();
	IN_StartAck (ACK_Any);

	if(IWad::CheckGameFilter("Corridor7"))
	{
		InterDoCorridor7(finale);
		return;
	}

	BJ_Breathe(true);

	if(levelInfo->LevelBonus == -1 || levelInfo->ForceTally)
	{
		if(levelInfo->LevelBonus > 0)
			InterState.bonus = levelInfo->LevelBonus;

		if(InterState.graphical)
			InterDoGraphical();
		else
			InterDoNormal();
	}
	else
	{
		InterDoBonus();
	}


	StatusBar->DrawStatusBar();
	VW_UpdateScreen ();

	InterWaitForAck();
}

//==========================================================================

/*
==================
=
= Victory
=
==================
*/

void Victory (bool fromIntermission)
{
	DetermineIntermissionMode();

	int kr = 0, sr = 0, tr = 0;

	StartCPMusic (gameinfo.VictoryMusic);
	VWB_DrawFill(TexMan(levelInfo->GetBorderTexture()), 0, 0, screenWidth, screenHeight);
	if(!fromIntermission)
		DrawPlayScreen(true);

	if(LevelRatios.numLevels)
	{
		kr = LevelRatios.killratio / LevelRatios.numLevels;
		sr = LevelRatios.secretsratio / LevelRatios.numLevels;
		tr = LevelRatios.treasureratio / LevelRatios.numLevels;
	}

	if(InterState.graphical)
	{
		VWB_DrawGraphic (TexMan("L_BJWINS"), 8, 8);
		VWB_DrawGraphic (TexMan(GraphicalTexID[WI_RATING]), 104, 32);
		VWB_DrawGraphic (TexMan(GraphicalTexID[WI_PAR]), 120, 56);
		VWB_DrawGraphic (TexMan(GraphicalTexID[WI_TIME]), 112, 72);
		VWB_DrawGraphic (TexMan(GraphicalTexID[WI_KILLS]), 104, 96);
		VWB_DrawGraphic (TexMan(GraphicalTexID[WI_TREASR]), 128, 112);
		VWB_DrawGraphic (TexMan(GraphicalTexID[WI_SECRTS]), 96, 128);

		InterWriteTime(LevelRatios.par, 184, 56, true);
		InterWriteTime(LevelRatios.time, 184, 72, true);

		FString ratioStr;
		ratioStr.Format("%u%%", kr);
		Write(35, 12, ratioStr, true);
		ratioStr.Format("%u%%", tr);
		Write(35, 14, ratioStr, true);
		ratioStr.Format("%u%%", sr);
		Write(35, 16, ratioStr, true);
	}
	else
	{
		static const unsigned int RATIOX = 22, RATIOY = 14, TIMEX = 14, TIMEY = 8;
		int min, sec;
		char tempstr[13];

		VWB_DrawGraphic (TexMan("L_BJWINS"), 8, 4);

		Write (18, 2, language["STR_YOUWIN"]);

		Write (TIMEX, TIMEY - 2, language["STR_TOTALTIME"]);

		Write (12, RATIOY - 2, language["STR_AVERAGES"]);

		Write (RATIOX, RATIOY, language["STR_RATKILL"], true);
		Write (RATIOX, RATIOY + 2, language["STR_RATSECRET"], true);
		Write (RATIOX, RATIOY + 4, language["STR_RATTREASURE"], true);
		Write (RATIOX+8, RATIOY, "%");
		Write (RATIOX+8, RATIOY + 2, "%");
		Write (RATIOX+8, RATIOY + 4, "%");

		sec = LevelRatios.time;

		min = sec / 60;
		sec %= 60;

		if (min > 99)
			min = sec = 99;

		FString timeString;
		timeString.Format("%02d:%02d", min, sec);
		Write (TIMEX, TIMEY, timeString);

		itoa (kr, tempstr, 10);
		Write (RATIOX + 8, RATIOY, tempstr, true);

		itoa (sr, tempstr, 10);
		Write (RATIOX + 8, RATIOY + 2, tempstr, true);

		itoa (tr, tempstr, 10);
		Write (RATIOX + 8, RATIOY + 4, tempstr, true);
	}

	VW_UpdateScreen ();
	VW_FadeIn ();

	IN_Ack (ACK_Any);

	EndText (levelInfo->Cluster);

	VW_FadeOut();
}

//==========================================================================


/*
=================
=
= PreloadGraphics
=
= Fill the cache up
=
=================
*/

bool PreloadUpdate (unsigned current, unsigned total)
{
	if(IWad::CheckGameFilter("Corridor7"))
	{
		double x = 59, y = 98, fullWidth = 200, filledWidth = 200.0*current/total;
		double height = 7, ignoredHeight = 7;
		screen->VirtualToRealCoords(x, y, fullWidth, height, 320, 200, true, true);
		double filledX = 59, filledY = 98;
		screen->VirtualToRealCoords(filledX, filledY, filledWidth, ignoredHeight,
			320, 200, true, true);
		VWB_Clear(GPalette.Remap[0], x, y, x+fullWidth, y+height);
		if(current)
			VWB_Clear(GPalette.Remap[4], filledX, filledY,
				filledX+filledWidth, filledY+ignoredHeight);
		VW_UpdateScreen();
		return false;
	}

	static const PalEntry colors[2] = {
		ColorMatcher.Pick(RPART(gameinfo.PsychedColors[0]), GPART(gameinfo.PsychedColors[0]), BPART(gameinfo.PsychedColors[0])),
		ColorMatcher.Pick(RPART(gameinfo.PsychedColors[1]), GPART(gameinfo.PsychedColors[1]), BPART(gameinfo.PsychedColors[1]))
	};

	double x = 53;
	double y = 101 + gameinfo.PsychedOffset;
	double w = 214.0*current/total;
	double h = 2;
	double ow = w - 1;
	double oh = h - 1;
	double ox = x, oy = y;
	screen->VirtualToRealCoords(x, y, w, h, 320, 200, true, true);
	screen->VirtualToRealCoords(ox, oy, ow, oh, 320, 200, true, true);

	if (current)
	{
		VWB_Clear(colors[0], x, y, x+w, y+h);
		VWB_Clear(colors[1], ox, oy, ox+ow, oy+oh);

	}
	VW_UpdateScreen ();
	return (false);
}

void PreloadGraphics (bool showPsych)
{
	if(showPsych)
	{
		ClearSplitVWB ();           // set up for double buffering in split screen

		VWB_DrawFill(TexMan(levelInfo->GetBorderTexture()), 0, 0, screenWidth, screenHeight);

		if(IWad::CheckGameFilter("Corridor7"))
		{
			// The CD release tiles its skull pattern and places the 224x56
			// loading plate at (48,56). Its red 200x7 meter is drawn by
			// PreloadUpdate inside that plate.
			C7DrawTiledBackdrop(TexMan("C7G0004"));
			C7DrawPlate(TexMan("C7G0073"), 48, 56);
		}
		else
		{
			const bool oldingame = ingame;
			ingame = false;
			DrawPlayScreen(true);
			ingame = oldingame;

			FTextureID getPsyched = TexMan.CheckForTexture("GETPSYCH", FTexture::TEX_Any);
			if(getPsyched.isValid())
				VWB_DrawGraphic(TexMan(getPsyched), 48, 56);
		}

		WindowX = (screenWidth - scaleFactorX*224)/2;
		WindowY = (screenHeight - scaleFactorY*(StatusBar->GetHeight(false)+48))/2;
		WindowW = scaleFactorX * 28 * 8;
		WindowH = scaleFactorY * 48;

		VW_UpdateScreen ();
		VW_FadeIn ();

		PreloadUpdate (5, 10);
	}

	TexMan.PrecacheLevel();

	if(showPsych)
	{
		PreloadUpdate (10, 10);
		IN_UserInput (70, ACK_Any);
		VW_FadeOut ();

		DrawPlayScreen ();
		VW_UpdateScreen ();
	}
}


//==========================================================================

/*
==================
=
= DrawHighScores
=
==================
*/

static void PrepareCorridor7HighScores()
{
	if(!IWad::CheckGameFilter("Corridor7"))
		return;

	// High scores predate per-game config sections, so a fresh ECWolf config
	// starts with Wolf3D's seven developer names. Replace only that untouched
	// stock table; once the player has earned or edited any entry it is theirs.
	static const char *wolfDefaults[MaxScores] = {
		"id software-'92", "Adrian Carmack", "John Carmack", "Kevin Cloud",
		"Tom Hall", "John Romero", "Jay Wilbur"
	};
	for(unsigned int i = 0;i < MaxScores;++i)
	{
		if(strcmp(Scores[i].name, wolfDefaults[i]) != 0 || Scores[i].score != 10000 ||
			Scores[i].completed.Compare("1") != 0)
			return;
	}

	static const char *corridor7Defaults[MaxScores] = {
		"Capstone 94", "Les", "Joe", "Jeff", "Ruben", "Carlos", "David"
	};
	for(unsigned int i = 0;i < MaxScores;++i)
	{
		strncpy(Scores[i].name, corridor7Defaults[i], MaxHighName);
		Scores[i].name[MaxHighName] = 0;
		Scores[i].score = 10000;
		Scores[i].completed = "1";
		Scores[i].graphic[0] = 0;
	}
}

void DrawHighScores (void)
{
	PrepareCorridor7HighScores();
	FString buffer;

	word i, w, h;
	HighScore *s;

	FFont *font = V_GetFont(gameinfo.HighScoresFont);

	if(IWad::CheckGameFilter("Corridor7"))
		CA_CacheScreen(TexMan("C7G0016"));
	else
		ClearMScreen ();
	if(IWad::CheckGameFilter("Corridor7"))
	{
		// This page is a full-screen picture, so all of its text must use the
		// same stretched 320x200 mapping as the picture, not the menu scaling.
		const int oldpa = pa;
		pa = MENU_NONE;
		word titleWidth, titleHeight;
		// Every string has the text routine's black drop shadow, which shows
		// wherever the picture behind is light.
		VW_MeasurePropString(font, "HIGH SCORES", titleWidth, titleHeight);
		C7ShadowPrintAt(font, 160-titleWidth/2, 20, "HIGH SCORES", 0xB7);
		C7ShadowPrintAt(font, 24, 43, "NAME", 0x24);
		C7ShadowPrintAt(font, 210, 43, "L", 0x24);
		C7ShadowPrintAt(font, 246, 43, "SCORE", 0x24);
		for(i = 0, s = Scores; i < MaxScores; ++i, ++s)
		{
			// CORR7CD.EXE draws row i at (0x3c + 0x12*i) + 2.
			PrintY = 62 + 18*i;
			buffer.Format("%u.", i+1);
			const BYTE rowColor = static_cast<BYTE>(0x57-2*i);
			const BYTE levelColor = static_cast<BYTE>(0x6F-2*i);
			C7ShadowPrintAt(font, 6, PrintY, buffer, rowColor);
			C7ShadowPrintAt(font, 24, PrintY, s->name, rowColor);
			C7ShadowPrintAt(font, 210, PrintY, s->completed.GetChars(), levelColor);
			buffer.Format("%d", s->score);
			VW_MeasurePropString(font, buffer, w, h);
			C7ShadowPrintAt(font, 300-w, PrintY, buffer, rowColor);
		}
		pa = oldpa;
		VW_UpdateScreen();
		return;
	}

	FTexture *highscores = TexMan("HGHSCORE");
	DrawStripes (10);
	if(highscores->GetScaledWidth() < 320)
		VWB_DrawGraphic(highscores, 160-highscores->GetScaledWidth()/2, 0, MENU_TOP);
	else
		VWB_DrawGraphic(highscores, 0, 0, MENU_TOP);

	static FTextureID texName = TexMan.CheckForTexture("M_NAME", FTexture::TEX_Any);
	static FTextureID texLevel = TexMan.CheckForTexture("M_LEVEL", FTexture::TEX_Any);
	static FTextureID texScore = TexMan.CheckForTexture("M_SCORE", FTexture::TEX_Any);
	if(texName.isValid())
		VWB_DrawGraphic(TexMan(texName), 16, 68);
	if(texLevel.isValid())
		VWB_DrawGraphic(TexMan(texLevel), 194 - TexMan(texLevel)->GetScaledWidth()/2, 68);
	if(texScore.isValid())
		VWB_DrawGraphic(TexMan(texScore), 240, 68);

	for (i = 0, s = Scores; i < MaxScores; i++, s++)
	{
		PrintY = 76 + ((font->GetHeight() + 3) * i);

		//
		// name
		//
		PrintX = 16;
		US_Print (font, s->name, gameinfo.FontColors[GameInfo::HIGHSCORES]);

		//
		// level
		//
		buffer.Format("%s", s->completed.GetChars());
		VW_MeasurePropString (font, buffer, w, h);
		PrintX = 194 - w;

		bool drawNumber = true;
		if (s->graphic[0])
		{
			FTextureID graphic = TexMan.CheckForTexture(s->graphic, FTexture::TEX_Any);
			if(graphic.isValid())
			{
				FTexture *tex = TexMan(graphic);

				drawNumber = false;
				VWB_DrawGraphic (tex, 194 - tex->GetScaledWidth(), PrintY - 1, MENU_CENTER);
			}
		}

		if(drawNumber)
			US_Print (font, buffer, gameinfo.FontColors[GameInfo::HIGHSCORES]);

		//
		// score
		//
		buffer.Format("%d", s->score);
		VW_MeasurePropString (font, buffer, w, h);
		PrintX = 292 - w;
		US_Print (font, buffer, gameinfo.FontColors[GameInfo::HIGHSCORES]);
	}

	VW_UpdateScreen ();
}

//===========================================================================


/*
=======================
=
= CheckHighScore
=
=======================
*/

// Whether CheckHighScore would put this score in the table. A won Corridor 7
// campaign only shows the table when it does: a2cc asks 2a49 for a rank and
// skips the page and its wait when there is none.
bool HighScoreWouldRank (int32_t score, const LevelInfo *levelInfo)
{
	if (!gameinfo.TrackHighScores || !Session::TracksHighScores())
		return false;
	PrepareCorridor7HighScores();

	FString completed;
	completed = levelInfo->FloorNumber;
	for (unsigned int i = 0; i < MaxScores; i++)
	{
		if ((score > Scores[i].score)
			|| ((score == Scores[i].score) && (completed.Compare(Scores[i].completed) > 0)))
			return true;
	}
	return false;
}

void CheckHighScore (int32_t score, const LevelInfo *levelInfo)
{
	if (!gameinfo.TrackHighScores || !Session::TracksHighScores())
		return;
	PrepareCorridor7HighScores();

	word i, j;
	int n;
	HighScore myscore;

	strcpy (myscore.name, "");
	myscore.score = score;
	myscore.completed = levelInfo->FloorNumber;
	if(levelInfo->HighScoresGraphic.isValid())
	{
		strncpy(myscore.graphic, TexMan[levelInfo->HighScoresGraphic]->Name, 8);
		myscore.graphic[8] = 0;
	}
	else
		myscore.graphic[0] = 0;

	for (i = 0, n = -1; i < MaxScores; i++)
	{
		if ((myscore.score > Scores[i].score)
			|| ((myscore.score == Scores[i].score) && (myscore.completed.Compare(Scores[i].completed) > 0)))
		{
			for (j = MaxScores; --j > i;)
				Scores[j] = Scores[j - 1];
			Scores[i] = myscore;
			n = i;
			break;
		}
	}

	StartCPMusic (gameinfo.ScoresMusic);
	DrawHighScores ();

	VW_FadeIn ();

	if (n != -1)
	{
		FFont *font = V_GetFont(gameinfo.HighScoresFont);

		//
		// got a high score
		//
		if(IWad::CheckGameFilter("Corridor7"))
		{
			// The earned row as 2a7e draws it before asking for a name
			// (241ab): a navy bar across the row in a yellow frame, the
			// floor and score redrawn over it with the usual black shadow,
			// and the name typed in the score's colour without one (the
			// line-input routine draws its own text) -- at most 18
			// characters in 262 pixels. All in the picture's mapping.
			const int oldpa = pa;
			pa = MENU_NONE;
			static const BYTE BAR = 0x30, FRAME = 0x6f;
			const int top = 60 + 18*n;
			C7FillRect(20, top, 280, 16, BAR);
			C7FillRect(20, top, 281, 1, FRAME);
			C7FillRect(20, top+16, 281, 1, FRAME);
			C7FillRect(20, top, 1, 17, FRAME);
			C7FillRect(300, top, 1, 17, FRAME);

			const BYTE rowColor = static_cast<BYTE>(0x57-2*n);
			const BYTE levelColor = static_cast<BYTE>(0x6F-2*n);
			C7ShadowPrintAt(font, 210, top+2, Scores[n].completed.GetChars(), levelColor);
			FString scoreText;
			scoreText.Format("%d", Scores[n].score);
			word scoreWidth, scoreHeight;
			VW_MeasurePropString(font, scoreText, scoreWidth, scoreHeight);
			C7ShadowPrintAt(font, 300-scoreWidth, top+2, scoreText, rowColor);

			US_LineInputColor = rowColor;
			PrintY = top + 2;
			PrintX = 24;
			US_LineInput (font,PrintX, PrintY, Scores[n].name, 0, true, 18, 262, BAR, CR_WHITE);
			US_LineInputColor = -1;
			pa = oldpa;

			// Both of the original's callers (a21d after a death, a31c after
			// the campaign) leave the finished table up for IN_UserInput(420),
			// six seconds or a keypress, before going back to the title.
			IN_ClearKeysDown ();
			IN_UserInput (420, ACK_Local);
		}
		else
		{
			PrintY = 76 + ((font->GetHeight() + 3) * n);
			PrintX = 16;
			US_LineInput (font,PrintX, PrintY, Scores[n].name, 0, true, MaxHighName, 130, BKGDCOLOR, CR_WHITE);
		}
	}
	else
	{
		IN_ClearKeysDown ();
		IN_UserInput (IWad::CheckGameFilter("Corridor7") ? 420 : 500, ACK_Local);
	}

	VW_FadeOut();
}
