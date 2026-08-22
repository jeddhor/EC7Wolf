#include <cmath>
#include <climits>

#include "wl_def.h"
#include "wl_agent.h"
#include "wl_game.h"
#include "wl_play.h"
#include "textures/textures.h"
#include "id_ca.h"
#include "id_us.h"
#include "id_vh.h"
#include "scanner.h"
#include "w_wad.h"
#include "m_random.h"
#include "colormatcher.h"
#include "v_video.h"
#include "thingdef/thingdef.h"
#include "g_mapinfo.h"
#include "a_inventory.h"
#include "a_keys.h"
#include "wl_iwad.h"
#include "wl_net.h"

/*
=============================================================================

							STATUS WINDOW STUFF

=============================================================================
*/

#define STATUSLINES     40

struct LatchConfig
{
	unsigned int Enabled;
	unsigned int Digits;
	unsigned int X;
	unsigned int Y;
};
static struct StatusBarConfig_t
{
	LatchConfig Floor, Score, Lives, Health, Ammo;
	LatchConfig Items;

	// The following don't use the digits
	LatchConfig Mugshot, Keys, Weapon;
} StatusBarConfig = {
	{1, 2, 16, 16},
	{1, 6, 48, 16},
	{1, 1, 112, 16},
	{1, 3, 168, 16},
	{1, 3, 208, 16},
	{0, 2, 280, 16},
	{1, 0, 136, 4},
	{1, 0, 240, 4},
	{1, 0, 256, 8}
};

class WolfStatusBar : public DBaseStatusBar
{
public:
	WolfStatusBar() : facecount(0), mac(false), corridor7(false), topMessageUntil(0),
		c7ChamberPower(0), c7ChamberPowerUntil(0)
	{
		if(IWad::CheckGameFilter("Corridor7"))
		{
			// Corridor 7's released HUD is composed from VGA chunks instead of
			// Wolf3D's STBACK/face set. Keep the gameplay information available
			// without looking up unrelated Wolf textures.
			corridor7 = true;
		}
		else if(IWad::CheckGameFilter("Noah"))
		{
			// Change default configuration
			StatusBarConfig.Floor.X = 16;
			StatusBarConfig.Floor.Digits = 3;
			StatusBarConfig.Score.X = 64;
			StatusBarConfig.Lives.X = 128;
			StatusBarConfig.Health.X = 184;
			StatusBarConfig.Ammo.X = 224;
			StatusBarConfig.Items.Enabled = true;
			StatusBarConfig.Mugshot.X = 152;
			StatusBarConfig.Keys.X = 256;
			StatusBarConfig.Weapon.Enabled = false;
		}
		else if(IWad::CheckGameFilter("MacWolf3D"))
		{
			mac = true;
			StatusBarConfig.Floor.X = 8;
			StatusBarConfig.Floor.Digits = 4;
			StatusBarConfig.Score.Digits = 7;
			StatusBarConfig.Score.X = 56;
			StatusBarConfig.Lives.X = 188;
			StatusBarConfig.Health.X = 210;
			StatusBarConfig.Ammo.Digits = 3;
			StatusBarConfig.Ammo.X = 268;
			StatusBarConfig.Items.X = 128;
			StatusBarConfig.Items.Enabled = true;
			StatusBarConfig.Mugshot.X = 160;
			StatusBarConfig.Keys.X = 310;
			StatusBarConfig.Weapon.Enabled = false;
		}

		SetupStatusbar();
	}

