#!/usr/bin/env python3
"""A UDP relay that makes a loopback link behave like the internet.

Multiplayer here is lockstep: every tic waits for every player's command. On a
loopback that costs nothing, so a test on one machine says nothing at all about
whether the game is playable between two houses. This sits in the middle and
adds what the internet adds -- latency, jitter, and lost packets.

Userspace on purpose. `tc netem` does this properly and needs root, which a
gate should not, and which CI will not give it.

    netdelay.py --listen 5040 --forward 127.0.0.1:5029 --delay 40 --loss 2

Anything arriving on the listening port is forwarded to the far side after the
delay; anything the far side sends back returns to whoever last spoke. Two
parties only, which is all a host-and-client test needs.
"""

from __future__ import annotations

import argparse
import random
import selectors
import socket
import sys
import threading
import time


class Relay:
    def __init__(self, listen: int, forward: tuple[str, int], delay_ms: float,
                 jitter_ms: float, loss: float, seed: int,
                 duplicate: float = 0.0):
        self.forward = forward
        self.delay = delay_ms / 1000.0
        self.jitter = jitter_ms / 1000.0
        self.loss = loss / 100.0
        # Duplication is the impairment a lockstep game is least likely to be
        # tested against and most likely to get wrong: a resend that arrives
        # twice has to be idempotent, and a receiver that stores both copies
        # fills its ring with the same sequence.
        self.duplicate = duplicate / 100.0
        self.random = random.Random(seed)

        self.near = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.near.bind(("127.0.0.1", listen))
        self.far = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.far.bind(("127.0.0.1", 0))

        self.client_address: tuple[str, int] | None = None
        self.counts = {"to_far": 0, "to_near": 0, "dropped": 0,
                       "duplicated": 0}
        self.lock = threading.Lock()

    def _later(self, send) -> None:
        """Deliver after the delay, without holding up anything else."""
        with self.lock:
            if self.random.random() < self.loss:
                self.counts["dropped"] += 1
                return
            wait = self.delay
            if self.jitter:
                wait += self.random.uniform(-self.jitter, self.jitter)
            # A second copy on a timer of its own, so it can land either side
            # of the first. Jitter already reorders; this adds the case where
            # the same sequence arrives twice.
            again = self.random.random() < self.duplicate
            extra = 0.0
            if again:
                self.counts["duplicated"] += 1
                extra = max(0.0, wait + self.random.uniform(0.0, 0.004))
        timer = threading.Timer(max(0.0, wait), send)
        timer.daemon = True
        timer.start()
        if again:
            twin = threading.Timer(extra, send)
            twin.daemon = True
            twin.start()

    def run(self) -> None:
        selector = selectors.DefaultSelector()
        selector.register(self.near, selectors.EVENT_READ, "near")
        selector.register(self.far, selectors.EVENT_READ, "far")

        while True:
            for key, _mask in selector.select(timeout=1.0):
                if key.data == "near":
                    data, address = self.near.recvfrom(65535)
                    self.client_address = address

                    def send(payload=data):
                        self.far.sendto(payload, self.forward)
                        with self.lock:
                            self.counts["to_far"] += 1
                    self._later(send)
                else:
                    data, _address = self.far.recvfrom(65535)
                    if self.client_address is None:
                        continue

                    def send(payload=data, to=self.client_address):
                        self.near.sendto(payload, to)
                        with self.lock:
                            self.counts["to_near"] += 1
                    self._later(send)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--listen", type=int, required=True)
    parser.add_argument("--forward", required=True, metavar="HOST:PORT")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="one-way delay in ms; round trip is twice this")
    parser.add_argument("--jitter", type=float, default=0.0, metavar="MS")
    parser.add_argument("--loss", type=float, default=0.0, metavar="PERCENT")
    parser.add_argument("--duplicate", type=float, default=0.0,
                        metavar="PERCENT", help="send this share twice")
    parser.add_argument("--seed", type=int, default=1,
                        help="so a run that fails can be repeated")
    arguments = parser.parse_args()

    host, port = arguments.forward.rsplit(":", 1)
    relay = Relay(arguments.listen, (host, int(port)), arguments.delay,
                  arguments.jitter, arguments.loss, arguments.seed,
                  arguments.duplicate)
    print(f"relay :{arguments.listen} -> {host}:{port}  "
          f"delay {arguments.delay}ms one way, jitter {arguments.jitter}ms, "
          f"loss {arguments.loss}%, duplicate {arguments.duplicate}%",
          flush=True)
    try:
        relay.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
