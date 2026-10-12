"""UGREEN HiTune headphones with the UG1 control protocol.

Ported from ugreen_core (github.com/dustincorder/ugreenapp), which was worked out
from the official UGREEN Home app. Requests are `AA BB CC <cmd> <len> <data>
<crc16>`, answers `DD EE FF <cmd> <status> <len> <data> <crc16>` with a Modbus
CRC over everything after the header. While the control port is open the headset
also pushes `85 86 87` reports when its state changes, e.g. from its own buttons.
"""

import time

from .. import sdp
from .base import Driver, control, label_of, option

REQUEST = b"\xAA\xBB\xCC"
RESPONSE = b"\xDD\xEE\xFF"
REPORT = b"\x85\x86\x87"

CMD_VERSION = 1
CMD_STATE = 4
CMD_EQ = 5
CMD_DUAL = 6
CMD_GAME = 8
CMD_ANC = 9
CMD_BUTTONS = 10
CMD_LDAC = 11
CMD_PROMPT_LANGUAGE = 12
CMD_SPATIAL = 18
CMD_WEAR = 19

ANSWER_TIMEOUT = 3.0
# A headset busy with a voice prompt rejects commands; the official app retries.
REJECT_RETRY_DELAY = 1.5
QUIET = 0.3
REFRESH_INTERVAL = 60.0

SERIAL_PORT = 0x1101
OTA_SERVICE_PREFIX = "66666666-"

MODELS = {
    # Verified: control port found over SDP (channel 12), off/transparency
    # without a depth nibble, three ANC strengths, configurable ANC button.
    "UGREEN HiTune Max5": {
        "anc": {"off": 0x00, "transparency": 0x02,
                "light": 0xC1, "medium": 0xB1, "strong": 0xA1},
        "levels": True,
        "features": {"ldac", "game", "dual", "eq", "prompt", "buttons"},
    },
    # Values from ugreen_core, where the Max5c was the reference device.
    "UGREEN HiTune Max5c": {
        "anc": {"off": 0xD0, "transparency": 0xD2, "anc": 0xD1},
        "levels": False,
        "channel": 1,
        "features": {"ldac", "game", "dual", "eq", "prompt", "spatial"},
    },
}

EQ_PRESETS = [
    option("original", "Original"), option("classic", "Balanced"), option("bass", "Bass"),
    option("treble", "Treble"), option("pop", "Pop"), option("rock", "Rock"),
    option("jazz", "Jazz"), option("classical", "Classical"), option("electronic", "Electronic"),
]
EQ_VALUES = {"original": 0, "jazz": 1, "electronic": 2, "pop": 3, "classical": 4,
             "rock": 5, "bass": 6, "treble": 7, "classic": 8}
EQ_NAMES = {v: k for k, v in EQ_VALUES.items()}

NOISE_MODES = [option("off", "Off"), option("anc", "Noise cancelling"),
               option("transparency", "Transparency")]
STRENGTHS = [option("light", "Light"), option("medium", "Medium"), option("strong", "Strong")]
# Button action codes as offered by the official app for the HiTune Max5
BUTTON_ACTIONS = [option(0, "None"), option(8, "ANC"), option(7, "Game")]
BUTTON_PRESSES = ["Single press", "Double press", "Triple press", "Long press"]
PROMPT_LANGUAGES = [option("english", "English"), option("chinese", "中文")]


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def encode(command, data):
    body = bytes([command, len(data)]) + bytes(data)
    crc = crc16(body)
    return REQUEST + body + bytes([crc & 0xFF, crc >> 8])


def report_length(command):
    return {1: 3, 8: 0, 9: 2}.get(command, 1)


def anc_mode(value):
    if value in (0, 160, 176, 192, 208):
        return "off"
    if value in (2, 162, 178, 194, 210):
        return "transparency"
    if value in (1, 161, 177, 193, 209):
        return "anc"
    return None


def anc_strength(value):
    if 160 <= value <= 162:
        return "strong"
    if 176 <= value <= 178:
        return "medium"
    if 192 <= value <= 194:
        return "light"
    return None


