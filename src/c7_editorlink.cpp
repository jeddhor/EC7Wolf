// SPDX-License-Identifier: GPL-2.0-or-later
//
// See c7_editorlink.h for what this is and why the nonce matters.

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "c7_editorlink.h"
#include "tarray.h"
#include "zstring.h"
#include "version.h"
#include "gitinfo.h"

namespace EditorLink
{

namespace
{
	bool      g_active   = false;
	int       g_version  = 0;
	FString   g_session;
	TArray<bool> g_claimed;

	void Claim(int index)
	{
		if(index < 0)
			return;
		while((int)g_claimed.Size() <= index)
			g_claimed.Push(false);
		g_claimed[index] = true;
	}

	// A session id is echoed back on every line, so it has to be something a
	// parent can match exactly and a map cannot smuggle a newline through.
	// Anything outside this set is refused rather than sanitized: a silently
	// altered nonce would never match, and "my events stopped arriving" is a
	// much worse thing to debug than "that session id was rejected".
	bool Printable(const char *text)
	{
		if(text == NULL || *text == '\0')
			return false;
		for(const char *c = text; *c; ++c)
		{
			const bool ok = (*c >= 'a' && *c <= 'z') || (*c >= 'A' && *c <= 'Z')
				|| (*c >= '0' && *c <= '9') || *c == '-' || *c == '_';
			if(!ok)
				return false;
		}
		return strlen(text) <= 64;
	}

	// Values go out as key=value on one line, so a value may not carry a
	// separator or a line break. Replaced rather than dropped, so the length
	// of what the engine saw is still visible to whoever is reading.
	//: Longest value we will put on a line. A map supplies its own name, so a
	//: value is attacker-influenced in length as well as content, and a line
	//: over PIPE_BUF loses the single-write atomicity the whole format relies
	//: on. Truncated rather than dropped: a shortened name still identifies
	//: the map, and an absent one identifies nothing.
	const unsigned int VALUE_LIMIT = 160;

	FString Sanitized(const char *text)
	{
		FString out;
		for(const char *c = (text ? text : ""); *c; ++c)
		{
			if(out.Len() >= VALUE_LIMIT)
			{
				out += "...";
				break;
			}
			// Anything that is not plainly printable becomes '_': the grammar
			// is whitespace-separated key=value, so a space, an equals, a tab
			// or a newline in a value would silently become another field.
			const bool safe = (*c > 0x20 && (unsigned char)*c < 0x7f
				&& *c != '=' );
			out += safe ? *c : '_';
		}
		if(out.IsEmpty())
			out = "-";
		return out;
	}

