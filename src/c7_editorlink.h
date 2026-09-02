// SPDX-License-Identifier: GPL-2.0-or-later
//
// The editor link: a versioned, opt-in event stream for a parent process.
//
// EC7Edit launches the engine to let somebody try the map they are drawing, and
// then has to answer questions a process exit code cannot: did it find the game
// data, did it load MY map rather than the shipped one, did it reach the floor,
// and if it died, where. Reading the ordinary log for that would mean parsing
// prose that exists to be read by people and is free to change.
//
// So: an explicit protocol, off unless asked for, carrying a nonce the parent
// generated. Every line looks like
//
//     EC7EDIT <nonce> <event> key=value key=value
//
// and is flushed the moment it is written, because the parent reads it while
// the game is still running -- a report that arrives when the process exits is
// no use for "did it get into the map".
//
// The nonce is what makes the stream trustworthy. The engine prints plenty of
// other lines, a user's map can contain arbitrary text, and stdout may be
// shared; a parent that matched on "EC7EDIT " alone could be fed a forged
// event by the very map it is testing. Matching on a nonce it generated for
// this launch and nothing else cannot be.
//
// Deliberately not a general IPC channel: no commands come back, nothing here
// changes what the engine does, and with the option absent not a byte is
// written. See milestone E9 of docs/corridor7-level-editor.md.

#ifndef __C7_EDITORLINK_H__
#define __C7_EDITORLINK_H__

class FString;

namespace EditorLink
{
	//: The protocol version this build speaks. A parent asks for a version and
	//: is refused if it is not this one, rather than being handed events it may
	//: read differently.
	//:
	//: 2 added next= and secretnext= to map-entry, for checking a generated map
	//: pack's routing against what MAPINFO actually resolved. An exact match is
	//: still required in both directions: a reader that ignores keys it does
	//: not know is a reader that silently accepts a protocol it cannot check.
	const int PROTOCOL_VERSION = 2;

	// Reads --editor-protocol and --editor-session out of argv and claims both
	// tokens and their values, so normal parameter dispatch never sees them.
	// Safe to call before anything is initialised.
	void ParseArgs(int argc, char **argv);

	// Whether an editor asked for the stream. False for every ordinary run.
	bool Active();

	// True when this argv index was consumed here.
	bool ArgClaimed(int index);

	// --editor-capabilities: print what this build supports and exit. Answers
	// with no game data present, because the editor asks before it knows
	// whether the data it has is usable. Returns true when it handled the
	// argument and the caller should exit with the given code.
	bool RunCapabilityProbe(int argc, char **argv, int &exitCode);

	// The events. Each writes one line and flushes.
	void DataSelected(const char *extension, const char *directory);
	// Reported from the loader itself, success or failure, because failure is
	// silent otherwise: AddFile prints "Could not stat" and RETURNS rather than
	// raising, so a launch whose preview WAD was missing still exits 0, still
	// enters a map, and is the shipped map of that number rather than the one
	// the editor built. An editor that trusted a bare "preview-load" would
	// report a successful test of a map the player never saw.
	void PreviewLoaded(const char *path, bool loaded, unsigned int lumps);
	// `spawnFilter` is the skill's own 0-based filter index, not the
	// 1-based number --skill takes; the event says which it is.
	// `name` is the MAPINFO display name and `mapName` is the one stored in the
	// map record itself. Both, because only the second one distinguishes the
	// editor's map from the shipped map of the same number: MAPINFO names MAP01
	// "Corridor 7 Level 1" whichever file the data came from, so a reader
	// checking the display name cannot tell it played the wrong floor.
	// `next` and `secretnext` are what MAPINFO resolved for this level, so a
	// pack's generated routing can be checked against what the engine actually
	// read rather than against the text that was written. An empty secret is
	// reported as "-": a level with no secret exit and a level whose secret
	// exit goes nowhere are different, and an absent key would read as either.
	void MapEntered(const char *marker, const char *name, const char *mapName,
		int spawnFilter, const char *next, const char *secretNext);
	// The campaign reached its ending -- MAPINFO's next resolved to EndTitle or
	// an EndSequence rather than to another level. Worth its own event because
	// what follows is the victory page, which waits for a keypress: to anything
	// watching from outside, "finished the game" and "stopped responding" look
	// identical without this.
	void CampaignEnded(const char *via);
	void Fatal(const char *message);
	void SessionResult(const char *outcome);
}

#endif