	void DrawStatusBar();
	void DrawTopOverlay();
	void SetTopMessage(const char *message, unsigned int duration);
	void SetC7HealthChamberPower(unsigned int power, unsigned int duration);
	unsigned int GetHeight(bool top) { return top ? 0 : STATUSLINES+!mac; }
	void NewGame() { facecount = 0; topMessage = ""; topMessageUntil = 0; c7ChamberPowerUntil = 0; }
	void RefreshBackground(bool noborder);
	void UpdateFace(int damage=0);
	void WeaponGrin();

private:
	static void LatchNumber (int x, int y, unsigned width, int32_t number, bool zerofill, bool cap=false);
	static void LatchString (int x, int y, unsigned width, const FString &str);
	static void DrawC7Gauge(int x, int y, unsigned int width, unsigned int height,
		unsigned int paletteStart);
	static void DrawC7GradientBar(int x, int y, unsigned int width,
		unsigned int fullWidth, unsigned int height, unsigned int paletteStart,
		unsigned int paletteColors);
	static void StatusDrawFace(FTexture *pic);
	static void StatusDrawPic(unsigned x, unsigned y, const char* pic);

	void DrawAmmo();
	void DrawFace();
	void DrawLevel();
	void DrawLives();
	void DrawHealth();
	void DrawItems();
	void DrawKeys();
	void DrawScore();
	void DrawWeapon();
	void SetupStatusbar();

	int facecount;
	bool mac;
	bool corridor7;
	FString topMessage;
	int32_t topMessageUntil;
	unsigned int c7ChamberPower;
	int32_t c7ChamberPowerUntil;
};

DBaseStatusBar *CreateStatusBar_Wolf3D() { return new WolfStatusBar(); }

/*
==================
=
= StatusDrawPic
=
==================
*/

void WolfStatusBar::StatusDrawPic (unsigned x, unsigned y, const char* pic)
{
	VWB_DrawGraphic(TexMan(pic), x, 200-(STATUSLINES-y));
}

void WolfStatusBar::StatusDrawFace(FTexture *pic)
{
	VWB_DrawGraphic(pic, StatusBarConfig.Mugshot.X, 200-(STATUSLINES-StatusBarConfig.Mugshot.Y));
}


/*
==================
=
= DrawFace
=
==================
*/

void WolfStatusBar::DrawFace (void)
{
	if((viewsize == 21 && ingame) || !StatusBarConfig.Mugshot.Enabled) return;

	if(!gamestate.faceframe.isValid())
	{
		facecount = 0;
		UpdateFace();
	}

	if (players[ConsolePlayer].health)
		StatusDrawFace(TexMan(gamestate.faceframe));
	else
	{
		// TODO: Make this work based on damage types.
		// It gets uglier now that we can blame the source of a projectile we
		// have to check the class that fired it which is just wrong. One of
		// these days I'll get damage types in!
		static const ClassDef *schabbs = ClassDef::FindClass("Schabbs");
		if (players[ConsolePlayer].killerobj && players[ConsolePlayer].killerobj->IsKindOf(schabbs))
			StatusDrawFace(TexMan("STFMUT0"));
		else
			StatusDrawFace(TexMan("STFDEAD0"));
	}
}

/*
===============
=
= UpdateFace
=
= Calls draw face if time to change
=
===============
*/

void WolfStatusBar::WeaponGrin ()
{
	static FTextureID grin = TexMan.CheckForTexture("STFEVL0", FTexture::TEX_Any);
	gamestate.faceframe = grin;
	facecount = 140;
}

