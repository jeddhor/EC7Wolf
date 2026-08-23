#!/usr/bin/env python3
"""Fire malformed, truncated and oversized packets at an EC7Wolf socket.

Not a fuzzer in the coverage-guided sense: a fixed, reproducible battery of the
shapes that a socket open to the internet actually has to survive. Every case
is one this port's own packet handling could have been fooled by before M7 --
the start packet in particular ends in an array whose length is declared by a
byte inside it, so "at least sizeof(struct)" was never the size that mattered.

Deliberately fixed rather than random: a gate that fails one run in fifty on an
input nobody can reproduce is worse than no gate.

Usage: netfuzz.py HOST PORT [--rounds N]
"""

import argparse
import os
import socket
import struct
import sys

# From the NET_* enum in wl_net.cpp, in order.
(NET_RequestConnection, NET_ConnectionStart, NET_Ack, NET_NewGame,
 NET_TicCmd, NET_BlockPlaysim, NET_DebugCmd, NET_EndGame, NET_InAck) = range(9)

MAXPLAYERS = 11


def start_packet(player=0, players=2, mode=0, delay=6, frags=0, seed=1,
                 clients=1):
    """A well-formed start packet, or as close as the arguments allow.

    Layout: type, playerNumber, numPlayers, gameMode, ticDelay, then the
    DWORD rngseed (which the compiler aligns), then numPlayers-1 clients of
    {DWORD host, WORD port}.
    """
    head = struct.pack("<BBBBB", NET_ConnectionStart, player, players, mode, delay)
    head += struct.pack("<B", frags)
    head += b"\x00\x00"                      # padding up to the DWORD
    head += struct.pack("<I", seed)
    body = b"".join(struct.pack("<IH2x", 0x0100007F, 5029 + i)
                    for i in range(clients))
    return head + body


def cases():
    """(name, payload) for every shot fired, in a fixed order."""
    out = []

    # Nothing at all, and one byte of nothing in particular.
    out.append(("empty", b""))
    out.append(("one stray byte", b"\x00"))

    # Every packet type, truncated to a single byte: the type is right and
    # there is no body behind it.
    for t in range(NET_InAck + 1):
        out.append(("type %d with no body" % t, bytes([t])))

    # A type byte that is not a type.
    out.append(("unknown type 200", bytes([200]) + b"\x00" * 64))

    # Start packets that lie about their size. numPlayers says there are more
    # clients behind the header than the datagram contains.
    out.append(("start claiming 11 players, no client array",
                start_packet(players=MAXPLAYERS, clients=0)))
    out.append(("start claiming 255 players",
                start_packet(players=255, clients=0)))
    out.append(("start claiming 255 players with one client",
                start_packet(players=255, clients=1)))

    # A player number outside the game it describes.
    out.append(("start with playerNumber 254 of 2",
                start_packet(player=254, players=2)))
    out.append(("start with playerNumber == numPlayers",
                start_packet(player=2, players=2)))

    # Values outside their enums and beyond their ranges.
    out.append(("start with gameMode 200", start_packet(mode=200)))
    out.append(("start with ticDelay 255", start_packet(delay=255)))
    out.append(("start with zero players", start_packet(players=0, clients=0)))

    # Oversized: far more than the game will ever send.
    out.append(("start with 60kB of trailing rubbish",
                start_packet() + os.urandom(60000)))
    out.append(("64kB of noise", os.urandom(65000)))

    # A debug command whose string argument fills its field with no terminator.
    debug = struct.pack("<Biii", NET_DebugCmd, 0, 0, 0) + b"A" * 256
    out.append(("debug command with an unterminated string", debug))
    out.append(("debug command truncated inside its string",
                struct.pack("<Biii", NET_DebugCmd, 0, 0, 0) + b"A" * 8))

    # Tic commands with nothing sensible in them.
    out.append(("tic command of zeros", bytes([NET_TicCmd]) + b"\x00" * 200))
    out.append(("tic command of 0xFF", bytes([NET_TicCmd]) + b"\xFF" * 200))

    # Acks for things nobody asked about.
    out.append(("ack for an unknown type",
                struct.pack("<BBi", NET_Ack, 200, -1)))
    out.append(("end game from a stranger", bytes([NET_EndGame]) + b"\x00" * 8))

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("port", type=int)
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--from-port", type=int, default=0,
                    help="bind this local port, so the target sees the "
                         "packets as coming from the host it dialled")
    ap.add_argument("--no-requests", action="store_true",
                    help="leave out anything a host would read as a genuine "
                         "connection request; a bare 0x00 byte is one")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.2)
    if args.from_port:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", args.from_port))

    sent = 0
    for _ in range(args.rounds):
        for name, payload in cases():
            # A one-byte 0x00 is NET_RequestConnection, and a host waiting for
            # players will read it as somebody asking to join -- which is what
            # hosting means, not a fault. Left out when the target is a host
            # still expecting players.
            if args.no_requests and payload[:1] == bytes([NET_RequestConnection]):
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