class FrameParser:
    """Splits the byte stream into responses, pushed reports and reject frames."""

    def __init__(self):
        self.buffer = b""
        self.last_data = 0.0

    def feed(self, data, now):
        self.buffer += data
        self.last_data = now

    def frames(self, now):
        """Yield ("response" | "report" | "reject", bytes)."""
        while self.buffer:
            starts = [i for i in (self.buffer.find(RESPONSE), self.buffer.find(REPORT)) if i >= 0]
            if not starts:
                # Keep a possible partial header
                self.buffer = self.buffer[-2:]
                return
            self.buffer = self.buffer[min(starts):]
            quiet = now - self.last_data >= QUIET
            if self.buffer.startswith(REPORT):
                if len(self.buffer) < 5:
                    return
                total = 5 + report_length(self.buffer[4])
                if len(self.buffer) < total:
                    return
                frame, self.buffer = self.buffer[:total], self.buffer[total:]
                yield "report", frame
                continue
            frame = self._response()
            if frame:
                self.buffer = self.buffer[len(frame):]
                yield "response", frame
                continue
            # `DD EE FF <value> 00 xx xx` shares its start with a response and
            # carries no length, so it only counts once the line is quiet.
            if quiet and len(self.buffer) == 7 and self.buffer[4] == 0:
                frame, self.buffer = self.buffer, b""
                yield "reject", frame
                continue
            if quiet and len(self.buffer) >= 8:
                self.buffer = self.buffer[1:]
                continue
            return

    def _response(self):
        buf = self.buffer
        if len(buf) < 8:
            return None
        # Answers end in two check bytes that do not follow the request CRC (a real
        # Max5 ack fails it), so like ugreen_core rely on the stated length.
        declared = 8 + buf[5]
        if len(buf) >= declared:
            return buf[:declared]
        # Some answers misstate their length; fall back to the first CRC match.
        for total in range(8, min(len(buf), 64) + 1):
            if self._crc_ok(buf[:total]):
                return buf[:total]
        return None

    @staticmethod
    def _crc_ok(frame):
        return crc16(frame[3:-2]) == (frame[-2] | frame[-1] << 8)