void WolfStatusBar::UpdateFace (int damage)
{
	static int oldDamageLevel = 0;
	static bool noGodFace = false;
	static FTextureID godmodeFace[3] = { TexMan.CheckForTexture("STFGOD0", FTexture::TEX_Any), TexMan.CheckForTexture("STFGOD1", FTexture::TEX_Any), TexMan.CheckForTexture("STFGOD2", FTexture::TEX_Any) };
	static FTextureID waitFace[2] = { TexMan.CheckForTexture("STFWAIT0", FTexture::TEX_Any), TexMan.CheckForTexture("STFWAIT1", FTexture::TEX_Any) };
	static FTextureID animations[7][3] =
	{
		{ TexMan.CheckForTexture("STFST00", FTexture::TEX_Any), TexMan.CheckForTexture("STFST01", FTexture::TEX_Any), TexMan.CheckForTexture("STFST02", FTexture::TEX_Any) },
		{ TexMan.CheckForTexture("STFST10", FTexture::TEX_Any), TexMan.CheckForTexture("STFST11", FTexture::TEX_Any), TexMan.CheckForTexture("STFST12", FTexture::TEX_Any) },
		{ TexMan.CheckForTexture("STFST20", FTexture::TEX_Any), TexMan.CheckForTexture("STFST21", FTexture::TEX_Any), TexMan.CheckForTexture("STFST22", FTexture::TEX_Any) },
		{ TexMan.CheckForTexture("STFST30", FTexture::TEX_Any), TexMan.CheckForTexture("STFST31", FTexture::TEX_Any), TexMan.CheckForTexture("STFST32", FTexture::TEX_Any) },
		{ TexMan.CheckForTexture("STFST40", FTexture::TEX_Any), TexMan.CheckForTexture("STFST41", FTexture::TEX_Any), TexMan.CheckForTexture("STFST42", FTexture::TEX_Any) },
		{ TexMan.CheckForTexture("STFST50", FTexture::TEX_Any), TexMan.CheckForTexture("STFST51", FTexture::TEX_Any), TexMan.CheckForTexture("STFST52", FTexture::TEX_Any) },
		{ TexMan.CheckForTexture("STFST60", FTexture::TEX_Any), TexMan.CheckForTexture("STFST61", FTexture::TEX_Any), TexMan.CheckForTexture("STFST62", FTexture::TEX_Any) },
	};
	static unsigned int faceAmimSet = animations[0][2].isValid() ? 3 : 2;
	static bool macDamage = !animations[2][0].isValid();

	const int maxHealth = players[ConsolePlayer].mo ? players[ConsolePlayer].mo->maxhealth : 100;
	const int damageLevel = macDamage ? (players[ConsolePlayer].health > (maxHealth>>2) ? 0 : 1)
		: MIN(6, players[ConsolePlayer].health > maxHealth ? 0 : (maxHealth-players[ConsolePlayer].health)/(maxHealth/6));
	if(damage)
	{
		static FTextureID ouchFace = TexMan.CheckForTexture("STFOUCH0", FTexture::TEX_Any);
		if(ouchFace.isValid() && damage > 30 && players[ConsolePlayer].health != 0)
		{
			gamestate.faceframe = ouchFace;
			facecount = 17;
		}
		else
		{
			// Update the face only if we've changed damage levels.
			if(damageLevel == oldDamageLevel)
				return;
			facecount = 0;
		}
	}
	oldDamageLevel = damageLevel;

	// OK Wolf apparently did something more along the lines of ++facecount > M_Random()
	// This doesn't seem to work as well with the new random generator, so lets take a different approach.
	if (--facecount <= 0)
	{
		facecount = ((M_Random()>>3)|0xF);

		if (funnyticount > 301 * 70)
		{
			funnyticount = 0;
			FTextureID pickedID = waitFace[M_Random() & 1];
			if(pickedID.isValid())
			{
				gamestate.faceframe = pickedID;
				facecount = 17;
				return;
			}
		}

		unsigned int facePick = M_Random()%faceAmimSet;

		if(godmode && !noGodFace)
		{
			gamestate.faceframe = godmodeFace[facePick];

			if(!gamestate.faceframe.isValid())
			{
				if(!godmodeFace[0].isValid())
					noGodFace = true;
				godmodeFace[1] = godmodeFace[2] = godmodeFace[0];
			}
			else
				return;
		}

		if(players[ConsolePlayer].mo)
			gamestate.faceframe = animations[damageLevel][facePick];
		else
			gamestate.faceframe = animations[0][0];
	}
}



/*
===============
=
= LatchNumber
=
= right justifies and pads with blanks
=
===============
*/

static const int ninestbl[10] = {
	0, 9, 99, 999, 9999,
	99999, 999999, 9999999,
	99999999, 999999999
};

