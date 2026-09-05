/*
** g_perception.h
**
** What a bot is allowed to know, and how it comes to know it.
**
** Section 13 of docs/multiplayer-bots-and-server.md. Everything a brain
** decides on passes through here, and the point of that is not tidiness: it is
** that a bot which reads the world directly is a bot that cheats, quietly,
** in ways no behavioural test will catch. A brain holding an AActor* can see
** through walls without anybody writing a line of code that means to.
**
** So an observation is values and stable ids, taken once, with no pointer into
** anything that can move. A brain reads its own observation and cannot reach
** past it.
**
** Three rules the plan states and this file exists to keep:
**
**   * never renderer state, and never ConsolePlayer's camera. Rendering may
**     not run at all on a server, and when it does it describes one screen,
**     not what eight bots can see. Anything derived from it makes a bot's
**     knowledge depend on which window happens to be open;
**   * all bots sense the same completed world, before any of this tic's
**     commands are applied, so no bot gets to react to another's move within
**     the tic that made it; and
**   * candidate slots are visited in ascending order, so ties break the same
**     way on two machines.
*/

#ifndef __G_PERCEPTION_H__
#define __G_PERCEPTION_H__

#include <stdint.h>

#include "wl_def.h"
#include "tarray.h"
#include "g_session.h"

class AActor;

namespace Perception {

// What the observing bot knows about itself. Its own body is the one thing it
// may read exactly: a player knows where they are standing and how hurt they
// are without needing a sensor for it.
struct OwnState
{
	fixed    x = 0;
	fixed    y = 0;
	angle_t  angle = 0;
	int      health = 0;
	uint16_t tileX = 0;
	uint16_t tileY = 0;
	bool     alive = false;
};

// One player seen this update. Position is where the target was when it was
// seen, which is the only position an observer can honestly hold.
struct PlayerSighting
{
	Session::PlayerSlot slot = 0;
	fixed    x = 0;
	fixed    y = 0;
	// In whole tiles, not map units and not fixed point. Named for it because
	// a distance typed `fixed` in a codebase where a tile is 1<<16 invites
	// exactly one mistake, and it was made within the hour: the first trace
	// shifted this as though it were map units and reported every contact at
	// range zero.
	int32_t  distanceTiles = 0;
	// From the observer, in the engine's angle space.
	angle_t  bearing = 0;
	// How far off the observer's own facing, folded to 0..180 degrees. Kept
	// because "in front of me" and "at my shoulder" are different facts and
	// the difference is what the FOV test turned on.
	angle_t  offAxis = 0;
	uint32_t seenAt = 0;
};

// What kind of thing made a noise. Semantic, and emitted where the gameplay
// action happens -- never by asking the audio mixer, which a dedicated server
// does not have and which knows about samples rather than events.
enum class SoundKind : uint8_t
{
	Weapon,
	Door,
	Pain,
	Death,
	NUM
};

const char *SoundName(SoundKind kind);

// One noise, as the listening bot received it.
//
// Deliberately not a coordinate. Section 13.4: the released observation gives
// an approximate bearing or region and never an exact unseen position -- a
// player hears a shot somewhere off to the left, and does not learn the
// shooter's map reference. The bearing is quantised to a sector and the range
// to a band for exactly that reason.
struct AudibleEvent
{
	SoundKind kind = SoundKind::Weapon;
	// Centre of the 45-degree sector the sound came from.
	angle_t  bearing = 0;
	// Banded: 0 is close, then further out. Not a measurement.
	int32_t  band = 0;
	// Only when the listener can already see who made it. Hearing a gun does
	// not tell you whose it is.
	int16_t  sourceSlot = -1;
	uint32_t heardAt = 0;
};

// A laser barrier this bot knows about.
//
// Corridor 7's barriers (map statics 28 and 84) are invisible without the
// infrared visor, and that is the whole of their design: walking into an
// unlit corridor and losing ten points is the intended experience. So a bot
// must not learn where they are by scanning actors, which is the one way it
// could trivially cheat here and the one that would never show up as odd
// behaviour -- it would just stop walking into them.
//
// Two honest ways to know: see it with infrared on, or walk into it.
struct HazardKnowledge
{
	uint16_t tileX = 0;
	uint16_t tileY = 0;
	// Seen with the visor, or discovered the hard way.
	bool     byContact = false;
	// When it was last confirmed. Memory ages from here; losing infrared does
	// not erase what was already learned.
	uint32_t knownAt = 0;
};

// Everything one bot perceived on one update.
struct Observation
{
	uint32_t sequence = 0;
	bool     valid = false;
	OwnState self;
	TArray<PlayerSighting> players;
	TArray<AudibleEvent> sounds;
	// Barriers currently visible to this bot. Empty without infrared, always,
	// however many are in front of it.
	TArray<HazardKnowledge> hazards;

	const PlayerSighting *Seen(Session::PlayerSlot slot) const;
};

// Half the horizontal field of view, each side of centre.
//
// The renderer shows 90 degrees across, so a bot that reacts to anything
// within 45 degrees of its facing reacts to what a player at the same spot
// could see. Wider would be a bot noticing things off the edge of the screen.
//
// Written as ANGLE_45 and not as 45*ANGLE_1: ANGLE_1 is a truncated division,
// so forty-five of them fall 32 units short of a true 45 degrees and something
// exactly on the edge of the view tests as outside it. A rounding artifact
// rather than a bug, but the edge of a bot's vision is not a good place to
// keep one.
#define FOV_HALF ((angle_t)ANGLE_45)

// Something happened that a person in the room would hear. Called from the
// gameplay action point, not from the sound code: the two coincide today and
// there is no reason they must, and a server plays nothing at all.
//
// Loudness is in tiles and is a radius, before zones and doors are considered.
void Emit(SoundKind kind, const AActor *source, int loudnessTiles);

// A player just walked into a laser barrier. Called from the damage path,
// because that is the moment the fact becomes known to whoever it happened
// to -- and to nobody else.
void NoteHazardContact(const AActor *victim);

// What this bot has learned about barriers, however it learned it. Persists
// across the visor being switched off; ages, but is not erased.
const TArray<HazardKnowledge> *HazardsKnownTo(Session::PlayerSlot slot);

// Build every active bot's observation for this tic, from the world as it
// stands before any of this tic's commands are applied. Cheap enough to do for
// all of them at once, and doing it at one point is what makes "the same
// completed world" true rather than aspirational.
void BeginFrame(uint32_t sequence);

// This slot's observation, or NULL if it has none this tic.
const Observation *For(Session::PlayerSlot slot);

// Drop everything. Called when a level ends or the bots are torn down.
void Reset();

// Was the last frame's work done? Diagnostics only.
unsigned int Observers();

// Open a trace of what every bot perceived, one line per sighting, for the
// gates that check nothing is perceived that should not be.
bool OpenTrace(const char *path);
void CloseTrace();

// Self-test: the geometry helpers, without a map or a window.
int SelfTest();

}

#endif
