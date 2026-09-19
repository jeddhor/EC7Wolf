/*
** g_items.h
**
** Where the pickups are, and whether a bot has any business believing one is
** still there.
**
** Section 12.8 draws a line this file exists to keep. Where an item *spawns*
** is map knowledge: a player who has played an arena twice knows the shotgun
** is in the north corridor, and a bot knowing the same thing is not cheating.
** Whether the shotgun is there *now* is a different fact entirely, and the only
** honest sources for it are having just looked, or having looked recently and
** having no reason to think otherwise.
**
** So an annotation is not availability. The annotations are built once at map
** load from the map's own placement; belief is per bot, and moves only when
** that bot sees something.
**
** The failure this prevents is quiet: a bot that walked the global actor list
** would collect every item the moment it respawned, from anywhere on the map,
** and would simply look like a bot that plays the item timings well.
*/

#ifndef __G_ITEMS_H__
#define __G_ITEMS_H__

#include <stdint.h>

#include "wl_def.h"
#include "tarray.h"
#include "name.h"
#include "g_session.h"

namespace Items {

// What an item is for. Kept coarse: the need model asks "am I short of
// health" rather than "am I short of a C7MedKit", and the categories are the
// axes a player actually thinks along.
enum class Category : uint8_t
{
	Weapon,
	Ammo,
	Energy,
	Health,
	Armor,
	Invulnerability,
	Mine,
	VisorCharge,
	Other
};

const char *CategoryName(Category category);

// A place the map puts something, and what it puts there.
struct Annotation
{
	uint16_t tileX = 0;
	uint16_t tileY = 0;
	FName    cls = NAME_None;
	Category category = Category::Other;
	// A wall dispenser rather than something lying on the floor. Used by
	// standing next to it and pressing use, not by walking over it, so a bot
	// heading for one wants an adjacent cell and not the tile itself.
	bool     dispenser = false;
};

// What one bot currently thinks about one annotation.
enum class Belief : uint8_t
{
	// Never looked, or looked so long ago that the answer is worthless. Not
	// the same as Gone -- section 13.6 is explicit that a decayed record
	// becomes "unknown" rather than "absent", because a bot that treats
	// forgotten as empty stops going to look.
	Unknown,
	Present,
	Gone
};

struct Knowledge
{
	Belief   belief = Belief::Unknown;
	// When the belief was last supported by actually seeing the place.
	uint32_t at = 0;
};

// Build the annotations from the map as loaded. Called once a level is up.
void Annotate();
void Reset();

unsigned int Count();
const Annotation &At(unsigned int index);

// What this bot believes, and telling it what it just saw. `present` is the
// answer to "is there one there", asked only of a place the bot can currently
// see -- never of a place it cannot.
const Knowledge *KnownTo(Session::PlayerSlot slot, unsigned int index);
void Observe(Session::PlayerSlot slot, unsigned int index, bool present,
	uint32_t sequence);

// A belief this old stops being a belief. Ten seconds: long enough to walk
// across an arena on the strength of having seen something, short enough that
// a bot is not still sure about a pickup from a minute ago.
enum { STALE_TICS = 700 };

// Ages every bot's beliefs, turning the old ones back into Unknown.
void Age(uint32_t sequence);

// How badly this bot wants something of this category, right now, on a scale
// where 0 is "no use to me" and 1000 is "drop everything".
//
// Section 14.2's need term. Three shapes matter and each is a real claim about
// how the game plays:
//
//   * health rises nonlinearly as health falls. The difference between 100 and
//     80 is not worth crossing a map for; the difference between 20 and 40 is
//     the difference between winning the next fight and not;
//   * ammunition is nearly worthless at capacity, and worthless for a weapon
//     that is not owned -- picking up shells for a shotgun you do not have is
//     a trip for nothing; and
//   * a weapon already held is worth nothing under stay-in-world rules,
//     because it stays in the world and picking it up changes nothing.
//
// Reads the bot's own inventory, which section 11.4 permits: a player knows
// what they are carrying.
int Need(Session::PlayerSlot slot, Category category);

// And for a weapon specifically, which needs to know which weapon: one already
// carried is worth nothing, because under stay-in-world rules it stays in the
// world and picking it up again changes nothing.
int NeedWeapon(Session::PlayerSlot slot, FName cls);

// Why a candidate was not chosen. Section 14.2 asks every selected goal to
// show candidate scores *and* rejection reasons, and the milestone's exit
// criterion is "for explainable reasons" -- so this is part of the deliverable
// rather than a debugging convenience.
enum class Reject : uint8_t
{
	None,
	NotPresent,		// belief says gone, or was never anything
	Stale,			// belief too old to act on
	AlreadyHave,	// a weapon under stay-in-world rules
	NoNeed,			// full up, or it feeds a weapon this bot lacks
	Unreachable,	// no route
	TooFar,			// route cost exceeds what the need justifies
	LostToBetter	// scored, and something else scored higher
};

const char *RejectName(Reject why);

// One evaluated candidate.
struct Candidate
{
	unsigned int index = 0;
	int      need = 0;
	int      routeCost = 0;
	int      utility = 0;
	Reject   why = Reject::None;
};

// Somebody picked something up. Called from the pickup path, because that is
// the event; the alternative -- counting what a bot is holding when the match
// ends -- stops meaning anything the moment bots start dying, since death
// returns a player to its starting inventory. That check passed until combat
// arrived and then reported a bot which had collected two weapons and been
// killed as having collected nothing.
void NotePickup(const AActor *taker);

// How many things this slot has picked up during the match, ever, whatever
// happened to them afterwards.
unsigned int PickupsBy(Session::PlayerSlot slot);

// How many weapons this slot is carrying.
//
// The measurable outcome of a weapon goal, and the only one there is: under
// multiplayer stay-in-world rules the pickup does not vanish when collected,
// so the world looks identical afterwards and a belief of "present" stays
// correct. What changes is whose backpack it is in.
unsigned int WeaponsHeld(Session::PlayerSlot slot);

// Diagnostics: how many beliefs each bot holds, by kind.
void Tally(Session::PlayerSlot slot, unsigned int &present, unsigned int &gone,
	unsigned int &unknown);

int SelfTest();

}

#endif
