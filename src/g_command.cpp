/*
** g_command.cpp
**
** See g_command.h for what this boundary is for.
*/

#include <stdio.h>
#include <string.h>

#include "g_command.h"
#include "wl_play.h"
#include "wl_main.h"
#include "files.h"

namespace Command {

void Intent::Clear()
{
	forward = strafe = turn = 0;
	memset(press, 0, sizeof(press));
}

void Intent::Press(int button)
{
	if(button >= 0 && button < NUMBUTTONS)
		press[button] = true;
}

// The list is deliberately a denial rather than an allowance, so that a button
// added to the enum is a gameplay button until somebody says otherwise -- a new
// weapon action that silently stopped working would be a worse failure than a
// new UI key that briefly travels.
bool IsGameplayButton(int button)
{
	switch(button)
	{
		case bt_esc:
		case bt_pause:
		case bt_automap:
		case bt_c7map:
		case bt_showstatusbar:
		case bt_scoreboard:
			return false;
		default:
			return button >= 0 && button < NUMBUTTONS;
	}
}

namespace {

Producer    *g_producers[MAXPLAYERS] = { NULL };
// The command last actually applied to each slot. Held state is measured
// against this and nothing else.
TicCmd_t     g_applied[MAXPLAYERS];
bool         g_haveApplied[MAXPLAYERS] = { false };
bool         g_installedThisFrame[MAXPLAYERS] = { false };
uint32_t     g_sequence = 0;
bool         g_inFrame = false;
Violations   g_violations;
uint32_t     g_digest = 0;
FILE        *g_trace = NULL;

int ClampAxis(int value, unsigned int *clamped)
{
	if(value < AXIS_MIN) { if(clamped) ++*clamped; return AXIS_MIN; }
	if(value > AXIS_MAX) { if(clamped) ++*clamped; return AXIS_MAX; }
	return value;
}

// FNV-1a over the bytes that matter, so that "the machines pressed the same
// things" can be compared without comparing the whole world.
void FoldDigest(const void *data, size_t len)
{
	const unsigned char *p = (const unsigned char *)data;
	for(size_t i = 0;i < len;++i)
	{
		g_digest ^= p[i];
		g_digest *= 16777619u;
	}
}

void Record(Session::PlayerSlot slot, const TicCmd_t &cmd)
{
	const uint32_t seq = g_sequence;
	FoldDigest(&seq, sizeof(seq));
	const uint8_t s = (uint8_t)slot;
	FoldDigest(&s, sizeof(s));
	const int32_t axes[3] = { cmd.controlx, cmd.controly, cmd.controlstrafe };
	FoldDigest(axes, sizeof(axes));
	FoldDigest(cmd.buttonstate, sizeof(cmd.buttonstate));
	FoldDigest(cmd.buttonheld, sizeof(cmd.buttonheld));

	if(g_trace == NULL)
		return;

	// One line per slot per sequence. Buttons as a bit string rather than a
	// number, because the question asked of this file is almost always "which
	// button" and counting bits by hand is how that goes wrong.
	char pressed[NUMBUTTONS + 1];
	char held[NUMBUTTONS + 1];
	for(int i = 0;i < NUMBUTTONS;++i)
	{
		pressed[i] = cmd.buttonstate[i] ? '1' : '0';
		held[i] = cmd.buttonheld[i] ? '1' : '0';
	}
	pressed[NUMBUTTONS] = held[NUMBUTTONS] = '\0';

	fprintf(g_trace, "%u %u %d %d %d %s %s %s\n",
		(unsigned)seq, (unsigned)slot,
		cmd.controlx, cmd.controly, cmd.controlstrafe,
		pressed, held,
		HasProducer(slot) ? ProducerFor(slot)->Describe() : "sampled");
}

// Finalization, in one place, for every producer and every packet. Clamps the
// axes, strips anything that is not a gameplay control, and derives the held
// state from the previous command applied to this slot.
void Finalize(Session::PlayerSlot slot, TicCmd_t &cmd)
{
	cmd.controlx = ClampAxis(cmd.controlx, &g_violations.clampedAxes);
	cmd.controly = ClampAxis(cmd.controly, &g_violations.clampedAxes);
	cmd.controlstrafe = ClampAxis(cmd.controlstrafe, &g_violations.clampedAxes);

	// Pan is not carried between machines and is not a gameplay control; see
	// S1 and the plan's section 24.3.
	cmd.controlpanx = cmd.controlpany = 0;

	for(int i = 0;i < NUMBUTTONS;++i)
	{
		if(cmd.buttonstate[i] && !IsGameplayButton(i))
		{
			cmd.buttonstate[i] = 0;
			++g_violations.strippedButtons;
		}
	}

	// Held is "this button, in the command applied to this slot last time".
	// Not what the producer claimed, and not what a packet asserted: a
	// producer that gets this wrong turns a tap into a hold, and a hold into a
	// string of taps -- which is how one press of the visor once cycled it
	// eleven times.
	if(g_haveApplied[slot])
	{
		for(int i = 0;i < NUMBUTTONS;++i)
			cmd.buttonheld[i] = g_applied[slot].buttonstate[i];
	}
	else
	{
		memset(cmd.buttonheld, 0, sizeof(cmd.buttonheld));
	}

	// The automap fields are not part of a canonical command. They are left
	// out of the recorded copy for that reason; control[] keeps whatever the
	// local instance sampled, because that is where its own automap handling
	// reads them.
	memset(cmd.ambuttonstate, 0, sizeof(cmd.ambuttonstate));
	memset(cmd.ambuttonheld, 0, sizeof(cmd.ambuttonheld));
}

void Apply(Session::PlayerSlot slot, TicCmd_t &cmd)
{
	Finalize(slot, cmd);
	Record(slot, cmd);

	// The automap fields belong to the local instance and are left where they
	// are: control[] is also what wl_play reads for its own UI handling.
	control[slot].controlx = cmd.controlx;
	control[slot].controly = cmd.controly;
	control[slot].controlstrafe = cmd.controlstrafe;
	memcpy(control[slot].buttonstate, cmd.buttonstate,
		sizeof(control[slot].buttonstate));
	memcpy(control[slot].buttonheld, cmd.buttonheld,
		sizeof(control[slot].buttonheld));

	g_applied[slot] = cmd;
	g_haveApplied[slot] = true;
	g_installedThisFrame[slot] = true;
}

}

// --- the canonical frame -------------------------------------------------------

void BeginFrame(uint32_t sequence)
{
	g_sequence = sequence;
	g_inFrame = true;
	memset(g_installedThisFrame, 0, sizeof(g_installedThisFrame));
}

void InstallSampled(Session::PlayerSlot slot, const TicCmd_t &sampled)
{
	if(slot >= MAXPLAYERS)
		return;
	TicCmd_t cmd = sampled;
	Apply(slot, cmd);
}

void ProduceAndInstall(Session::PlayerSlot slot, uint32_t sequence)
{
	if(slot >= MAXPLAYERS)
		return;

	TicCmd_t cmd;
	memset(&cmd, 0, sizeof(cmd));

	Intent intent;
	Producer *producer = g_producers[slot];
	if(producer != NULL && producer->Produce(slot, sequence, intent))
	{
		cmd.controlx = intent.turn;
		cmd.controly = intent.forward;
		cmd.controlstrafe = intent.strafe;
		for(int i = 0;i < NUMBUTTONS;++i)
			cmd.buttonstate[i] = intent.press[i] ? 1 : 0;
	}
	// A producer with nothing to say gets a neutral command rather than the
	// last one repeated: a stuck attack button is worse than standing still,
	// and repeating a command is how a dead controller keeps firing.

	Apply(slot, cmd);
}

void FinishFrame()
{
	if(!g_inFrame)
		return;
	g_inFrame = false;

	for(unsigned int i = 0;i < Session::ActiveSlotCount();++i)
	{
		if(g_installedThisFrame[i])
			continue;
		++g_violations.missingCommands;
#ifndef NDEBUG
		I_FatalError("No command for active slot %u at sequence %u", i,
			(unsigned)g_sequence);
#endif
	}
}

// --- producers -----------------------------------------------------------------

void SetProducer(Session::PlayerSlot slot, Producer *producer)
{
	if(slot >= MAXPLAYERS)
	{
		delete producer;
		return;
	}
	delete g_producers[slot];
	g_producers[slot] = producer;
}

Producer *ProducerFor(Session::PlayerSlot slot)
{
	return slot < MAXPLAYERS ? g_producers[slot] : NULL;
}

bool HasProducer(Session::PlayerSlot slot)
{
	return ProducerFor(slot) != NULL;
}

void ClearProducers()
{
	for(unsigned int i = 0;i < MAXPLAYERS;++i)
	{
		delete g_producers[i];
		g_producers[i] = NULL;
	}
}

// --- the scripted producer ------------------------------------------------------
//
// A tape is a text file, one line per tic:
//
//     <turn> <forward> <strafe> [button ...]
//     repeat N          the previous line again, N more times
//     loop              start over from the top when the tape runs out
//
// Blank lines and # comments are skipped. Button names are the gameplay ones;
// naming a UI button is allowed here on purpose, so that a test can prove the
// finalizer strips it rather than having to trust that it would.

namespace {

struct ButtonName { const char *name; int button; };

const ButtonName kButtonNames[] = {
	{ "attack",       bt_attack },
	{ "strafe",       bt_strafe },
	{ "run",          bt_run },
	{ "use",          bt_use },
	{ "slot1",        bt_slot1 },
	{ "slot2",        bt_slot2 },
	{ "slot3",        bt_slot3 },
	{ "slot4",        bt_slot4 },
	{ "slot5",        bt_slot5 },
	{ "slot6",        bt_slot6 },
	{ "slot7",        bt_slot7 },
	{ "slot8",        bt_slot8 },
	{ "nextweapon",   bt_nextweapon },
	{ "prevweapon",   bt_prevweapon },
	{ "altattack",    bt_altattack },
	{ "reload",       bt_reload },
	{ "zoom",         bt_zoom },
	{ "moveforward",  bt_moveforward },
	{ "movebackward", bt_movebackward },
	{ "strafeleft",   bt_strafeleft },
	{ "straferight",  bt_straferight },
	{ "turnleft",     bt_turnleft },
	{ "turnright",    bt_turnright },
	// Named so a test can ask for them and watch them be removed.
	{ "esc",          bt_esc },
	{ "pause",        bt_pause },
	{ "automap",      bt_automap },
	{ "c7map",        bt_c7map },
	{ "statusbar",    bt_showstatusbar },
	{ "scoreboard",   bt_scoreboard },
};

int ButtonByName(const char *name)
{
	for(unsigned int i = 0;i < sizeof(kButtonNames)/sizeof(kButtonNames[0]);++i)
	{
		if(stricmp(kButtonNames[i].name, name) == 0)
			return kButtonNames[i].button;
	}
	return bt_nobutton;
}

class ScriptedProducer : public Producer
{
public:
	bool Load(const char *path, FString &error);