void WolfStatusBar::LatchNumber (int x, int y, unsigned width, int32_t number, bool zerofill, bool cap)
{
	FString str;
	if(zerofill)
		str.Format("%0*d", width, number);
	else
		str.Format("%*d", width, number);
	if(str.Len() > width && cap)
	{
		int maxval = width <= 9 ? ninestbl[width] : INT_MAX;
		str.Format("%d", maxval);
	}

	LatchString(x, y, width, str);
}

void WolfStatusBar::LatchString (int x, int y, unsigned width, const FString &str)
{
	static FFont *HudFont = NULL;
	if(!HudFont)
	{
		HudFont = V_GetFont("HudFont");
	}

	y = 200-(STATUSLINES-y);// + HudFont->GetHeight();

	int cwidth;
	FRemapTable *remap = HudFont->GetColorTranslation(CR_UNTRANSLATED);
	for(unsigned int i = MAX<int>(0, (int)(str.Len()-width));i < str.Len();++i)
	{
		VWB_DrawGraphic(HudFont->GetChar(str[i], &cwidth), x, y, MENU_NONE, remap);
		x += cwidth;
	}
}

void WolfStatusBar::DrawC7Gauge(int x, int y, unsigned int width, unsigned int height,
	unsigned int paletteStart)
{
	if(width == 0 || height == 0)
		return;

	// DOS advances one native palette entry after every three columns. At a
	// nominal width of 25 the final column reaches the black separator that
	// follows each eight-entry HUD ramp.
	width = MIN(width, 25U);
	for(unsigned int column = 0;column < width;++column)
	{
		int realX = x + column;
		int realY = y;
		int realWidth = 1;
		int realHeight = height;
		screen->VirtualToRealCoordsInt(realX, realY, realWidth, realHeight,
			320, 200, true, true);
		const int color = GPalette.Remap[
			MIN<unsigned int>(255, paletteStart+column/3)];
		screen->Clear(realX, realY, realX + realWidth, realY + realHeight,
			color, GPalette.BaseColors[color]);
	}
}

void WolfStatusBar::DrawC7GradientBar(int x, int y, unsigned int width,
	unsigned int fullWidth, unsigned int height, unsigned int paletteStart,
	unsigned int paletteColors)
{
	if(width == 0 || fullWidth == 0 || height == 0 || paletteColors == 0)
		return;

	// Unlike the 25-column status-bar gauges, this meter stretches one complete
	// palette ramp over the width of the artwork's recessed well. Keeping the
	// shade tied to the original column also makes a depleted chamber reveal the
	// red C7G0062 background from right to left without rescaling the gradient.
	width = MIN(width, fullWidth);
	for(unsigned int column = 0;column < width;++column)
	{
		int realX = x + column;
		int realY = y;
		int realWidth = 1;
		int realHeight = height;
		screen->VirtualToRealCoordsInt(realX, realY, realWidth, realHeight,
			320, 200, true, true);
		const unsigned int shade = MIN(paletteColors-1,
			(column*paletteColors)/fullWidth);
		const int color = GPalette.Remap[
			MIN<unsigned int>(255, paletteStart+shade)];
		screen->Clear(realX, realY, realX + realWidth, realY + realHeight,
			color, GPalette.BaseColors[color]);
	}
}


/*
===============
=
= DrawHealth
=
===============
*/

void WolfStatusBar::DrawHealth (void)
{
	if((viewsize == 21 && ingame) || !StatusBarConfig.Health.Enabled) return;
	LatchNumber (StatusBarConfig.Health.X,StatusBarConfig.Health.Y,StatusBarConfig.Health.Digits,players[ConsolePlayer].health,mac,true);
}

//===========================================================================


/*
===============
=
= DrawLevel
=
===============
*/

