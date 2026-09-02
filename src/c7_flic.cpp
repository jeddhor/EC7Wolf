// ===========================================================================
//
// c7_flic.cpp - Corridor 7 CD cinematics.
//
// See c7_flic.h and docs/corridor7-video.md.
//
// FLIC is a delta format: after the first frame every frame is a patch on the
// one before, so the decode buffer has to persist across frames and playback
// cannot be started from the middle. That is the only thing about it that is
// not obvious; the rest is a handful of run-length encodings.
//
// ===========================================================================

#include <string.h>

#include "wl_def.h"
#include "c7_flic.h"
#include "files.h"
#include "id_in.h"
#include "id_sd.h"
#include "id_vh.h"
#include "id_vl.h"
#include "v_video.h"
#include "v_palette.h"
#include "textures/textures.h"
#include "wl_iwad.h"
#include "w_wad.h"
#include "filesys.h"
#include "wl_main.h"
#include "tarray.h"

namespace
{
	const unsigned int FLIC_WIDTH  = 320;
	const unsigned int FLIC_HEIGHT = 200;
	const unsigned int FLIC_PIXELS = FLIC_WIDTH * FLIC_HEIGHT;

	// Chunk types. Everything else is skipped by its own size rather than
	// treated as an error: FLIC files legitimately carry chunks a player does
	// not need (a postage-stamp preview, for one), and refusing to play an
	// animation because it contains a thumbnail would be absurd.
	enum
	{
		FLI_COLOR256 = 4,
		FLI_SS2      = 7,
		FLI_COLOR64  = 11,
		FLI_LC       = 12,
		FLI_BLACK    = 13,
		FLI_BRUN     = 15,
		FLI_COPY     = 16,
		FLI_PSTAMP   = 18
	};

	const unsigned short FLI_MAGIC       = 0xAF11;
	const unsigned short FLC_MAGIC       = 0xAF12;
	const unsigned short FRAME_MAGIC     = 0xF1FA;
	const unsigned short PREFIX_MAGIC    = 0xF100;

	FString gVideoDir;

	// --- the sound script ---------------------------------------------------
	//
	// The animations carry no audio: FLIC has no such chunk, and none of the
	// disc's audio tracks is the length of a cinematic. The executable plays
	// digitized sounds from AUDIOMUS at fixed FRAME NUMBERS instead, out of a
	// switch that compares the running frame counter -- "CMP AX, 60 / JZ / PUSH
	// 46 / CALL far" and so on, at file offset 0x026FDB onwards.
	//
	// Established twice over, which is the only reason these numbers are here
	// rather than guessed: read out of that switch, and independently captured
	// by running the released game under an instrumented DOSBox-X that logs
	// Sound Blaster DMA payloads, then matching each payload against AUDIOMUS.
	// The two agree to within 0.17 s across the whole opening.
	//
	// The logo's audio is assembled from ordinary in-game effects -- the
	// apparition shriek, a morph, a door, a teleport -- which is why a player
	// recognizes the first one. Only the four speech samples are unique to the
	// cinematics, and they are the only digitized sounds in the game that
	// nothing else ever plays.
	struct SoundCue
	{
		unsigned int frame;
		const char  *sound;
	};

	const SoundCue kSeqOne[] =
	{
		{   1, "c7/apparition"            },
		{  36, "c7/monster/morph/class8"  },
		{  55, "doors/open"               },
		{  60, "c7/teleport"              },
		{   0, NULL }
	};

	const SoundCue kSeqThree[] =
	{
		{   1, "c7/cinematic/line1" },
		{ 120, "c7/cinematic/line2" },
		{ 340, "c7/cinematic/line3" },
		{ 500, "c7/cinematic/line4" },
		{   0, NULL }
	};

