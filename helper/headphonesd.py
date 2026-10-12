#!/usr/bin/env python3
"""Headset control helper for the DMS Headphones plugin.

Reads JSON commands from stdin, one per line:
    {"cmd": "devices", "addresses": ["AA:BB:...", ...]}   connected devices, newest first
    {"cmd": "set", "address": "AA:BB:...", "id": "noise", "value": "anc"}
    {"cmd": "refresh", "address": "AA:BB:..."}           address optional: all headsets
and prints the state of every connected supported headset as JSON lines on stdout:
    {"type": "state", "devices": [{"device": {...}, "status", "controls", ...}, ...]}
It exits when stdin closes, and with its parent (DMS). Needs only Python and `busctl`.

    headphonesd.py [--debug]     --debug logs the raw traffic to stderr
"""

import ctypes
import json
import os
import select
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hp.session import Session, log  # noqa: E402

PR_SET_PDEATHSIG = 1
TICK = 0.2


def die_with_parent():
    try:
        ctypes.CDLL(None).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except (OSError, AttributeError):
        pass


def emit(state):
    sys.stdout.write(json.dumps(state, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main():
    die_with_parent()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    session = Session(emit, debug="--debug" in sys.argv)
    session.report()
    stdin = sys.stdin.buffer
    pending = b""
    while True:
        sockets = session.sockets()
        readable, _, _ = select.select([stdin] + list(sockets), [], [], TICK)
        now = time.monotonic()
        if stdin in readable:
            chunk = os.read(stdin.fileno(), 65536)
            if not chunk:
                break
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    log("ignoring", line[:80])
                    continue
                session.handle(message, now)
        for sock, entry in sockets.items():
            if sock not in readable or entry.sock is not sock:
                continue
            try:
                data = sock.recv(4096)
            except BlockingIOError:
                continue
            except OSError as error:
                session.lost(entry, now, error)
                continue
            if data:
                session.received(entry, data, now)
            else:
                session.lost(entry, now, "closed by the headset")
        session.tick(now)
    session.close()


if __name__ == "__main__":
    main()