void WolfStatusBar::DrawLevel (void)
{
	if((viewsize == 21 && ingame) || !StatusBarConfig.Floor.Enabled) return;
	FString str;
	str.Format("%*s", StatusBarConfig.Floor.Digits, levelInfo->FloorNumber.GetChars());
	LatchString (StatusBarConfig.Floor.X,StatusBarConfig.Floor.Y,StatusBarConfig.Floor.Digits,str);
}

//===========================================================================


/*
===============
=
= DrawLives
=
===============
*/

void WolfStatusBar::DrawLives (void)
{
	if((viewsize == 21 && ingame) || (!StatusBarConfig.Lives.Enabled) || (gamestate.difficulty->LivesCount < 0)) return;
	LatchNumber (StatusBarConfig.Lives.X,StatusBarConfig.Lives.Y,StatusBarConfig.Lives.Digits,players[ConsolePlayer].lives,mac);
}

//===========================================================================


/*
===============
=
= DrawItems
=
===============
*/

void WolfStatusBar::DrawItems (void)
{
	if((viewsize == 21 && ingame) || !StatusBarConfig.Items.Enabled || players[ConsolePlayer].mo == NULL) return;

	AInventory *items = players[ConsolePlayer].mo->FindInventory(ClassDef::FindClass("MacTreasureItem"));
	unsigned int amount = 0;
	if(items)
		amount = items->amount;

	LatchNumber (StatusBarConfig.Items.X,StatusBarConfig.Items.Y,StatusBarConfig.Items.Digits,amount,mac);
}

//===========================================================================

/*
===============
=
= DrawScore
=
===============
*/

void WolfStatusBar::DrawScore (void)
{
	if((viewsize == 21 && ingame) || !StatusBarConfig.Score.Enabled) return;

	int32_t score = players[ConsolePlayer].score;
	if(Net::Deathmatch())
		score = players[ConsolePlayer].frags;

	LatchNumber (StatusBarConfig.Score.X,StatusBarConfig.Score.Y,StatusBarConfig.Score.Digits,score,mac);
}

//===========================================================================

/*
==================
=
= DrawWeapon
=
==================
*/

void WolfStatusBar::DrawWeapon (void)
{
	if((viewsize == 21 && ingame) || !StatusBarConfig.Weapon.Enabled ||
		players[ConsolePlayer].ReadyWeapon == NULL ||
		players[ConsolePlayer].ReadyWeapon->icon.isNull()
	)
		return;

	VWB_DrawGraphic(TexMan(players[ConsolePlayer].ReadyWeapon->icon), StatusBarConfig.Weapon.X, 200-(STATUSLINES-StatusBarConfig.Weapon.Y));
}


/*
==================
=
= DrawKeys
=
==================
*/

void WolfStatusBar::DrawKeys (void)
{
	if((viewsize == 21 && ingame) || !StatusBarConfig.Keys.Enabled) return;
	static bool extendedKeysGraphics = TexMan.CheckForTexture("STKEYS3", FTexture::TEX_Any).isValid();
	static bool emptyKeysGraphic = TexMan.CheckForTexture("STKEYS0", FTexture::TEX_Any).isValid();

	// Find keys in inventory
	unsigned int presentKeys = 0;
	if(players[ConsolePlayer].mo)
	{
		for(AInventory *item = players[ConsolePlayer].mo->inventory;item != NULL;item = item->inventory)
		{
			if(item->IsKindOf(NATIVE_CLASS(Key)))
			{
				unsigned int slot = static_cast<AKey *>(item)->KeyNumber;
				if(slot <= 4)
					presentKeys |= 1<<(slot-1);
				if(presentKeys == 15)
					break;
			}
		}
	}

	const unsigned int x = StatusBarConfig.Keys.X;
	unsigned int y = StatusBarConfig.Keys.Y;
	if (extendedKeysGraphics && (presentKeys & (1|4)) == (1|4))
		StatusDrawPic (x,y,"STKEYS5");
	else if(extendedKeysGraphics && (presentKeys & 4))
		StatusDrawPic (x,y,"STKEYS3");
	else if(presentKeys & 1)
		StatusDrawPic (x,y,"STKEYS1");
	else if(emptyKeysGraphic)
		StatusDrawPic (x,y,"STKEYS0");

	y += mac ? 20 : 16;
	if (extendedKeysGraphics && (presentKeys & (2|8)) == (2|8))
		StatusDrawPic (x,y,"STKEYS6");
	else if (extendedKeysGraphics && (presentKeys & 8))
		StatusDrawPic (x,y,"STKEYS4");
	else if (presentKeys & 2)
		StatusDrawPic (x,y,"STKEYS2");
	else if (emptyKeysGraphic)
		StatusDrawPic (x,y,"STKEYS0");
}

