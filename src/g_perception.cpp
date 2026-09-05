/*
** g_perception.cpp
**
** See g_perception.h.
*/

#include <stdio.h>
#include <stdlib.h>

#include "g_perception.h"
#include "g_bot.h"
#include "g_botnav.h"
#include "actor.h"
#include "wl_agent.h"
#include "wl_def.h"
#include "wl_play.h"
#include "wl_state.h"
#include "gamemap.h"
#include "id_ca.h"
#include "thingdef/thingdef.h"
#include "wl_game.h"
#include "g_shared/a_inventory.h"
#include "wl_draw.h"

namespace Perception {

namespace {

Observation  g_observation[MAXPLAYERS];
unsigned int g_observers = 0;
FILE        *g_trace = NULL;

// Noises made during the tic now finishing, read by the next tic's sense
// update. A tic of latency, which is both harmless -- the reaction delay is
// twenty times longer -- and correct: a sound made by a command applied this
// tic cannot be heard by a decision taken before that command ran.
struct RawSound
{
	SoundKind kind;
	int16_t   sourceSlot;
	fixed     x, y;
	const MapZone *zone;
	int       loudnessTiles;
};
enum { MAX_SOUNDS = 64 };
RawSound     g_pending[MAX_SOUNDS];
unsigned int g_pendingCount = 0;
RawSound     g_current[MAX_SOUNDS];
unsigned int g_currentCount = 0;

// What each bot has learned about laser barriers, kept between tics. This is
// memory rather than perception: it survives the visor being switched off,
// which is the point of learning something.
TArray<HazardKnowledge> g_hazards[MAXPLAYERS];

// Does this player have the infrared visor running? Read from that player's
// own inventory -- never from ConsolePlayer's camera, which is what the
// renderer uses and which describes one screen rather than eight bots.
bool HasInfrared(unsigned int slot)
{
	if(slot >= MAXPLAYERS || players[slot].mo == NULL)
		return false;
	AInventory *const mode =
		players[slot].mo->FindInventory(ClassDef::FindClass("C7VisorMode"));
	return mode != NULL && mode->amount == 3;
}

void Remember(unsigned int slot, uint16_t tx, uint16_t ty, bool byContact,
	uint32_t when)
{
	if(slot >= MAXPLAYERS)
		return;
	TArray<HazardKnowledge> &known = g_hazards[slot];
	for(unsigned int i = 0;i < known.Size();++i)
	{
		if(known[i].tileX == tx && known[i].tileY == ty)
		{
			known[i].knownAt = when;
			known[i].byContact = known[i].byContact || byContact;
			return;
		}
	}
	HazardKnowledge fresh;
	fresh.tileX = tx;
	fresh.tileY = ty;
	fresh.byContact = byContact;
	fresh.knownAt = when;
	known.Push(fresh);
}

// Fold a signed angular difference to 0..180 degrees worth of angle_t.
angle_t OffAxis(angle_t facing, angle_t toward)
{
	const angle_t diff = toward - facing;
	return diff <= ANGLE_180 ? diff : (angle_t)(0u - diff);
}

}

const char *SoundName(SoundKind kind)
{
	switch(kind)
	{
		case SoundKind::Weapon: return "weapon";
		case SoundKind::Door:   return "door";
		case SoundKind::Pain:   return "pain";
		case SoundKind::Death:  return "death";
		default:                return "?";
	}
}

void Emit(SoundKind kind, const AActor *source, int loudnessTiles)
{
	if(source == NULL || g_pendingCount >= MAX_SOUNDS)
		return;

	RawSound &ev = g_pending[g_pendingCount++];
	ev.kind = kind;
	ev.x = source->x;
	ev.y = source->y;
	ev.zone = source->GetZone();
	ev.loudnessTiles = loudnessTiles;
	ev.sourceSlot = -1;
	for(unsigned int i = 0;i < MAXPLAYERS;++i)
	{
		if(players[i].mo == source)
		{
			ev.sourceSlot = (int16_t)i;
			break;
		}
	}
}

void NoteHazardContact(const AActor *victim)
{
	if(victim == NULL)
		return;
	for(unsigned int i = 0;i < MAXPLAYERS;++i)
	{
		if(players[i].mo != victim)
			continue;
		// Learned the hard way, at the place it happened, by the one it
		// happened to. Nobody else is told.
		Remember(i, (uint16_t)victim->tilex, (uint16_t)victim->tiley, true,
			gamestate.TimeCount);
		if(g_trace != NULL)
			fprintf(g_trace, "hazard %lu %u %d %d contact\n",
				(unsigned long)gamestate.TimeCount, i,
				victim->tilex, victim->tiley);
		break;
	}
}

const TArray<HazardKnowledge> *HazardsKnownTo(Session::PlayerSlot slot)
{
	if(slot >= MAXPLAYERS)
		return NULL;
	return &g_hazards[slot];
}

const PlayerSighting *Observation::Seen(Session::PlayerSlot slot) const
{
	for(unsigned int i = 0;i < players.Size();++i)
	{
		if(players[i].slot == slot)
			return &players[i];
	}
	return NULL;
}

void Reset()
{
	for(unsigned int i = 0;i < MAXPLAYERS;++i)
	{
		g_observation[i] = Observation();
		g_observation[i].players.Clear();
		g_observation[i].sounds.Clear();
		g_observation[i].hazards.Clear();
		g_hazards[i].Clear();
	}
	g_observers = 0;
	g_pendingCount = 0;
	g_currentCount = 0;
}

unsigned int Observers() { return g_observers; }

bool OpenTrace(const char *path)
{
	CloseTrace();
	g_trace = fopen(path, "w");
	if(g_trace == NULL)
		return false;
	fprintf(g_trace, "# tic observer ox oy subject sx sy distance bearing offaxis"
		"   (positions in map units, 64 to the tile)\n");
	return true;
}

void CloseTrace()
{
	if(g_trace != NULL)
	{
		fclose(g_trace);
		g_trace = NULL;
	}
}

void BeginFrame(uint32_t sequence)
{
	g_observers = 0;

	// Take the noises made during the tic just finished, and start a fresh
	// list for the tic about to run.
	g_currentCount = g_pendingCount;
	for(unsigned int i = 0;i < g_pendingCount;++i)
		g_current[i] = g_pending[i];
	g_pendingCount = 0;

	// Ascending slot order, so that anything downstream which breaks a tie on
	// "the first one seen" breaks it the same way twice.
	for(unsigned int slot = 0;slot < MAXPLAYERS;++slot)
	{
		Observation &obs = g_observation[slot];
		obs = Observation();
		obs.players.Clear();
		obs.sounds.Clear();
		obs.hazards.Clear();
		obs.sequence = sequence;

		if(!Bot::Active(slot))
			continue;

		AActor *const eye = Bot::OwnPawn(slot);
		if(eye == NULL)
		{
			// Dead or not spawned. A valid observation of nothing, which is
			// different from no observation at all: the brain should be able
			// to tell "I looked and saw nobody" from "I did not look".
			obs.valid = true;
			++g_observers;
			continue;
		}

		obs.valid = true;
		obs.self.x = eye->x;
		obs.self.y = eye->y;
		obs.self.angle = eye->angle;
		obs.self.tileX = (uint16_t)eye->tilex;
		obs.self.tileY = (uint16_t)eye->tiley;
		obs.self.health = players[slot].health;
		obs.self.alive = true;
		++g_observers;

		// Laser barriers, and only with the visor on. Without infrared this
		// loop does not run at all -- not "runs and filters", does not run.
		// An actor scan that happened to be filtered later is one refactor
		// away from being a scan that is not.
		if(HasInfrared(slot))
		{
			for(AActor::Iterator iter = AActor::GetIterator();iter.Next();)
			{
				AActor *const thing = iter;
				if(!Corridor7IsLaserBarrierActor(thing))
					continue;

				const angle_t toward = BotNav::BearingTo(eye->x, eye->y,
					thing->x, thing->y);
				if(OffAxis(eye->angle, toward) > FOV_HALF)
					continue;
				if(!CheckLine(eye, thing))
					continue;

				HazardKnowledge seen;
				seen.tileX = (uint16_t)thing->tilex;
				seen.tileY = (uint16_t)thing->tiley;
				seen.byContact = false;
				seen.knownAt = sequence;
				obs.hazards.Push(seen);
				Remember(slot, seen.tileX, seen.tileY, false, sequence);

				if(g_trace != NULL)
					fprintf(g_trace, "hazard %u %u %d %d seen\n",
						sequence, slot, thing->tilex, thing->tiley);
			}
		}

		// Hearing, before vision, so that a sound from somebody already in
		// view can be attributed and one from a stranger cannot. Iterated in
		// emission order, which is the order the world made them in.
		for(unsigned int e = 0;e < g_currentCount;++e)
		{
			const RawSound &raw = g_current[e];
			if(raw.sourceSlot == (int16_t)slot)
				continue;			// you do not startle yourself

			const int64_t dxt = ((int64_t)raw.x - eye->x)>>TILESHIFT;
			const int64_t dyt = ((int64_t)raw.y - eye->y)>>TILESHIFT;
			int64_t a = dxt < 0 ? -dxt : dxt;
			int64_t b = dyt < 0 ? -dyt : dyt;
			if(a < b) { const int64_t t = a; a = b; b = t; }
			const int32_t range = (int32_t)((a*1007 + b*441)>>10);
			if(range > raw.loudnessTiles)
				continue;

			// Corridor 7's sound zones, and the doors between them. A floor
			// word of zero is no zone at all, and nothing can be heard from
			// there or in it -- which is the map saying "this is outside the
			// audible world", not an oversight to be worked around.
			const MapZone *const ear = eye->GetZone();
			if(raw.zone == NULL || ear == NULL)
				continue;
			if(raw.zone != ear && !map->CheckLink(raw.zone, ear, true))
				continue;

			AudibleEvent heard;
			heard.kind = raw.kind;
			heard.heardAt = sequence;
			// Quantised to a 45-degree sector. A player hears a shot off to
			// the left; they do not hear a bearing.
			const angle_t exact = BotNav::BearingTo(eye->x, eye->y, raw.x, raw.y);
			heard.bearing = (angle_t)((exact / ANGLE_45) * ANGLE_45) +
				(angle_t)(ANGLE_45/2);
			// And banded rather than measured: close, nearby, somewhere off.
			heard.band = range <= 4 ? 0 : (range <= 12 ? 1 : 2);
			// Whose it was, only if they are already in plain sight.
			heard.sourceSlot = -1;
			if(raw.sourceSlot >= 0 && raw.sourceSlot < (int16_t)MAXPLAYERS)
			{
				AActor *const who = players[raw.sourceSlot].mo;
				if(who != NULL && players[raw.sourceSlot].health > 0 &&
					OffAxis(eye->angle, BotNav::BearingTo(eye->x, eye->y,
						who->x, who->y)) <= FOV_HALF &&
					CheckLine(eye, who))
					heard.sourceSlot = raw.sourceSlot;
			}
			obs.sounds.Push(heard);

			if(g_trace != NULL)
			{
				// The true range and loudness go in the trace but not in the
				// observation: a gate needs to check the sound carried no
				// further than it should have, and the brain needs not to
				// know the distance to a shooter it cannot see.
				fprintf(g_trace,
					"sound %u %u %s band %d bearing %u from %d range %d loud %d\n",
					sequence, slot, SoundName(raw.kind), heard.band,
					(unsigned)(heard.bearing/ANGLE_1), heard.sourceSlot,
					range, raw.loudnessTiles);
			}
		}

		for(unsigned int other = 0;other < MAXPLAYERS;++other)
		{
			if(other == slot)
				continue;
			// Alive, in the world, and a target under the ordinary rules. A
			// bot may not see a corpse or an empty slot as a player.
			if(players[other].mo == NULL || players[other].health <= 0)
				continue;
			if(Session::KindOf((Session::PlayerSlot)other) ==
				Session::SlotKind::Empty)
				continue;

			AActor *const target = players[other].mo;

			const angle_t bearing = BotNav::BearingTo(eye->x, eye->y,
				target->x, target->y);
			const angle_t off = OffAxis(eye->angle, bearing);
			if(off > FOV_HALF)
				continue;			// behind, or off the edge of the screen

			// Gameplay line of sight, through the same check the game's own
			// monsters use. Not a renderer visibility mark: those describe one
			// camera and are not computed at all when nothing is drawn.
			if(!CheckLine(eye, target))
				continue;

			PlayerSighting sighting;
			sighting.slot = (Session::PlayerSlot)other;
			sighting.x = target->x;
			sighting.y = target->y;
			sighting.bearing = bearing;
			sighting.offAxis = off;
			sighting.seenAt = sequence;

			const int64_t dx = (int64_t)(target->x - eye->x)>>FRACBITS;
			const int64_t dy = (int64_t)(target->y - eye->y)>>FRACBITS;
			// Integer hypotenuse, near enough for a comparison and identical
			// on every machine, which a square root would not be.
			int64_t a = dx < 0 ? -dx : dx;
			int64_t b = dy < 0 ? -dy : dy;
			if(a < b) { const int64_t t = a; a = b; b = t; }
			sighting.distanceTiles = (int32_t)((a*1007 + b*441)>>10);

			obs.players.Push(sighting);

			if(g_trace != NULL)
			{
				// Both ends of the line, because a gate that wants to check
				// the sight line for itself needs to know where it was drawn
				// from as well as to.
				// Map units rather than tiles. A gate that re-walks the
				// sight line has to be more precise than the thing it is
				// checking, and at tile precision the line between two tile
				// indices is not the line the engine tested: fifteen sightings
				// in four hundred came back as wall leaks that were nothing of
				// the sort.
				fprintf(g_trace, "%u %u %d %d %u %d %d %d %u %u\n",
					sequence, slot,
					eye->x>>10, eye->y>>10, other,
					target->x>>10, target->y>>10,
					sighting.distanceTiles,
					(unsigned)(bearing/ANGLE_1), (unsigned)(off/ANGLE_1));
			}
		}
	}
}

const Observation *For(Session::PlayerSlot slot)
{
	if(slot >= MAXPLAYERS || !g_observation[slot].valid)
		return NULL;
	return &g_observation[slot];
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
	Printf("Perception self-test\n");

	// The angle fold is the whole of the field-of-view test, and a sign error
	// in it is a bot that can only see things on its left.
	Printf("\nOff-axis angles\n");
	Check(OffAxis(0, 0) == 0, "dead ahead is zero off axis");
	Check(OffAxis(0, ANGLE_45) == (angle_t)ANGLE_45, "to the left folds to 45");
	Check(OffAxis(0, (angle_t)(0u - ANGLE_45)) == (angle_t)ANGLE_45,
		"and to the right folds to 45 as well");
	Check(OffAxis(0, ANGLE_180) == (angle_t)ANGLE_180, "behind is 180");
	Check(OffAxis(ANGLE_90, ANGLE_90 + ANGLE_45) == (angle_t)ANGLE_45,
		"and it is measured from the observer's own facing");
	Check(OffAxis(0, ANGLE_180 + ANGLE_1) > (angle_t)ANGLE_180 == false,
		"nothing folds to more than 180");

	// A 90-degree screen means 45 each side, and the test is inclusive of the
	// edge: something exactly on the edge of the view is on the screen.
	Printf("\nField of view\n");
	const angle_t half = FOV_HALF;
	Check(OffAxis(0, ANGLE_45) <= half, "45 degrees off is inside the view");
	Check(OffAxis(0, ANGLE_45 + ANGLE_1*2) > half, "47 is outside it");
	Check(OffAxis(0, ANGLE_90) > half, "and a right angle certainly is");

	Printf("\n%d checks, %d failures\n", g_checks, g_failures);
	return g_failures;
}

}
