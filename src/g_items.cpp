/*
** g_items.cpp
**
** See g_items.h.
*/

#include "g_items.h"
#include "actor.h"
#include "a_inventory.h"
#include "thingdef/thingdef.h"
#include "wl_def.h"
#include "wl_play.h"
#include "lnspec.h"
#include "id_ca.h"
#include "gamemap.h"
#include "wl_agent.h"

namespace Items {

namespace {

TArray<Annotation> g_annotations;
// Pickups actually made, per slot, for the whole match.
unsigned int       g_pickups[MAXPLAYERS] = { 0 };
// [slot][annotation]. A flat array per slot rather than a map: there are at
// most a couple of dozen pickups in a Corridor 7 arena.
TArray<Knowledge>  g_belief[MAXPLAYERS];

// Which axis of need a class answers to.
//
// Matched on the native inventory types where there is one, and on the class
// name where Corridor 7 says something the type system does not -- a charge
// pack and a mine pack are both Ammo to the engine and are not remotely the
// same decision.
Category Classify(AActor *thing)
{
	const FString name = thing->GetClass()->GetName().GetChars();

	if(name.IndexOf("Mine") >= 0)
		return Category::Mine;
	if(name.IndexOf("ChargePack") >= 0 || name.IndexOf("Visor") >= 0)
		return Category::VisorCharge;
	if(name.IndexOf("Invuln") >= 0)
		return Category::Invulnerability;
	if(name.IndexOf("Armor") >= 0)
		return Category::Armor;
	if(name.IndexOf("Energy") >= 0)
		return Category::Energy;

	if(thing->IsKindOf(NATIVE_CLASS(Weapon)))
		return Category::Weapon;
	if(thing->IsKindOf(NATIVE_CLASS(Ammo)))
		return Category::Ammo;
	if(thing->IsKindOf(NATIVE_CLASS(Health)))
		return Category::Health;

	return Category::Other;
}

}

const char *CategoryName(Category category)
{
	switch(category)
	{
		case Category::Weapon:          return "weapon";
		case Category::Ammo:            return "ammo";
		case Category::Energy:          return "energy";
		case Category::Health:          return "health";
		case Category::Armor:           return "armor";
		case Category::Invulnerability: return "invuln";
		case Category::Mine:            return "mine";
		case Category::VisorCharge:     return "visor";
		default:                        return "other";
	}
}

void Reset()
{
	for(unsigned int i = 0;i < MAXPLAYERS;++i)
		g_pickups[i] = 0;
	g_annotations.Clear();
	for(unsigned int i = 0;i < MAXPLAYERS;++i)
		g_belief[i].Clear();
}

void Annotate()
{
	Reset();

	for(AActor::Iterator iter = AActor::GetIterator();iter.Next();)
	{
		AActor *const thing = iter;
		if(!thing->IsKindOf(NATIVE_CLASS(Inventory)))
			continue;
		// Something already in a backpack is nobody's landmark.
		if(static_cast<AInventory *>(thing)->owner != NULL)
			continue;

		Annotation note;
		note.tileX = (uint16_t)thing->tilex;
		note.tileY = (uint16_t)thing->tiley;
		note.cls = thing->GetClass()->GetName();
		note.category = Classify(thing);
		g_annotations.Push(note);
	}

	// Wall dispensers, which are where health in these arenas actually comes
	// from. Not pickup actors: a C7_Dispenser trigger on a wall tile, used by
	// pressing use while facing it, with args[0] of 1 for health and 2 for
	// ammunition.
	//
	// Missing these is why B5 recorded "these arenas carry almost no health".
	// They carry plenty; it is on the walls.
	if(map != NULL)
	{
		for(unsigned int ty = 0;ty < map->GetHeader().height;++ty)
		{
			for(unsigned int tx = 0;tx < map->GetHeader().width;++tx)
			{
				MapSpot spot = map->GetSpot(tx, ty, 0);
				if(spot == NULL || spot->tile == NULL)
					continue;
				for(unsigned int t = 0;t < spot->triggers.Size();++t)
				{
					const MapTrigger &trig = spot->triggers[t];
					if(trig.action != Specials::C7_Dispenser || !trig.playerUse)
						continue;
					Annotation note;
					note.tileX = (uint16_t)tx;
					note.tileY = (uint16_t)ty;
					note.cls = NAME_None;
					note.category = trig.arg[0] == 1 ? Category::Health
						: Category::Ammo;
					note.dispenser = true;
					g_annotations.Push(note);
					break;
				}
			}
		}
	}

	for(unsigned int i = 0;i < MAXPLAYERS;++i)
	{
		g_belief[i].Resize(g_annotations.Size());
		for(unsigned int a = 0;a < g_annotations.Size();++a)
			g_belief[i][a] = Knowledge();
	}
}

unsigned int Count() { return g_annotations.Size(); }

const Annotation &At(unsigned int index) { return g_annotations[index]; }

const Knowledge *KnownTo(Session::PlayerSlot slot, unsigned int index)
{
	if(slot >= MAXPLAYERS || index >= g_belief[slot].Size())
		return NULL;
	return &g_belief[slot][index];
}

void Observe(Session::PlayerSlot slot, unsigned int index, bool present,
	uint32_t sequence)
{
	if(slot >= MAXPLAYERS || index >= g_belief[slot].Size())
		return;
	Knowledge &k = g_belief[slot][index];
	k.belief = present ? Belief::Present : Belief::Gone;
	k.at = sequence;
}

void Age(uint32_t sequence)
{
	for(unsigned int i = 0;i < MAXPLAYERS;++i)
	{
		for(unsigned int a = 0;a < g_belief[i].Size();++a)
		{
			Knowledge &k = g_belief[i][a];
			if(k.belief == Belief::Unknown)
				continue;
			if(sequence - k.at < (uint32_t)STALE_TICS)
				continue;
			// Back to Unknown, and specifically not to Gone. A bot that lets
			// old news decay into "there is nothing there" stops going to look
			// and never discovers otherwise.
			k.belief = Belief::Unknown;
		}
	}
}

namespace {

// How full a named ammo-like inventory is, 0..1000. -1 when the bot has none
// of that kind at all, which for an Ammo class means it cannot use it.
int Fullness(AActor *pawn, const char *className)
{
	const ClassDef *cls = ClassDef::FindClass(className);
	if(cls == NULL)
		return -1;
	AInventory *const held = pawn->FindInventory(cls);
	if(held == NULL)
		return -1;
	const unsigned int cap = held->maxamount;
	if(cap == 0)
		return 1000;
	const unsigned int have = held->amount > cap ? cap : held->amount;
	return (int)((have*1000)/cap);
}

}

int Need(Session::PlayerSlot slot, Category category)
{
	if(slot >= MAXPLAYERS || players[slot].mo == NULL ||
		players[slot].health <= 0)
		return 0;
	AActor *const pawn = players[slot].mo;

	switch(category)
	{
		case Category::Health:
		{
			// Nonlinear, and steeply so. Full health wants nothing; a quarter
			// health wants it more than three times as much as three-quarters
			// does, which is the shape of actually needing it.
			const int have = players[slot].health;
			const int max = pawn->SpawnHealth() > 0 ? pawn->SpawnHealth() : 100;
			const int missing = have >= max ? 0 : ((max - have)*1000)/max;
			return (missing*missing)/1000;
		}

		case Category::Armor:
		{
			const int armor = Fullness(pawn, "C7BodyArmor");
			return armor < 0 ? 700 : (1000 - armor)*7/10;
		}

		case Category::Invulnerability:
			// Always worth having and never worth dying for. Section 14.2:
			// valuable, but not worth repeated lethal traversal.
			return 500;

		case Category::Ammo:
		{
			const int bullets = Fullness(pawn, "C7Bullets");
			if(bullets < 0)
				return 0;			// nothing that uses it
			return 1000 - bullets;
		}

		case Category::Energy:
		{
			const int energy = Fullness(pawn, "C7EnergyCapacity");
			if(energy < 0)
				return 0;
			return 1000 - energy;
		}

		case Category::VisorCharge:
		{
			const int charge = Fullness(pawn, "C7VisorCharge");
			if(charge < 0)
				return 0;
			// Useful, but a bot is not going to cross an arena for it.
			return (1000 - charge)/2;
		}

		case Category::Mine:
			return 300;

		case Category::Weapon:
			// Whether this particular weapon is worth anything depends on
			// which weapon it is, and the caller knows that. Answered by
			// NeedWeapon; the category on its own says only "possibly".
			return 600;

		default:
			return 100;
	}
}

int NeedWeapon(Session::PlayerSlot slot, FName cls)
{
	if(slot >= MAXPLAYERS || players[slot].mo == NULL)
		return 0;
	const ClassDef *def = ClassDef::FindClass(cls);
	if(def == NULL)
		return 0;
	// Already carried. Under multiplayer stay-in-world rules the pickup does
	// not vanish and collecting it again does nothing at all, so it is worth
	// exactly nothing -- not "a little less".
	if(players[slot].mo->FindInventory(def) != NULL)
		return 0;
	return Need(slot, Category::Weapon);
}

void NotePickup(const AActor *taker)
{
	if(taker == NULL)
		return;
	for(unsigned int i = 0;i < MAXPLAYERS;++i)
	{
		if(players[i].mo == taker)
		{
			++g_pickups[i];
			break;
		}
	}
}

unsigned int PickupsBy(Session::PlayerSlot slot)
{
	return slot < MAXPLAYERS ? g_pickups[slot] : 0;
}

unsigned int WeaponsHeld(Session::PlayerSlot slot)
{
	if(slot >= MAXPLAYERS || players[slot].mo == NULL)
		return 0;
	unsigned int held = 0;
	for(AInventory *item = players[slot].mo->inventory;item != NULL;
		item = item->inventory)
	{
		if(item->IsKindOf(NATIVE_CLASS(Weapon)))
			++held;
	}
	return held;
}

const char *RejectName(Reject why)
{
	switch(why)
	{
		case Reject::None:         return "chosen";
		case Reject::NotPresent:   return "not-present";
		case Reject::Stale:        return "stale";
		case Reject::AlreadyHave:  return "already-have";
		case Reject::NoNeed:       return "no-need";
		case Reject::Unreachable:  return "unreachable";
		case Reject::TooFar:       return "too-far";
		case Reject::LostToBetter: return "lost-to-better";
		default:                   return "?";
	}
}

void Tally(Session::PlayerSlot slot, unsigned int &present, unsigned int &gone,
	unsigned int &unknown)
{
	present = gone = unknown = 0;
	if(slot >= MAXPLAYERS)
		return;
	for(unsigned int a = 0;a < g_belief[slot].Size();++a)
	{
		switch(g_belief[slot][a].belief)
		{
			case Belief::Present: ++present; break;
			case Belief::Gone:    ++gone;    break;
			default:              ++unknown; break;
		}
	}
}

// --- self-test ------------------------------------------------------------

namespace {
int g_checks = 0, g_failures = 0;
void Check(bool ok, const char *what)
{
	++g_checks;
	if(!ok)
	{
		++g_failures;
		Printf("  FAIL %s\n", what);
	}
	else
		Printf("  ok   %s\n", what);
}
}

int SelfTest()
{
	g_checks = g_failures = 0;
	Printf("Item knowledge self-test\n");

	Reset();
	g_annotations.Resize(2);
	for(unsigned int i = 0;i < MAXPLAYERS;++i)
	{
		g_belief[i].Resize(2);
		for(unsigned int a = 0;a < 2;++a)
			g_belief[i][a] = Knowledge();
	}

	Printf("\nBelief\n");
	Check(KnownTo(0, 0)->belief == Belief::Unknown,
		"a bot starts out knowing nothing about a pickup");

	Observe(0, 0, true, 100);
	Check(KnownTo(0, 0)->belief == Belief::Present, "seeing one makes it present");
	Check(KnownTo(1, 0)->belief == Belief::Unknown,
		"and tells nobody else");
	Check(KnownTo(0, 1)->belief == Belief::Unknown,
		"nor anything about the other pickup");

	Observe(0, 0, false, 200);
	Check(KnownTo(0, 0)->belief == Belief::Gone,
		"seeing the place empty makes it gone");

	Printf("\nAgeing\n");
	Observe(0, 0, true, 1000);
	Age(1000 + STALE_TICS - 1);
	Check(KnownTo(0, 0)->belief == Belief::Present,
		"a fresh belief survives");
	Age(1000 + STALE_TICS);
	Check(KnownTo(0, 0)->belief == Belief::Unknown,
		"and an old one decays");

	// The one that matters: stale news becomes "go and look", never "it is
	// not there". A bot that decays to Gone stops checking and never learns.
	Observe(0, 1, false, 2000);
	Age(2000 + STALE_TICS);
	Check(KnownTo(0, 1)->belief == Belief::Unknown,
		"a stale absence decays to unknown, not to absent");

	Reset();
	Check(Count() == 0, "and Reset leaves nothing behind");

	Printf("\n%d checks, %d failures\n", g_checks, g_failures);
	return g_failures;
}

}
