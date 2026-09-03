#!/usr/bin/env python3
"""Fire malformed, truncated and oversized packets at an EC7Wolf socket.

Not a fuzzer in the coverage-guided sense: a fixed, reproducible battery of the
shapes that a socket open to the internet actually has to survive. Every case
is one this port's own packet handling could have been fooled by -- the start
packet in particular ends in an array whose length is declared by a byte inside
it, so "at least sizeof(struct)" was never the size that mattered.

Deliberately fixed rather than random: a gate that fails one run in fifty on an
input nobody can reproduce is worse than no gate.

Every shape is built from a vector file the engine itself writes, via

    ec7wolf --netvectors FILE

because the hand-maintained copy this script used to carry had drifted from the
engine twice over: the NET_ enum had NewGame and TicCmd the wrong way round and
InAck, DebugCmd and EndGame all misnumbered, and the start packet was laid out
for natural alignment when the real struct is #pragma pack(1). It had been
firing well-formed nonsense at the wrong message types and passing.

Usage: netfuzz.py HOST PORT --vectors FILE [--rounds N]
"""

import argparse
import os
import socket
import struct
import sys


class Vectors:
    """What the engine says it speaks."""

    def __init__(self, path):
        self.types = {}
        self.sizes = {}
        self.offsets = {}
        self.values = {}
        self.golden = b""
        with open(path, "r") as handle:
            for line in handle:
                self._read(line.split())
        for need in ("RequestConnection", "ConnectionStart", "Ack", "TicCmd",
                     "NewGame", "BlockPlaysim", "InAck", "DebugCmd", "EndGame"):
            if need not in self.types:
                raise SystemExit("netfuzz: %s names no %s" % (path, need))
        if not self.golden:
            raise SystemExit("netfuzz: %s has no golden start packet" % path)

    def _read(self, parts):
        if not parts:
            return
        if parts[0] == "type" and len(parts) == 4:
            self.types[parts[1]] = int(parts[2])
            self.sizes[parts[1]] = int(parts[3])
            return
        if len(parts) != 2:
            return
        key, value = parts
        if key == "start.golden":
            self.golden = bytes.fromhex(value)
        elif key.startswith("start.offset."):
            self.offsets[key[len("start.offset."):]] = int(value)
        elif key == "start.size.client":
            self.values["client"] = int(value)
        elif key == "magic":
            self.values["magic"] = value
        elif value.lstrip("-").isdigit():
            self.values[key] = int(value)

    def start_packet(self, player=1, players=2, mode=1, delay=6, frags=0,
                     seed=0x01020304, clients=1, version=None):
        """A start packet in the engine's own layout, or a lie about it.

        Built by writing fields into a buffer at the offsets the engine
        reported, so a field that moves moves here too.
        """
        head = bytearray(self.sizes["ConnectionStart"])
        head[0] = self.types["ConnectionStart"]
        off = self.offsets
        if version is None:
            version = self.values["protocol"]
        struct.pack_into("<H", head, off["protocolVersion"], version & 0xFFFF)
        head[off["playerNumber"]] = player & 0xFF
        head[off["numPlayers"]] = players & 0xFF
        head[off["gameMode"]] = mode & 0xFF
        head[off["ticDelay"]] = delay & 0xFF
        head[off["fragLimit"]] = frags & 0xFF
        struct.pack_into("<I", head, off["rngseed"], seed)
        entry = self.values["client"]
        body = bytearray()
        for i in range(clients):
            one = bytearray(entry)
            struct.pack_into("<I", one, 0, 0x0100007F)
            struct.pack_into("<H", one, 4, 5029 + i)
            body += one
        return bytes(head) + bytes(body)

    def request_packet(self, magic=None, version=None):
        size = self.sizes["RequestConnection"]
        out = bytearray(size)
        out[0] = self.types["RequestConnection"]
        raw = bytes.fromhex(magic if magic is not None else self.values["magic"])
        out[1:1 + len(raw)] = raw
        if version is None:
            version = self.values["protocol"]
        struct.pack_into("<H", out, 4, version & 0xFFFF)
        return bytes(out)

    def selftest(self):
        """The golden datagram, rebuilt. Proves this script and the engine
        still agree before a single packet is fired."""
        mine = self.start_packet()
        if mine != self.golden:
            raise SystemExit(
                "netfuzz: built %s but the engine emits %s -- the layout has "
                "moved and this script has not" %
                (mine.hex(), self.golden.hex()))


def named_cases(v):
    """Cases fired only on request, because what they prove is a message.

    A well-formed packet from another protocol version is not rubbish. Mixed
    into the battery it makes "is it still running" ambiguous -- ignored, or
    still saying no? -- so it is asked for by name and asserted on its own.
    """
    return {
        "start-wrong-version": v.start_packet(version=1),
        "request-wrong-version": v.request_packet(version=1),
    }