	// SEQFOUR's script is dispatched by a binary search over the frame counter
	// plus a jump table rather than the flat compare chain the other two use,
	// and it has not been read out reliably yet. The sounds it reaches are
	// visible in the same code region (50, 78, 62, 12, 34, 25 and 93 among
	// them); the frames they belong to are not. Better silent than wrong.
	const SoundCue *CuesFor(const char *name)
	{
		if(stricmp(name, "SEQONE") == 0)
			return kSeqOne;
		if(stricmp(name, "SEQTHREE") == 0)
			return kSeqThree;
		return NULL;
	}

	inline unsigned short GetU16(const BYTE *p) { return (unsigned short)(p[0] | (p[1] << 8)); }
	inline unsigned int   GetU32(const BYTE *p)
	{
		return (unsigned int)p[0] | ((unsigned int)p[1] << 8) |
			((unsigned int)p[2] << 16) | ((unsigned int)p[3] << 24);
	}

	// A whole animation, held in memory. The largest of the three is 21 MB,
	// which is nothing now and means the decoder never has to cope with a short
	// read part way through a chunk.
	struct Flic
	{
		TArray<BYTE> data;
		unsigned int frames;
		unsigned int speedMs;
		unsigned int firstFrameOffset;
	};

	// Where a cinematic may live, in the order it is looked for.
	//
	// A LOADED RESOURCE FIRST. The CD's three animations sit in a directory
	// beside the game data because that is where the disc leaves them, and
	// until now that was the only place this looked -- so a campaign could not
	// carry one at all, however it was packaged. A pack's `video/NAME.CO7` is
	// tried before the directory, which means a resource pack can supply its
	// own ending and cannot accidentally shadow the game's unless it names it
	// the same thing on purpose.
	int FindFlicLump(const char *name)
	{
		if(name == NULL || *name == '\0')
			return -1;
		FString full;
		full.Format("video/%s.CO7", name);
		int lump = Wads.CheckNumForFullName(full);
		if(lump == -1)
		{
			full.Format("video/%s.co7", name);
			lump = Wads.CheckNumForFullName(full);
		}
		return lump;
	}

	bool LoadFlicData(Flic &out);

	bool LoadFlicLump(int lump, Flic &out)
	{
		if(lump == -1)
			return false;
		const int length = Wads.LumpLength(lump);
		if(length < 128)
			return false;
		out.data.Resize((unsigned int)length);
		FWadLump reader = Wads.OpenLumpNum(lump);
		if(reader.Read(&out.data[0], length) != length)
			return false;
		return LoadFlicData(out);
	}

	bool LoadFlic(const char *path, Flic &out)
	{
		FileReader reader;
		if(!reader.Open(path))
			return false;
		const long length = reader.GetLength();
		if(length < 128)
			return false;

		out.data.Resize((unsigned int)length);
		if(reader.Read(&out.data[0], length) != length)
			return false;
		return LoadFlicData(out);
	}

	// Everything after the bytes are in hand, shared by both routes so a
	// cinematic from a pack is validated exactly as one from the disc is.
	bool LoadFlicData(Flic &out)
	{
		const unsigned int length = out.data.Size();

		const BYTE *h = &out.data[0];
		const unsigned int size   = GetU32(h);
		const unsigned short magic = GetU16(h + 4);
		const unsigned short w     = GetU16(h + 8);
		const unsigned short hgt   = GetU16(h + 10);
		const unsigned short depth = GetU16(h + 12);

		if(magic != FLC_MAGIC && magic != FLI_MAGIC)
			return false;
		if(size != (unsigned int)length)
			return false;
		if(w != FLIC_WIDTH || hgt != FLIC_HEIGHT || depth != 8)
			return false;

		out.frames = GetU16(h + 6);
		// FLC keeps a millisecond speed at offset 16; FLI keeps 1/70 s jiffies.
		out.speedMs = magic == FLC_MAGIC
			? GetU32(h + 16)
			: (GetU32(h + 16) * 1000u) / 70u;
		if(out.speedMs == 0)
			out.speedMs = 71;
		out.firstFrameOffset = 128;
		return out.frames != 0;
	}

