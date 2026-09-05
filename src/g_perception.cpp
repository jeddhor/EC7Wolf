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

namespace Perception {

namespace {

Observation  g_observation[MAXPLAYERS];
unsigned int g_observers = 0;
FILE        *g_trace = NULL;

// Fold a signed angular difference to 0..180 degrees worth of angle_t.
angle_t OffAxis(angle_t facing, angle_t toward)
{
	const angle_t diff = toward - facing;
	return diff <= ANGLE_180 ? diff : (angle_t)(0u - diff);
}

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
	}
	g_observers = 0;
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

	// Ascending slot order, so that anything downstream which breaks a tie on
	// "the first one seen" breaks it the same way twice.
	for(unsigned int slot = 0;slot < MAXPLAYERS;++slot)
	{
		Observation &obs = g_observation[slot];
		obs = Observation();
		obs.players.Clear();
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