	void Emit(const char *event, const char *body)
	{
		if(!g_active)
			return;
		// Straight to stdout, not Printf: Printf goes through the console,
		// which word-wraps, colors, and is not guaranteed to reach the pipe
		// before the frame ends. This has to be one line, exactly as written,
		// now.
		//
		// Assembled first and written once. A line built by several printf
		// calls can be spliced down the middle by anything else writing to the
		// same descriptor -- and the ordinary log and stderr often are the same
		// descriptor, because that is what a parent process pipe looks like.
		// One write under PIPE_BUF is not interleaved.
		FString line;
		line.Format("EC7EDIT %s %s%s%s\n", g_session.GetChars(), event,
			(body && *body) ? " " : "", body ? body : "");
		fwrite(line.GetChars(), 1, line.Len(), stdout);
		fflush(stdout);
	}
}

void ParseArgs(int argc, char **argv)
{
	for(int i = 1; i < argc; ++i)
	{
		if(strcmp(argv[i], "--editor-protocol") == 0 && i + 1 < argc)
		{
			Claim(i);
			g_version = atoi(argv[++i]);
			Claim(i);
		}
		else if(strcmp(argv[i], "--editor-session") == 0 && i + 1 < argc)
		{
			Claim(i);
			++i;
			Claim(i);
			if(Printable(argv[i]))
				g_session = argv[i];
			else
				printf("Editor link: session id refused; it must be 1-64 "
					"characters of A-Z a-z 0-9 - _\n");
		}
	}

	// Both halves or neither. A protocol version with no session would emit
	// events nobody can attribute; a session with no version does not say
	// which grammar the parent expects to read.
	if(g_version != 0 && !g_session.IsEmpty())
	{
		if(g_version != PROTOCOL_VERSION)
		{
			printf("Editor link: this build speaks protocol %d, not %d; "
				"no events will be sent.\n", PROTOCOL_VERSION, g_version);
			fflush(stdout);
			return;
		}
		g_active = true;
		Emit("hello", "engine=" GAMENAME " version=" DOTVERSIONSTR_NOREV);
	}
}

bool Active()
{
	return g_active;
}

bool ArgClaimed(int index)
{
	return index >= 0 && index < (int)g_claimed.Size() && g_claimed[index];
}

bool RunCapabilityProbe(int argc, char **argv, int &exitCode)
{
	bool wanted = false;
	for(int i = 1; i < argc; ++i)
	{
		if(strcmp(argv[i], "--editor-capabilities") == 0)
		{
			wanted = true;
			break;
		}
	}
	if(!wanted)
		return false;

	// Deliberately plain key=value on stdout and nothing else: this runs before
	// any game data is looked for, so it must not depend on a console, a
	// window, or an IWAD. An editor calls it to find out what it may ask for
	// before it asks.
	printf("engine=%s\n", GAMENAME);
	printf("version=%s\n", DOTVERSIONSTR_NOREV);
	printf("editor-protocol=%d\n", PROTOCOL_VERSION);
	printf("events=hello,data-selection,preview-load,map-entry,campaign-end,fatal,session-result\n");
	printf("options=--editor-protocol,--editor-session,--data,--file,--tedlevel,"
		"--skill,--config,--savedir,--res,--vid-renderer,--nowait,--no-upscale\n");
#ifdef ECWOLF_RENDERER_OPENGL
	printf("renderers=software,opengl\n");
#else
	printf("renderers=software\n");
#endif
	fflush(stdout);
	exitCode = 0;
	return true;
}

void DataSelected(const char *extension, const char *directory)
{
	FString body;
	body.Format("extension=%s directory=%s",
		Sanitized(extension).GetChars(), Sanitized(directory).GetChars());
	Emit("data-selection", body.GetChars());
}

void PreviewLoaded(const char *path, bool loaded, unsigned int lumps)
{
	FString body;
	body.Format("path=%s loaded=%s lumps=%u", Sanitized(path).GetChars(),
		loaded ? "yes" : "no", lumps);
	Emit("preview-load", body.GetChars());
}

void MapEntered(const char *marker, const char *name, const char *mapName,
	int spawnFilter, const char *next, const char *secretNext)
{
	FString body;
	body.Format("marker=%s name=%s mapname=%s spawnfilter=%d next=%s secretnext=%s",
		Sanitized(marker).GetChars(), Sanitized(name).GetChars(),
		Sanitized(mapName).GetChars(), spawnFilter,
		Sanitized(next && *next ? next : "-").GetChars(),
		Sanitized(secretNext && *secretNext ? secretNext : "-").GetChars());
	Emit("map-entry", body.GetChars());
}

void CampaignEnded(const char *via)
{
	FString body;
	body.Format("via=%s", Sanitized(via).GetChars());
	Emit("campaign-end", body.GetChars());
}

void Fatal(const char *message)
{
	FString body;
	body.Format("message=%s", Sanitized(message).GetChars());
	Emit("fatal", body.GetChars());
}

void SessionResult(const char *outcome)
{
	// Once only. Several exit paths lead here -- Quit() says so on its way out
	// and the outermost handler says so again -- and a parent that saw two
	// closing events would reasonably wonder which one was the session's.
	static bool said = false;
	if(said)
		return;
	said = true;
	FString body;
	body.Format("outcome=%s", Sanitized(outcome).GetChars());
	Emit("session-result", body.GetChars());
}

}