class UgreenDriver(Driver):
    settle = 3.0

    def __init__(self, info, model):
        super().__init__(info, model)
        self.spec = MODELS[model]
        self.parser = FrameParser()
        self.state = None
        self.queue = []
        self.pending = None
        self.last_refresh = 0.0
        self.last_strength = "strong"

    @classmethod
    def match(cls, info):
        name = info.get("name", "")
        return name if name in MODELS else None

    def channel(self):
        if "channel" in self.spec:
            return self.spec["channel"]
        records = sdp.search(self.info["address"], SERIAL_PORT)
        for record in records:
            if record["channel"] and not any(c.startswith(OTA_SERVICE_PREFIX) for c in record["classes"]):
                return record["channel"]
        raise OSError("the headset offers no control port")

    # Protocol plumbing

    def connected(self, now):
        self.parser = FrameParser()
        self.queue = []
        self.pending = None
        self.request(CMD_STATE, [0])

    def request(self, command, data, replace=True):
        if replace:
            self.queue = [q for q in self.queue if q[0] != command]
        self.queue.append((command, list(data)))
        self.touch()

    def refresh(self):
        if not any(q[0] == CMD_STATE for q in self.queue):
            self.request(CMD_STATE, [0], replace=False)

    def _pump(self, now):
        if self.pending or not self.queue:
            return
        command, data = self.queue.pop(0)
        self.pending = {"command": command, "data": data, "sent": now, "retry": False, "resend_at": None}
        self.send(encode(command, data))
        if command == CMD_STATE:
            self.last_refresh = now

    def received(self, data, now):
        self.parser.feed(data, now)
        self._drain(now)

    def poll(self, now):
        self._drain(now)
        pending = self.pending
        if pending:
            if pending["resend_at"] and now >= pending["resend_at"]:
                pending.update(resend_at=None, sent=now)
                self.send(encode(pending["command"], pending["data"]))
            elif not pending["resend_at"] and now - pending["sent"] > ANSWER_TIMEOUT:
                self._fail("The headset did not answer")
        elif self.ready and now - self.last_refresh > REFRESH_INTERVAL:
            self.refresh()
        self._pump(now)

    def _drain(self, now):
        for kind, frame in self.parser.frames(now):
            if kind == "report":
                self._report(frame[4], frame[5:])
            elif kind == "reject":
                self._rejected(now)
            else:
                self._response(frame)

    def _rejected(self, now):
        pending = self.pending
        if not pending:
            return
        if pending["retry"]:
            self._fail("The headset is busy, try again")
            return
        pending.update(retry=True, resend_at=now + REJECT_RETRY_DELAY)

    def _fail(self, message):
        failed = self.pending
        self.pending = None
        self.error = message
        self.touch()
        # The optimistic value may now be wrong: read the real state back.
        if failed and failed["command"] != CMD_STATE and self.state is not None:
            self.refresh()

    def _response(self, frame):
        command, status = frame[3], frame[4]
        payload = frame[6:-2]
        if self.pending and self.pending["command"] == command:
            self.pending = None
        if status == 0:
            self.error = "The headset refused the change"
            if command != CMD_STATE:
                self.refresh()
        else:
            self.error = ""
            if command == CMD_STATE:
                self._device_state(payload)
            else:
                self._apply(command, payload)
                # Best effort: the answer echoes one value, the state has them all.
                self.refresh()
        self.touch()

    def _device_state(self, p):
        def at(i, default=0):
            return p[i] if i < len(p) else default
        state = {
            "battery": [b for b in (at(0, 255), at(1, 255), at(2, 255))],
            "anc": at(3),
            "eq": EQ_NAMES.get(at(4), "classic"),
            "dual": at(5) != 0,
            "game": at(6) != 0,
            "ldac": at(7) != 0,
            "buttons": list(p[8:16]) if len(p) >= 16 else [],
            "prompt": "chinese" if at(16) == 1 else "english",
            "spatial": at(20) != 0,
            "wear": at(21) != 0,
        }
        self.state = state
        strength = anc_strength(state["anc"])
        if anc_mode(state["anc"]) == "anc" and strength:
            self.last_strength = strength

    def _apply(self, command, p):
        if self.state is None or not p:
            return
        value = p[0]
        if command == CMD_EQ:
            self.state["eq"] = EQ_NAMES.get(value, self.state["eq"])
        elif command == CMD_ANC:
            self.state["anc"] = value
        elif command == CMD_DUAL:
            self.state["dual"] = value != 0
        elif command == CMD_GAME:
            self.state["game"] = value != 0
        elif command == CMD_LDAC:
            self.state["ldac"] = value != 0
        elif command == CMD_PROMPT_LANGUAGE:
            self.state["prompt"] = "chinese" if value == 1 else "english"

    def _report(self, command, p):
        if self.state is None:
            return
        if command == 1 and len(p) == 3:
            self.state["battery"] = list(p)
        elif command == 2 and p:
            self.state["anc"] = p[0]
        elif command == 4 and p:
            self.state["game"] = p[0] != 0
        elif command == 5 and p:
            self.state["eq"] = EQ_NAMES.get(p[0], self.state["eq"])
        elif command == 10 and p:
            self.state["spatial"] = p[0] != 0
        elif command == 12 and p:
            self.state["dual"] = p[0] != 0
        else:
            return
        self.touch()

    # Model-independent side

    @property
    def ready(self):
        return self.state is not None

    @property
    def busy(self):
        return self.pending is not None or bool(self.queue)

    def has(self, feature):
        return feature in self.spec["features"]

    def _anc_value(self, mode, strength=None):
        table = self.spec["anc"]
        if mode != "anc":
            return table[mode]
        if self.spec["levels"]:
            return table[strength or self.last_strength]
        return table["anc"]

    def set(self, key, value, now):
        if self.state is None:
            return
        self.error = ""
        s = self.state
        if key == "noise" and value in ("off", "anc", "transparency"):
            s["anc"] = self._anc_value(value)
            self.request(CMD_ANC, [s["anc"]])
        elif key == "strength" and value in ("light", "medium", "strong"):
            self.last_strength = value
            s["anc"] = self._anc_value("anc", value)
            self.request(CMD_ANC, [s["anc"]])
        elif key == "eq" and value in EQ_VALUES:
            s["eq"] = value
            self.request(CMD_EQ, [EQ_VALUES[value]])
        elif key == "ldac":
            # Every LDAC write re-establishes the audio link (~8 s of silence).
            if bool(value) != s["ldac"]:
                s["ldac"] = bool(value)
                self.request(CMD_LDAC, [int(bool(value))])
        elif key in ("game", "dual", "spatial", "wear"):
            command = {"game": CMD_GAME, "dual": CMD_DUAL, "spatial": CMD_SPATIAL, "wear": CMD_WEAR}[key]
            s[key] = bool(value)
            self.request(command, [int(bool(value))])
        elif key == "prompt" and value in ("english", "chinese"):
            s["prompt"] = value
            self.request(CMD_PROMPT_LANGUAGE, [1 if value == "chinese" else 0])
        elif key.startswith("button") and len(s["buttons"]) >= 8:
            index = int(key[len("button"):])
            if 0 <= index < 4 and int(value) in (o["value"] for o in BUTTON_ACTIONS):
                s["buttons"][index] = int(value)
                self.request(CMD_BUTTONS, s["buttons"][:8])
        else:
            return
        self.touch()
        self._pump(now)

    def snapshot(self):
        s = self.state
        battery = []
        if s:
            levels = [b for b in s["battery"] if b <= 100]
            if levels:
                battery.append({"id": "level", "label": "", "level": levels[0], "charging": False})
        if not s:
            return {"battery": battery, "controls": [], "settings": [], "summary": [],
                    "active": False, "toggle": None}
        mode = anc_mode(s["anc"]) or "off"
        strength = anc_strength(s["anc"]) or self.last_strength
        ldac = s["ldac"]
        locked = "Unavailable while LDAC is on"
        controls = [
            control("noise", "segmented", "Noise control", mode, NOISE_MODES),
            control("strength", "choice", "Strength", strength, STRENGTHS,
                    visible=self.spec["levels"] and mode == "anc"),
        ]
        if self.has("ldac"):
            controls.append(control("ldac", "toggle", "LDAC", ldac,
                                    description="High-resolution audio. Switching reconnects the audio for a few seconds."))
        if self.has("game"):
            controls.append(control("game", "toggle", "Game mode", s["game"] and not ldac,
                                    description=locked if ldac else "Lower audio latency", enabled=not ldac))
        if self.has("dual"):
            controls.append(control("dual", "toggle", "Multipoint", s["dual"] and not ldac,
                                    description=locked if ldac else "Stay connected to two devices at once",
                                    enabled=not ldac))
        if self.has("spatial"):
            controls.append(control("spatial", "toggle", "Spatial audio", s["spatial"]))
        if self.has("wear"):
            controls.append(control("wear", "toggle", "Wear detection", s["wear"]))
        if self.has("eq"):
            controls.append(control("eq", "list", "Equalizer", s["eq"], EQ_PRESETS))

        settings = []
        if self.has("prompt"):
            settings.append(control("prompt", "list", "Voice prompts", s["prompt"], PROMPT_LANGUAGES,
                                    description="Language of the announcements the headset plays"))
        if self.has("buttons") and len(s["buttons"]) >= 8:
            for index, press in enumerate(BUTTON_PRESSES):
                settings.append(control("button%d" % index, "choice", press, s["buttons"][index], BUTTON_ACTIONS,
                                        section="ANC button" if index == 0 else "",
                                        section_description="What the noise-control button on the headset does"
                                        if index == 0 else ""))

        summary = [label_of(NOISE_MODES, mode)]
        if mode == "anc" and self.spec["levels"]:
            summary.append(label_of(STRENGTHS, strength))
        return {
            "battery": battery,
            "controls": controls,
            "settings": settings,
            "summary": summary,
            "active": mode != "off",
            "toggle": {"id": "noise", "on": "anc", "off": "off", "value": mode},
        }