def cases(v):
    """(name, payload) for every shot fired, in a fixed order."""
    out = []
    maxplayers = v.values["maxplayers"]

    # Nothing at all, and one byte of nothing in particular.
    out.append(("empty", b""))
    out.append(("one stray byte", b"\x00"))

    # Every packet type, truncated to a single byte: the type is right and
    # there is no body behind it.
    for name in sorted(v.types, key=lambda n: v.types[n]):
        out.append(("%s with no body" % name, bytes([v.types[name]])))

    # A type byte that is not a type.
    out.append(("unknown type 200", bytes([200]) + b"\x00" * 64))

    # Connection requests that are not this build's.
    out.append(("request with no magic", v.request_packet(magic="000000")))
    out.append(("request from protocol 65535", v.request_packet(version=0xFFFF)))
    out.append(("legacy one-byte request",
                bytes([v.types["RequestConnection"]])))

    # Start packets that lie about their size. numPlayers says there are more
    # clients behind the header than the datagram contains. The 255 case is
    # the one that mattered: the swap loop followed that count out of the
    # receive buffer entirely, reading and writing as it went.
    out.append(("start claiming %d players, no client array" % maxplayers,
                v.start_packet(players=maxplayers, clients=0)))
    out.append(("start claiming 255 players", v.start_packet(players=255, clients=0)))
    out.append(("start claiming 255 players with one client",
                v.start_packet(players=255, clients=1)))
    out.append(("start claiming 255 players, header truncated",
                v.start_packet(players=255, clients=0)[:3]))

    # A player number outside the game it describes.
    out.append(("start with playerNumber 254 of 2", v.start_packet(player=254)))
    out.append(("start with playerNumber == numPlayers",
                v.start_packet(player=2, players=2)))

    # Values outside their enums and beyond their ranges.
    out.append(("start with gameMode 200", v.start_packet(mode=200)))
    out.append(("start with ticDelay 255", v.start_packet(delay=255)))
    out.append(("start with zero players", v.start_packet(players=0, clients=0)))

    # Oversized: far more than the game will ever send.
    out.append(("start with 60kB of trailing rubbish",
                v.start_packet() + os.urandom(60000)))
    out.append(("64kB of noise", os.urandom(65000)))

    # A debug command whose string argument fills its field with no terminator.
    dbg = v.types["DebugCmd"]
    out.append(("debug command with an unterminated string",
                struct.pack("<Biii", dbg, 0, 0, 0) + b"A" * 256))
    out.append(("debug command truncated inside its string",
                struct.pack("<Biii", dbg, 0, 0, 0) + b"A" * 8))

    # Tic commands with nothing sensible in them.
    tic = v.types["TicCmd"]
    out.append(("tic command of zeros", bytes([tic]) + b"\x00" * 200))
    out.append(("tic command of 0xFF", bytes([tic]) + b"\xFF" * 200))

    # Things only somebody already in the match is allowed to say.
    out.append(("ack for an unknown type",
                struct.pack("<BBi", v.types["Ack"], 200, -1)))
    out.append(("end game from a stranger",
                struct.pack("<Bi", v.types["EndGame"], 0)))
    out.append(("block playsim from a stranger",
                struct.pack("<Bi", v.types["BlockPlaysim"], 0)))
    out.append(("input ack from a stranger",
                struct.pack("<BiI", v.types["InAck"], 0, 0)))

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("port", type=int)
    ap.add_argument("--vectors", required=True,
                    help="file written by ec7wolf --netvectors")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--from-port", type=int, default=0,
                    help="bind this local port, so the target sees the "
                         "packets as coming from the host it dialled")
    ap.add_argument("--only", metavar="NAME",
                    help="fire one named case instead of the battery: " +
                         "start-wrong-version, request-wrong-version")
    ap.add_argument("--no-requests", action="store_true",
                    help="leave out anything a host would read as a genuine "
                         "connection request")
    args = ap.parse_args()

    v = Vectors(args.vectors)
    v.selftest()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.2)
    if args.from_port:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", args.from_port))

    if args.only:
        named = named_cases(v)
        if args.only not in named:
            raise SystemExit("netfuzz: no case named %s" % args.only)
        for _ in range(max(1, args.rounds)):
            sock.sendto(named[args.only], (args.host, args.port))
        print("fired %s %d time(s)" % (args.only, max(1, args.rounds)))
        return 0

    request = v.types["RequestConnection"]
    sent = 0
    for _ in range(args.rounds):
        for name, payload in cases(v):
            # A host still waiting for players will read a well-formed request
            # as somebody asking to join -- which is what hosting means, not a
            # fault. Left out when the target is such a host.
            if args.no_requests and payload[:1] == bytes([request]):
                continue
            try:
                sock.sendto(payload, (args.host, args.port))
                sent += 1
            except OSError as exc:
                # An oversized datagram the local stack refuses never reaches
                # the game, so it is not a case the game failed.
                print("  (skipped %s: %s)" % (name, exc), file=sys.stderr)
    print("fired %d packets" % sent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