	// --- chunk decoders ----------------------------------------------------

	void DecodeColor(const BYTE *p, unsigned int len, PalEntry *pal, bool sixBit)
	{
		if(len < 2)
			return;
		unsigned int packets = GetU16(p);
		unsigned int at = 2;
		unsigned int index = 0;
		while(packets-- > 0 && at + 2 <= len)
		{
			index += p[at++];
			unsigned int count = p[at++];
			if(count == 0)
				count = 256;
			for(unsigned int i = 0; i < count && index < 256 && at + 3 <= len + 1; ++i, ++index)
			{
				if(at + 3 > len)
					return;
				BYTE r = p[at], g = p[at+1], b = p[at+2];
				at += 3;
				// A COLOR64 chunk is 0..63 per channel, the VGA DAC's own range;
				// COLOR256 is already 0..255.
				if(sixBit)
				{
					r = (BYTE)((r << 2) | (r >> 4));
					g = (BYTE)((g << 2) | (g >> 4));
					b = (BYTE)((b << 2) | (b >> 4));
				}
				pal[index] = PalEntry(r, g, b);
			}
		}
	}

	void DecodeBrun(const BYTE *p, unsigned int len, BYTE *pixels)
	{
		unsigned int at = 0;
		for(unsigned int y = 0; y < FLIC_HEIGHT; ++y)
		{
			if(at >= len)
				return;
			// The packet count byte is vestigial -- it cannot express more than
			// 255 packets and a 320-pixel line can need more -- so decode until
			// the line is full and ignore it, which is what every real player
			// does.
			++at;
			BYTE *row = pixels + y * FLIC_WIDTH;
			unsigned int x = 0;
			while(x < FLIC_WIDTH && at < len)
			{
				const signed char count = (signed char)p[at++];
				if(count >= 0)
				{
					if(at >= len) return;
					const BYTE value = p[at++];
					unsigned int run = (unsigned int)count;
					if(x + run > FLIC_WIDTH) run = FLIC_WIDTH - x;
					memset(row + x, value, run);
					x += run;
				}
				else
				{
					unsigned int run = (unsigned int)(-count);
					if(x + run > FLIC_WIDTH) run = FLIC_WIDTH - x;
					if(at + run > len) return;
					memcpy(row + x, p + at, run);
					at += run;
					x += run;
				}
			}
		}
	}

	// FLI_LC: a run of changed lines, each a set of skip/replace packets.
	void DecodeLc(const BYTE *p, unsigned int len, BYTE *pixels)
	{
		if(len < 4)
			return;
		unsigned int y = GetU16(p);
		unsigned int lines = GetU16(p + 2);
		unsigned int at = 4;

		while(lines-- > 0 && y < FLIC_HEIGHT && at < len)
		{
			unsigned int packets = p[at++];
			BYTE *row = pixels + y * FLIC_WIDTH;
			unsigned int x = 0;
			while(packets-- > 0 && at + 2 <= len)
			{
				x += p[at++];
				const signed char count = (signed char)p[at++];
				if(count >= 0)
				{
					unsigned int run = (unsigned int)count;
					if(x >= FLIC_WIDTH) break;
					if(x + run > FLIC_WIDTH) run = FLIC_WIDTH - x;
					if(at + run > len) return;
					memcpy(row + x, p + at, run);
					at += run;
					x += run;
				}
				else
				{
					if(at >= len) return;
					const BYTE value = p[at++];
					unsigned int run = (unsigned int)(-count);
					if(x >= FLIC_WIDTH) break;
					if(x + run > FLIC_WIDTH) run = FLIC_WIDTH - x;
					memset(row + x, value, run);
					x += run;
				}
			}
			++y;
		}
	}