//===========================================================================

/*
===============
=
= DrawAmmo
=
===============
*/

void WolfStatusBar::DrawAmmo (void)
{
	if((viewsize == 21 && ingame) || !StatusBarConfig.Ammo.Enabled ||
		!players[ConsolePlayer].ReadyWeapon || !players[ConsolePlayer].ReadyWeapon->ammo[AWeapon::PrimaryFire])
		return;

	unsigned int amount = players[ConsolePlayer].ReadyWeapon->ammo[AWeapon::PrimaryFire]->amount;
	LatchNumber (StatusBarConfig.Ammo.X,StatusBarConfig.Ammo.Y,StatusBarConfig.Ammo.Digits,amount,mac,true);
}

//===========================================================================

void WolfStatusBar::RefreshBackground(bool noborder)
{
	DBaseStatusBar::RefreshBackground(noborder);

	if(viewsize == 21 && ingame)
		return;
	if(corridor7)
	{
		VWB_DrawGraphic(TexMan("STBAR"), 0, 160);
		return;
	}

	VWB_DrawGraphic(TexMan("STBACK"), 0, 160);
}

void WolfStatusBar::DrawStatusBar()
{
	if(viewsize == 21 && ingame)
		return;
	if(corridor7)
	{
		VWB_DrawGraphic(TexMan("STBAR"), 0, 160);
		FString level;
		level.Format("%2s", levelInfo->FloorNumber.GetChars());
		LatchString(10, 16, 2, level);
		LatchNumber(30, 16, 7, players[ConsolePlayer].score, false, true);
		unsigned int ammo = 0;
		if(players[ConsolePlayer].ReadyWeapon &&
			players[ConsolePlayer].ReadyWeapon->ammo[AWeapon::PrimaryFire])
		{
			AAmmo *readyAmmo = players[ConsolePlayer].ReadyWeapon->ammo[AWeapon::PrimaryFire];
			ammo = readyAmmo->amount;
		}
		LatchNumber(296, 16, 2,
			MAX(0, gamestate.killtotal-gamestate.killcount), false, true);

		if(players[ConsolePlayer].mo)
		{
			AActor *pawn = players[ConsolePlayer].mo;
			AInventory *armor = pawn->FindInventory(ClassDef::FindClass("C7BodyArmor"));
			AInventory *mines = pawn->FindInventory(ClassDef::FindClass("C7Mines"));
			AInventory *visor = pawn->FindInventory(ClassDef::FindClass("C7VisorCharge"));

			DrawC7Gauge(97, 172,
				MIN(25U, unsigned(MAX(0, players[ConsolePlayer].health))>>2),
				5, players[ConsolePlayer].health < 32 ? 80 : 128);
			DrawC7Gauge(97, 191,
				MIN(25U, unsigned(armor ? armor->amount : 0)>>2), 5, 56);
			DrawC7Gauge(200, 172, MIN(25U, ammo>>2), 5, 104);
			DrawC7Gauge(200, 190,
				MIN(25U, unsigned(mines ? mines->amount : 0)), 5, 104);
			DrawC7Gauge(149, 193,
				MIN(25U, unsigned(visor ? visor->amount : 0)>>2), 3, 56);

			const char *itemGraphics[3] =
			{
				"C7G0019", "C7G0020", "C7G0021"
			};
			const char *itemClasses[3] =
			{
				"C7Static001", "C7Static002", "C7FloorPlan"
			};
			unsigned int slot = 0;
			for(;slot < 3;++slot)
				VWB_DrawGraphic(TexMan("C7G0018"), 256+slot*8, 176);
			slot = 0;
			for(unsigned int item = 0;item < 3 && slot < 3;++item)
			{
				if(pawn->FindInventory(ClassDef::FindClass(itemClasses[item])))
					VWB_DrawGraphic(TexMan(itemGraphics[item]), 256+(slot++)*8, 176);
			}
		}
		return;
	}

	VWB_DrawGraphic(TexMan("STBAR"), 0, 160);
	DrawFace ();
	DrawHealth ();
	DrawLives ();
	DrawLevel ();
	DrawAmmo ();
	DrawKeys ();
	DrawWeapon ();
	DrawScore ();
	DrawItems ();
}