	bool Produce(Session::PlayerSlot slot, uint32_t sequence, Intent &out);
	const char *Describe() const { return "tape"; }

private:
	TArray<Intent> steps;
	bool     loop = false;
	unsigned position = 0;
};

bool ScriptedProducer::Load(const char *path, FString &error)
{
	FILE *file = fopen(path, "r");
	if(file == NULL)
	{
		error.Format("cannot open command tape '%s'", path);
		return false;
	}

	char line[512];
	unsigned int lineNumber = 0;
	while(fgets(line, sizeof(line), file) != NULL)
	{
		++lineNumber;
		char *hash = strchr(line, '#');
		if(hash != NULL)
			*hash = '\0';

		char *token = strtok(line, " \t\r\n");
		if(token == NULL)
			continue;

		if(stricmp(token, "loop") == 0)
		{
			loop = true;
			continue;
		}
		if(stricmp(token, "repeat") == 0)
		{
			char *count = strtok(NULL, " \t\r\n");
			if(count == NULL || steps.Size() == 0)
			{
				error.Format("%s:%u: repeat with nothing to repeat",
					path, lineNumber);
				fclose(file);
				return false;
			}
			const int times = atoi(count);
			if(times < 0 || times > 100000)
			{
				error.Format("%s:%u: repeat %d is out of range",
					path, lineNumber, times);
				fclose(file);
				return false;
			}
			const Intent previous = steps[steps.Size() - 1];
			for(int i = 0;i < times;++i)
				steps.Push(previous);
			continue;
		}

		Intent step;
		step.turn = atoi(token);
		char *forward = strtok(NULL, " \t\r\n");
		char *strafe = strtok(NULL, " \t\r\n");
		if(forward == NULL || strafe == NULL)
		{
			error.Format("%s:%u: needs turn, forward and strafe",
				path, lineNumber);
			fclose(file);
			return false;
		}
		step.forward = atoi(forward);
		step.strafe = atoi(strafe);

		for(char *name = strtok(NULL, " \t\r\n"); name != NULL;
			name = strtok(NULL, " \t\r\n"))
		{
			const int button = ButtonByName(name);
			if(button == bt_nobutton)
			{
				error.Format("%s:%u: no button called '%s'",
					path, lineNumber, name);
				fclose(file);
				return false;
			}
			step.Press(button);
		}
		steps.Push(step);
	}
	fclose(file);

	if(steps.Size() == 0)
	{
		error.Format("command tape '%s' has no steps in it", path);
		return false;
	}
	return true;
}

bool ScriptedProducer::Produce(Session::PlayerSlot, uint32_t, Intent &out)
{
	if(position >= steps.Size())
	{
		if(!loop)
			return false;
		position = 0;
	}
	out = steps[position++];
	return true;
}

}

Producer *MakeScriptedProducer(const char *tapePath, FString &error)
{
	ScriptedProducer *producer = new ScriptedProducer;
	if(!producer->Load(tapePath, error))
	{
		delete producer;
		return NULL;
	}
	return producer;
}

// --- local UI intent --------------------------------------------------------------

namespace { TicCmd_t g_localUi; bool g_haveLocalUi = false; }

void SetLocalUi(const TicCmd_t &sampled)
{
	g_localUi = sampled;
	g_haveLocalUi = true;
}

const TicCmd_t &LocalUi()
{
	if(!g_haveLocalUi)
	{
		memset(&g_localUi, 0, sizeof(g_localUi));
		g_haveLocalUi = true;
	}
	return g_localUi;
}

// --- diagnostics ----------------------------------------------------------------

void OpenTrace(const char *path)
{
	CloseTrace();
	g_trace = fopen(path, "w");
	if(g_trace != NULL)
		fprintf(g_trace, "# sequence slot turn forward strafe pressed held producer\n");
}

void CloseTrace()
{
	if(g_trace != NULL)
	{
		fclose(g_trace);
		g_trace = NULL;
	}
}

uint32_t Digest() { return g_digest; }

const Violations &GetViolations() { return g_violations; }

void ResetViolations() { g_violations = Violations(); }

}