	// FLI_SS2: FLC's word-oriented delta. Lines are addressed by a signed skip
	// count, and the top two bits of the opcode select between skipping lines,
	// setting the row's last byte, and a packet count.
	void DecodeSs2(const BYTE *p, unsigned int len, BYTE *pixels)
	{
		if(len < 2)
			return;
		unsigned int lines = GetU16(p);
		unsigned int at = 2;
		unsigned int y = 0;

		while(lines > 0 && at + 2 <= len)
		{
			const short opcode = (short)GetU16(p + at);
			at += 2;

			if((opcode & 0xC000) == 0x0000)
			{
				// Packet count for this line.
				unsigned int packets = (unsigned int)opcode;
				if(y >= FLIC_HEIGHT)
					return;
				BYTE *row = pixels + y * FLIC_WIDTH;
				unsigned int x = 0;
				while(packets-- > 0 && at + 2 <= len)
				{
					x += p[at++];
					const signed char count = (signed char)p[at++];
					if(count >= 0)
					{
						unsigned int run = (unsigned int)count * 2;
						if(x >= FLIC_WIDTH) break;
						if(x + run > FLIC_WIDTH) run = FLIC_WIDTH - x;
						if(at + run > len) return;
						memcpy(row + x, p + at, run);
						at += run;
						x += run;
					}
					else
					{
						if(at + 2 > len) return;
						const BYTE a = p[at], b = p[at+1];
						at += 2;
						unsigned int run = (unsigned int)(-count);
						for(unsigned int i = 0; i < run && x + 1 < FLIC_WIDTH; ++i, x += 2)
						{
							row[x] = a;
							row[x+1] = b;
						}
					}
				}
				++y;
				--lines;
			}
			else if((opcode & 0xC000) == 0xC000)
			{
				// Negative line skip.
				y += (unsigned int)(-(int)opcode);
			}
			else if((opcode & 0xC000) == 0x8000)
			{
				// The row's last byte, for an odd-width image. These are 320
				// wide, so this cannot occur -- but a player that ignores it
				// would desynchronise rather than fail, so it is handled.
				if(y < FLIC_HEIGHT)
					pixels[y * FLIC_WIDTH + FLIC_WIDTH - 1] = (BYTE)(opcode & 0xFF);
			}
		}
	}

	// One FRAME chunk applied to the running image and palette. Shared by the
	// player and by --flictest so the thing the gate exercises is the thing the
	// game runs, not a second copy of it.
	void DecodeFrame(const BYTE *chunk, unsigned int chunkSize,
		BYTE *pixels, PalEntry *pal)
	{
		unsigned int subChunks = GetU16(chunk + 6);
		unsigned int sub = 16;
		while(subChunks-- > 0 && sub + 6 <= chunkSize)
		{
			const unsigned int subSize = GetU32(chunk + sub);
			const unsigned short subType = GetU16(chunk + sub + 4);
			if(subSize < 6 || sub + subSize > chunkSize)
				break;
			const BYTE *payload = chunk + sub + 6;
			const unsigned int payloadLen = subSize - 6;

			switch(subType)
			{
				case FLI_COLOR256: DecodeColor(payload, payloadLen, pal, false); break;
				case FLI_COLOR64:  DecodeColor(payload, payloadLen, pal, true);  break;
				case FLI_BRUN:     DecodeBrun(payload, payloadLen, pixels);      break;
				case FLI_LC:       DecodeLc(payload, payloadLen, pixels);        break;
				case FLI_SS2:      DecodeSs2(payload, payloadLen, pixels);       break;
				case FLI_BLACK:    memset(pixels, 0, FLIC_PIXELS);               break;
				case FLI_COPY:
					if(payloadLen >= FLIC_PIXELS)
						memcpy(pixels, payload, FLIC_PIXELS);
					break;
				case FLI_PSTAMP:
				default:
					break;	// a preview thumbnail, or something we need not know
			}
			sub += subSize;
		}
	}