static void DrawC7TopMessage(const char *message)
{
	// The DOS notification renderer offsets a black copy by one virtual pixel
	// before painting a solid, full-bright yellow stencil. Using the regular
	// font color ramp preserved the font's dark shades, which made the letters
	// look smoke-stained by the scene lighting.
	//
	// The yellow is measured, not chosen: a DOSBox capture of the CD release on
	// MAP01 draws this message in exactly (255,255,0), with no intermediate
	// shades at all. Palette entry 3 was used here before and is (215,215,0),
	// which is close enough to look right over a dark wall and visibly dull --
	// smoky, which is the word the symptom keeps attracting -- over the bright
	// ceiling gradient that MAP01 opens on.
	//
	// Asking for the colour rather than an index because the palette holds three
	// identical pure yellows (111, 231 and 253) and a screenshot cannot say
	// which one the DOS code named. They differ only under the palette rewrites
	// C7 does for the visor and for damage, and picking by eye there would be
	// guessing.
	screen->DrawText(SmallFont, CR_BLACK, 5, 5, message,
		DTA_FillColor, GPalette.BaseColors[GPalette.BlackIndex].d,
		DTA_VirtualWidth, 320, DTA_VirtualHeight, 200, TAG_DONE);
	screen->DrawText(SmallFont, CR_YELLOW, 4, 4, message,
		DTA_FillColor, PalEntry(255, 255, 0).d,
		DTA_VirtualWidth, 320, DTA_VirtualHeight, 200, TAG_DONE);
}

void WolfStatusBar::DrawTopOverlay()
{
	if(corridor7 && gamestate.TimeCount < c7ChamberPowerUntil)
	{
		// The decoded 48x32 C7G0062 panel contains a 42x5 red meter well at
		// (3,24). Derive that rectangle from the texture's rendered dimensions
		// so both the panel and its fill use the same 320x200 virtual mapping at
		// every output resolution.
		FTexture *const panel = TexMan("C7G0062");
		const int panelX = 4;
		const int panelY = 4;
		const unsigned int meterLeft = 3;
		const unsigned int meterRight = 3;
		const unsigned int meterBottom = 3;
		const unsigned int meterHeight = 5;
		VWB_DrawGraphic(panel, panelX, panelY);
		if(panel != NULL && panel->GetScaledWidth() > int(meterLeft+meterRight) &&
			panel->GetScaledHeight() > int(meterHeight+meterBottom))
		{
			const unsigned int meterWidth = panel->GetScaledWidth()-meterLeft-meterRight;
			const unsigned int power = MIN(c7ChamberPower, 100U);
			const unsigned int filledWidth = (power*meterWidth+50)/100;
			const int meterX = panelX+meterLeft;
			const int meterY = panelY+panel->GetScaledHeight()-meterBottom-meterHeight;
			DrawC7GradientBar(meterX, meterY, filledWidth, meterWidth,
				meterHeight, 128, 8);
		}
		return;
	}

	if(corridor7 && !topMessage.IsEmpty() && gamestate.TimeCount < topMessageUntil)
	{
		DrawC7TopMessage(topMessage.GetChars());
		return;
	}

	// The mission prompt is a short level-introduction overlay, not permanent
	// status-bar content. Drawing it every rendered frame also prevents the
	// alternating-frame flicker caused by the status bar's update cadence.
	if(corridor7 && gamestate.TimeCount < 5*TICRATE)
		DrawC7TopMessage("Eliminate Aliens To Secure Floor");
}

