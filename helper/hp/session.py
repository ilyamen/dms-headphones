"""Keeps the control ports of all connected supported headsets open and reports
their state.

The plugin tells the session which Bluetooth devices are connected; every one a
driver handles gets a link. Lookups and connects run on a worker thread, so
commands from the plugin are never stuck behind a slow headset.
"""

import concurrent.futures
import sys
import time

from . import bluez, link
from .drivers import find_driver

# Seconds before reconnect attempts: quick at first (an LDAC switch drops the
# port for a few seconds), then backing off.
RETRY_DELAYS = [2, 3, 5, 10, 20, 30]


def log(*parts):
    print("headphonesd:", *parts, file=sys.stderr, flush=True)


class Link:
    """One headset: its driver and its control port."""

    def __init__(self, address, driver, now):
        self.address = address
        self.driver = driver
        self.sock = None
        self.pending_connect = None
        self.status = "connecting"
        self.error = ""
        self.failures = 0
        self.next_attempt = now + driver.settle
        self.outgoing = b""

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self.outgoing = b""

    def state(self):
        info = self.driver.info
        status = "ready" if self.sock and self.driver.ready else self.status
        state = {
            "device": {"address": self.address, "name": info.get("alias") or info.get("name", ""),
                       "model": self.driver.model, "icon": self.driver.icon},
            "status": "connecting" if status == "connected" else status,
            "error": self.driver.error or self.error,
            "busy": self.driver.busy,
        }
        state.update(self.driver.snapshot())
        return state


class Session:
    def __init__(self, emit, probe=bluez.device_info, connect=link.open_rfcomm, debug=False):
        self.emit = emit
        self.probe = probe
        self.connect = connect
        self.debug = debug
        self.worker = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.candidates = []
        self.probed = {}
        self.links = {}
        self.last_emitted = None

    # Commands from the plugin

    def handle(self, message, now):
        command = message.get("cmd")
        if command == "devices":
            self.set_devices(message.get("addresses") or [], now)
        elif command in ("set", "refresh"):
            target = self.links.get(str(message.get("address", "")).upper())
            for entry in [target] if target else self.links.values():
                if not entry.sock:
                    continue
                if command == "set":
                    entry.driver.set(str(message.get("id", "")), message.get("value"), now)
                else:
                    entry.driver.refresh()
                self.flush(entry)
        self.report()

    def set_devices(self, addresses, now):
        self.candidates = [str(a).upper() for a in addresses]
        for address in list(self.probed):
            if address not in self.candidates:
                del self.probed[address]
        for address in list(self.links):
            if address not in self.candidates:
                self.links.pop(address).close()
        for address in self.candidates:
            if address in self.links:
                continue
            if address not in self.probed:
                try:
                    info = self.probe(address)
                except Exception as error:  # busctl missing, BlueZ restarting, ...
                    log("cannot read", address, error)
                    info = None
                driver, model = find_driver(info) if info else (None, None)
                self.probed[address] = (driver, model, info) if driver else None
            entry = self.probed[address]
            if entry:
                driver, model, info = entry
                self.links[address] = Link(address, driver(info, model), now)

    # Connection

    def sockets(self):
        return {entry.sock: entry for entry in self.links.values() if entry.sock}

    def _open(self, driver, address):
        return self.connect(address, driver.channel())

    def lost(self, entry, now, reason):
        log(entry.address, "control port closed:", reason)
        entry.close()
        entry.status = "connecting"
        entry.next_attempt = now + RETRY_DELAYS[0]

    def tick(self, now):
        for entry in list(self.links.values()):
            self._tick(entry, now)
        self.report()

    def _tick(self, entry, now):
        if entry.pending_connect and entry.pending_connect.done():
            future, entry.pending_connect = entry.pending_connect, None
            try:
                sock = future.result()
            except Exception as error:
                entry.failures += 1
                entry.error = "Cannot reach the headset"
                entry.status = "error" if entry.failures >= 3 else "connecting"
                entry.next_attempt = now + RETRY_DELAYS[min(entry.failures, len(RETRY_DELAYS)) - 1]
                log(entry.address, "connect failed:", error)
            else:
                if self.links.get(entry.address) is entry:
                    entry.sock = sock
                    entry.failures = 0
                    entry.error = ""
                    entry.status = "connected"
                    entry.driver.connected(now)
                else:
                    sock.close()
        if not entry.sock and not entry.pending_connect and now >= entry.next_attempt:
            entry.pending_connect = self.worker.submit(self._open, entry.driver, entry.address)
        if entry.sock:
            entry.driver.poll(now)
            self.flush(entry)

    def received(self, entry, data, now):
        if self.debug:
            log(entry.address, "<<", data.hex())
        entry.driver.received(data, now)
        self.flush(entry)

    def flush(self, entry):
        if not entry.sock:
            return
        for frame in entry.driver.take_output():
            if self.debug:
                log(entry.address, ">>", frame.hex())
            entry.outgoing += frame
        while entry.outgoing:
            try:
                sent = entry.sock.send(entry.outgoing)
            except BlockingIOError:
                return
            except OSError as error:
                self.lost(entry, time.monotonic(), error)
                return
            entry.outgoing = entry.outgoing[sent:]

    def close(self):
        for entry in self.links.values():
            entry.close()

    # State for the plugin

    def state(self):
        """Headsets in the order the plugin listed them (most recent first)."""
        ordered = [self.links[a] for a in self.candidates if a in self.links]
        return {"type": "state", "devices": [entry.state() for entry in ordered]}

    def report(self):
        state = self.state()
        if state != self.last_emitted:
            self.last_emitted = state
            self.emit(state)