	// --- the frame the canvas draws ----------------------------------------
	//
	// The decoded frame is 8-bit indices at 320x200, and the game's canvas is
	// 8-bit indices; wrapping it in an FTexture lets DrawTexture do the
	// full-screen scaling that every other page in the game already goes
	// through, which is why this needs nothing from either renderer.
	class FFlicFrameTexture : public FTexture
	{
	public:
		FFlicFrameTexture()
		{
			Width = FLIC_WIDTH;
			Height = FLIC_HEIGHT;
			WidthBits = 9;   // 512 >= 320
			HeightBits = 8;  // 256 >= 200
			WidthMask = (1 << WidthBits) - 1;
			bMasked = false;
			xScale = yScale = FRACUNIT;
			Pixels.Resize(FLIC_PIXELS);
			memset(&Pixels[0], 0, FLIC_PIXELS);
			Spans[0].TopOffset = 0;
			Spans[0].Length = FLIC_HEIGHT;
			Spans[1].TopOffset = 0;
			Spans[1].Length = 0;
		}

		// FTexture is column-major; the decoder works in rows, so the transpose
		// happens once per frame here rather than inside every chunk decoder.
		void SetFrame(const BYTE *rows)
		{
			BYTE *dest = &Pixels[0];
			for(unsigned int x = 0; x < FLIC_WIDTH; ++x)
				for(unsigned int y = 0; y < FLIC_HEIGHT; ++y)
					*dest++ = rows[y * FLIC_WIDTH + x];
		}

		const BYTE *GetColumn(unsigned int column, const Span **spans_out)
		{
			if(column >= FLIC_WIDTH)
				column %= FLIC_WIDTH;
			if(spans_out != NULL)
				*spans_out = Spans;
			return &Pixels[column * FLIC_HEIGHT];
		}

		const BYTE *GetPixels() { return &Pixels[0]; }
		void Unload() {}

	private:
		TArray<BYTE> Pixels;
		Span Spans[2];
	};
}

// ---------------------------------------------------------------------------

void C7Flic_Init()
{
	if(!IWad::CheckGameFilter("Corridor7"))
		return;

	const FString dirName = IWad::GetGameDataDirectory() + "video";
	unsigned int found = 0;
	static const char *const names[] = { "SEQONE", "SEQTHREE", "SEQFOUR" };
	for(unsigned int i = 0; i < 3; ++i)
	{
		FString path;
		path.Format("%s" PATH_SEPARATOR "%s.CO7", dirName.GetChars(), names[i]);
		FileReader probe;
		if(probe.Open(path))
			++found;
	}

	if(found == 0)
	{
		Printf("Cinematics: no %s directory; the CD animations will be skipped.\n",
			dirName.GetChars());
		return;
	}

	gVideoDir = dirName;
	Printf("Cinematics: %u of 3 CD animations found in %s.\n", found, dirName.GetChars());
}

bool C7Flic_Have(const char *name)
{
	if(name == NULL)
		return false;
	if(FindFlicLump(name) != -1)
		return true;
	if(gVideoDir.IsEmpty())
		return false;
	FString path;
	path.Format("%s" PATH_SEPARATOR "%s.CO7", gVideoDir.GetChars(), name);
	FileReader probe;
	return probe.Open(path);
}