void WolfStatusBar::SetTopMessage(const char *message, unsigned int duration)
{
	if(!corridor7 || message == NULL || *message == 0)
		return;
	topMessage = message;
	topMessageUntil = gamestate.TimeCount + static_cast<int32_t>(duration);
}

void WolfStatusBar::SetC7HealthChamberPower(unsigned int power, unsigned int duration)
{
	if(!corridor7)
		return;
	c7ChamberPower = MIN(power, 100U);
	c7ChamberPowerUntil = gamestate.TimeCount + static_cast<int32_t>(duration);
}

//===========================================================================

void WolfStatusBar::SetupStatusbar()
{
	// Temporary configuration lump so that some mods can be ported to ECWolf
	// before a proper solution is created.
	// ---> WILL BE REMOVED <---

	int lastLump = 0;
	int lumpnum = 0;
	while((lumpnum = Wads.FindLump("LATCHCFG", &lastLump)) != -1)
	{
		Scanner sc(lumpnum);
		sc.ScriptMessage(Scanner::WARNING, "Utilizing temporary status bar configuration script.");

		while(sc.TokensLeft())
		{
			sc.MustGetToken(TK_Identifier);
			FString key = sc->str;
			key.ToLower();
			sc.MustGetToken('=');
			sc.MustGetToken(TK_IntConst);
			unsigned int value = sc->number;

			LatchConfig *var = NULL;
			FString extrakey;
			if(key.IndexOf("ammo") == 0)
			{
				extrakey = key.Mid(4);
				var = &StatusBarConfig.Ammo;
			}
			else if(key.IndexOf("floor") == 0)
			{
				extrakey = key.Mid(5);
				var = &StatusBarConfig.Floor;
			}
			else if(key.IndexOf("health") == 0)
			{
				extrakey = key.Mid(6);
				var = &StatusBarConfig.Health;
			}
			else if(key.IndexOf("items") == 0)
			{
				extrakey = key.Mid(5);
				var = &StatusBarConfig.Items;
			}
			else if(key.IndexOf("keys") == 0)
			{
				extrakey = key.Mid(4);
				var = &StatusBarConfig.Keys;
			}
			else if(key.IndexOf("lives") == 0)
			{
				extrakey = key.Mid(5);
				var = &StatusBarConfig.Lives;
			}
			else if(key.IndexOf("mugshot") == 0)
			{
				extrakey = key.Mid(7);
				var = &StatusBarConfig.Mugshot;
			}
			else if(key.IndexOf("score") == 0)
			{
				extrakey = key.Mid(5);
				var = &StatusBarConfig.Score;
			}
			else if(key.IndexOf("weapon") == 0)
			{
				extrakey = key.Mid(6);
				var = &StatusBarConfig.Weapon;
			}
			else
				sc.ScriptMessage(Scanner::ERROR, "Unknown key '%s'.\n", key.GetChars());

			if(extrakey.Compare("enabled") == 0)
				var->Enabled = value;
			else if(extrakey.Compare("digits") == 0)
				var->Digits = value;
			else if(extrakey.Compare("x") == 0)
				var->X = value;
			else if(extrakey.Compare("y") == 0)
				var->Y = value;
			else
				sc.ScriptMessage(Scanner::ERROR, "Unknown key '%s'.\n", key.GetChars());
		}
	}
}