bool C7Flic_Play(const char *name)
{
	if(name == NULL || screen == NULL)
		return false;

	// A loaded resource first, then the disc's own directory. A campaign that
	// ships its own ending is the whole point of looking in a lump at all.
	Flic flic;
	const char *from = "a loaded resource";
	if(!LoadFlicLump(FindFlicLump(name), flic))
	{
		if(gVideoDir.IsEmpty())
			return false;
		FString path;
		path.Format("%s" PATH_SEPARATOR "%s.CO7", gVideoDir.GetChars(), name);
		if(!LoadFlic(path, flic))
			return false;
		from = gVideoDir.GetChars();
	}

	// Said out loud, because "which animation played, and where did it come
	// from" is otherwise unanswerable: the thing on screen is a picture, and
	// a campaign's own ending and the game's look equally plausible.
	Printf("Cinematic: playing %s from %s, %u frames at %u ms.\n",
		name, from, flic.frames, flic.speedMs);

	TArray<BYTE> pixels(FLIC_PIXELS);
	pixels.Resize(FLIC_PIXELS);
	memset(&pixels[0], 0, FLIC_PIXELS);

	// The animation owns the palette while it plays; the caller's is put back
	// afterward so whatever was on screen before still looks like itself.
	PalEntry saved[256];
	memcpy(saved, screen->GetPalette(), sizeof(saved));
	PalEntry pal[256];
	memcpy(pal, saved, sizeof(pal));

	FFlicFrameTexture frame;

	// PG13() and the attract loop's faders leave the screen blended to black,
	// and everything presented while that is true is invisible -- which is
	// exactly what happened when these moved into the attract cycle: the
	// animations ran, correctly, onto a black screen. The screen is already
	// black here, so fading in costs nothing to look at and leaves the blend
	// cleared; the matching fade-out at the end hands the caller back the state
	// it had, because the next thing the loop does is fade the title page in.
	const bool wasFaded = screenfaded;
	if(wasFaded)
	{
		screen->Lock(false);
		screen->Clear(0, 0, SCREENWIDTH, SCREENHEIGHT, GPalette.BlackIndex, 0);
		screen->Unlock();
		VW_FadeIn();
	}

	IN_ClearKeysDown();

	const SoundCue *cues = CuesFor(name);

	const BYTE *const base = &flic.data[0];
	const unsigned int total = flic.data.Size();
	unsigned int at = flic.firstFrameOffset;

	// Paced against the real clock rather than by sleeping a fixed amount per
	// frame, so a machine that cannot keep up drops behind and finishes on time
	// instead of playing the whole thing in slow motion.
	const unsigned int startTime = SDL_GetTicks();
	unsigned int frameIndex = 0;
	bool skipped = false;

	while(at + 16 <= total && frameIndex < flic.frames && !skipped)
	{
		const unsigned int chunkSize = GetU32(base + at);
		const unsigned short chunkMagic = GetU16(base + at + 4);
		if(chunkSize < 16 || at + chunkSize > total)
			break;

		if(chunkMagic == FRAME_MAGIC)
		{
			DecodeFrame(base + at, chunkSize, &pixels[0], pal);

			// A frame chunk with no sub-chunks is a held frame: show the
			// previous image again for its own duration.
			frame.SetFrame(&pixels[0]);
			memcpy(screen->GetPalette(), pal, sizeof(pal));
			screen->UpdatePalette();

			screen->Lock(false);
			screen->Clear(0, 0, SCREENWIDTH, SCREENHEIGHT, GPalette.BlackIndex, 0);
			screen->DrawTexture(&frame, 0, 0,
				DTA_DestWidth, SCREENWIDTH,
				DTA_DestHeight, SCREENHEIGHT,
				TAG_DONE);
			screen->Unlock();
			VH_UpdateScreen();

			++frameIndex;

			// Frame numbers in the script are 1-based, counting the frames the
			// animation actually shows.
			while(cues != NULL && cues->sound != NULL && cues->frame <= frameIndex)
			{
				SD_PlaySound(cues->sound);
				++cues;
			}

			const unsigned int due = startTime + frameIndex * flic.speedMs;
			for(;;)
			{
				IN_ProcessEvents();
				if(IN_CheckAck())
				{
					skipped = true;
					break;
				}
				const unsigned int now = SDL_GetTicks();
				if(now >= due)
					break;
				SDL_Delay(due - now > 5 ? 5 : 1);
			}
		}
		else if(chunkMagic != PREFIX_MAGIC)
		{
			// Not a frame and not the prefix chunk: the file is not shaped the
			// way we think, so stop rather than walk off into it.
			break;
		}

		at += chunkSize;
	}

	// Leave on a black screen, and get there BEFORE handing the palette back.
	//
	// The animation's last image is still in the framebuffer at this point, and
	// it is 256 indices that mean something only under the animation's own
	// palette. Restoring the game's palette first showed that image through the
	// wrong colors for exactly one present -- a single psychedelic flash at the
	// end of every cinematic. Fading out first drives the screen to black while
	// the palette still matches its pixels, and the swap afterward lands on
	// black, where it cannot be seen.
	VW_FadeOut();
	screen->Lock(false);
	screen->Clear(0, 0, SCREENWIDTH, SCREENHEIGHT, GPalette.BlackIndex, 0);
	screen->Unlock();

	memcpy(screen->GetPalette(), saved, sizeof(saved));
	screen->UpdatePalette();

	// A caller that handed us a lit screen gets one back. The framebuffer is
	// black and the palette is theirs again, so this fades up on nothing rather
	// than on a stale frame.
	if(!wasFaded)
		VW_FadeIn();

	// A skip means "move on", so the cue that was mid-sentence stops with the
	// picture. An animation that ran to its end keeps its tail: the last line of
	// dialogue is 10.2 s and starts 7.5 s before the last frame, so the released
	// game lets it finish over whatever comes next, and cutting it would be a
	// deviation rather than a fix.
	if(skipped)
		SD_StopDigitized();

	IN_ClearKeysDown();

	return true;
}

// ---------------------------------------------------------------------------
// --flictest: decode an animation and report, without a game or a window.
//
// The engine cannot start without the commercial data, so nothing that drives
// it can run on a hosted CI runner. This can: it needs a file and nothing else,
// which makes the decoder the one part of the cinematics that is gated
// everywhere rather than only on a machine that owns a Corridor 7 disc.
// ---------------------------------------------------------------------------

int C7Flic_SelfTest(const char *path)
{
	Flic flic;
	if(!LoadFlic(path, flic))
	{
		printf("FLIC: %s is not a playable animation.\n", path);
		return 1;
	}

	printf("FLIC: %s, %u frames, %u ms/frame\n", path, flic.frames, flic.speedMs);

	TArray<BYTE> pixels(FLIC_PIXELS);
	pixels.Resize(FLIC_PIXELS);
	memset(&pixels[0], 0, FLIC_PIXELS);
	PalEntry pal[256];
	memset(pal, 0, sizeof(pal));

	const BYTE *const base = &flic.data[0];
	const unsigned int total = flic.data.Size();
	unsigned int at = flic.firstFrameOffset;
	unsigned int decoded = 0;

	while(at + 16 <= total && decoded < flic.frames)
	{
		const unsigned int chunkSize = GetU32(base + at);
		const unsigned short chunkMagic = GetU16(base + at + 4);
		if(chunkSize < 16 || at + chunkSize > total)
			break;

		if(chunkMagic == FRAME_MAGIC)
		{
			DecodeFrame(base + at, chunkSize, &pixels[0], pal);
			++decoded;

			// A checksum of the image and of the palette, per frame. Enough for
			// a gate to pin exact output without shipping reference images.
			unsigned int image = 2166136261u;
			for(unsigned int i = 0; i < FLIC_PIXELS; ++i)
				image = (image ^ pixels[i]) * 16777619u;
			unsigned int palsum = 2166136261u;
			for(unsigned int i = 0; i < 256; ++i)
			{
				palsum = (palsum ^ pal[i].r) * 16777619u;
				palsum = (palsum ^ pal[i].g) * 16777619u;
				palsum = (palsum ^ pal[i].b) * 16777619u;
			}
			printf("frame %u image %08x palette %08x\n", decoded, image, palsum);
		}
		else if(chunkMagic != PREFIX_MAGIC)
			break;

		at += chunkSize;
	}

	if(decoded != flic.frames)
	{
		printf("FLIC: decoded %u of %u frames.\n", decoded, flic.frames);
		return 1;
	}
	printf("FLIC: decoded all %u frames.\n", decoded);
	return 0;
}
