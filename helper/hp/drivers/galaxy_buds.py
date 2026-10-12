"""Samsung Galaxy Buds with the second-generation SPP protocol.

Message layout and field offsets follow GalaxyBudsClient
(github.com/timschneeb/GalaxyBudsClient) and BudsLink (github.com/maniacx/BudsLink),
which reverse-engineered the Galaxy Wearable app. A message is
`FD <size:2 LE> <id> <payload> <crc16:2 LE> DD`, where size counts the id, payload
and CRC (CRC-16/XMODEM over id and payload). The buds push a full status when the
port opens and short updates whenever something changes.
"""

from .. import sdp
from .base import Driver, control, label_of, option

SOM = 0xFD
EOM = 0xDD
SPP_SERVICE = "2e73a4ad-332d-41fc-90e2-16bef06523f2"
# The last four hex digits of this service UUID are the model and colour id.
MODEL_ID_PREFIX = "d908aab5-7a90-4cbe-8641-86a553db"

MSG_ACK = 0x42
MSG_STATUS = 0x60
MSG_EXTENDED_STATUS = 0x61
MSG_NOISE_CONTROLS_UPDATE = 0x77
MSG_NOISE_CONTROLS = 0x78
MSG_AMBIENT_VOLUME = 0x84
MSG_GAME_MODE = 0x85  # "adjust sound sync"
MSG_EQUALIZER = 0x86
MSG_MANAGER_INFO = 0x88
MSG_LOCK_TOUCHPAD = 0x90
MSG_TOUCHPAD_OPTION = 0x92
MSG_ANC_WITH_ONE_EARBUD = 0x6F
MSG_SEAMLESS_CONNECTION = 0xAF

MODELS = {
    # The open-fit Buds3 have no ambient mode: their noise-control cycle byte
    # only ever lists off and ANC. Gestures are pinches on the stem plus a swipe
    # for volume.
    "Galaxy Buds3": {
        "ids": {0x014D, 0x014E},
        "name": "buds3",
        "noise": ["off", "anc"],
        "ambient_levels": 3,
        "swipe": True,
    },
}

NOISE_LABELS = {"off": "Off", "anc": "Noise cancelling", "ambient": "Ambient sound", "adaptive": "Adaptive"}
NOISE_VALUES = {"off": 0, "anc": 1, "ambient": 2, "adaptive": 3}
NOISE_NAMES = {v: k for k, v in NOISE_VALUES.items()}
AMBIENT_LEVELS = [option(0, "Low"), option(1, "Medium"), option(2, "High")]
EQ_PRESETS = [option("off", "Normal"), option("bass", "Bass boost"), option("soft", "Soft"),
              option("dynamic", "Dynamic"), option("clear", "Clear"), option("treble", "Treble boost")]
EQ_VALUES = {"off": 0, "bass": 1, "soft": 2, "dynamic": 3, "clear": 4, "treble": 5}
EQ_NAMES = {v: k for k, v in EQ_VALUES.items()}
HOLD_ACTIONS = [option(1, "Voice assistant"), option(2, "Noise control"), option(3, "Volume")]
# Bits of the touch byte: bit 7 enables the touchpad, the rest single gestures
GESTURES = [("pinch", 3, "Pinch"), ("doublePinch", 2, "Double pinch"),
            ("triplePinch", 1, "Triple pinch"), ("pinchHold", 0, "Pinch and hold"),
            ("swipe", 6, "Swipe for volume")]


def _crc_table():
    table = []
    for byte in range(256):
        crc = byte << 8
        for _ in range(8):
            crc = (crc << 1) ^ 0x1021 if crc & 0x8000 else crc << 1
        table.append(crc & 0xFFFF)
    return table


CRC_TABLE = _crc_table()


def crc16(data):
    crc = 0
    for byte in data:
        crc = (CRC_TABLE[((crc >> 8) ^ byte) & 0xFF] ^ (crc << 8)) & 0xFFFF
    return crc


def encode(message_id, payload=()):
    body = bytes([message_id]) + bytes(payload)
    size = len(body) + 2
    crc = crc16(body)
    return bytes([SOM, size & 0xFF, size >> 8]) + body + bytes([crc & 0xFF, crc >> 8, EOM])


def decode_stream(buffer):
    """Split complete messages off `buffer`; returns ([(id, payload)], rest)."""
    messages = []
    while True:
        start = buffer.find(bytes([SOM]))
        if start < 0:
            return messages, b""
        buffer = buffer[start:]
        if len(buffer) < 3:
            return messages, buffer
        size = (buffer[1] | buffer[2] << 8) & 0x3FF
        total = 4 + size
        if size < 3:
            buffer = buffer[1:]
            continue
        if len(buffer) < total:
            return messages, buffer
        frame = buffer[:total]
        body = frame[3:3 + size - 2]
        crc = frame[1 + size] | frame[2 + size] << 8
        if frame[-1] == EOM and crc16(body) == crc:
            messages.append((body[0], body[1:]))
            buffer = buffer[total:]
        else:
            buffer = buffer[1:]


def model_id(uuids):
    for value in uuids:
        if value.startswith(MODEL_ID_PREFIX):
            try:
                return int(value[len(MODEL_ID_PREFIX):], 16)
            except ValueError:
                return None
    return None


class GalaxyBudsDriver(Driver):
    icon = "earbuds"
    settle = 1.0

    def __init__(self, info, model):
        super().__init__(info, model)
        self.spec = MODELS[model]
        self.buffer = b""
        self.state = None
        self.greeted = False

    @classmethod
    def match(cls, info):
        uuids = info.get("uuids", [])
        if SPP_SERVICE not in uuids:
            return None
        found = model_id(uuids)
        for name, spec in MODELS.items():
            if found in spec["ids"]:
                return name
        # Older BlueZ caches may lack the model UUID; fall back to the name
        # (users often rename the buds, but the model stays in front).
        name = info.get("name", "").lower()
        for model, spec in MODELS.items():
            if name.startswith(spec["name"] + " ") or name == spec["name"] or \
                    name.startswith("galaxy " + spec["name"]):
                if "pro" not in name and " fe" not in name:
                    return model
        return None

    def channel(self):
        for record in sdp.search(self.info["address"], SPP_SERVICE):
            if record["channel"]:
                return record["channel"]
        raise OSError("the buds offer no control port")

    def connected(self, now):
        self.buffer = b""
        self.greeted = False
        self.send(encode(MSG_EXTENDED_STATUS))

    def received(self, data, now):
        messages, self.buffer = decode_stream(self.buffer + data)
        for message_id, payload in messages:
            self._handle(message_id, payload)

    def refresh(self):
        self.send(encode(MSG_EXTENDED_STATUS))

    def _handle(self, message_id, p):
        if message_id == MSG_EXTENDED_STATUS:
            self._extended_status(p)
            if not self.greeted:
                # Tells the buds a Samsung client is attached; until then some
                # firmwares hold back updates.
                self.greeted = True
                self.send(encode(MSG_MANAGER_INFO, [1, 1, 34]))
        elif self.state is None:
            return
        elif message_id == MSG_STATUS and len(p) >= 7:
            self.state.update(left=p[1], right=p[2], placement=p[5], case=p[6])
            if len(p) >= 8:
                self.state["charging"] = p[7]
        elif message_id == MSG_NOISE_CONTROLS_UPDATE and p:
            self.state["noise"] = NOISE_NAMES.get(p[0], self.state["noise"])
        elif message_id == MSG_AMBIENT_VOLUME and p:
            self.state["ambient"] = p[0]
        elif message_id == MSG_TOUCHPAD_OPTION and len(p) >= 2:
            self.state["hold"] = [p[0], p[1]]
        elif message_id == MSG_ACK and len(p) >= 2:
            self._acknowledged(p[0], p[1:])
        else:
            return
        self.touch()

    def _acknowledged(self, message_id, v):
        """The buds confirm a change with the value they actually applied (an
        unsupported noise mode comes back as off), so take it as the truth. They
        ignore repeated full status requests, so this is how changes are verified."""
        s = self.state
        if message_id == MSG_NOISE_CONTROLS:
            s["noise"] = NOISE_NAMES.get(v[0], "off")
        elif message_id == MSG_GAME_MODE:
            s["game"] = v[0] == 1
        elif message_id == MSG_EQUALIZER:
            s["eq"] = EQ_NAMES.get(v[0], s["eq"])
        elif message_id == MSG_AMBIENT_VOLUME:
            s["ambient"] = v[0]
        elif message_id == MSG_LOCK_TOUCHPAD and len(v) >= 5:
            # Same order as the request; models without the call gestures or the
            # swipe echo fewer bytes, those bits keep their current value.
            kept = [s["touch"] >> 4 & 1, s["touch"] >> 5 & 1, s["touch"] >> 6 & 1]
            bits = (list(v[:8]) + kept[min(len(v), 8) - 5:])[:8]
            on, single, double, triple, hold, call_double, call_hold, swipe = (b & 1 for b in bits)
            s["touch"] = (on << 7 | swipe << 6 | call_hold << 5 | call_double << 4 |
                          single << 3 | double << 2 | triple << 1 | hold)
        elif message_id == MSG_TOUCHPAD_OPTION and len(v) >= 2:
            s["hold"] = [v[0], v[1]]
        elif message_id == MSG_ANC_WITH_ONE_EARBUD:
            s["oneEarbud"] = v[0] == 1
        elif message_id == MSG_SEAMLESS_CONNECTION:
            s["seamless"] = v[0] == 0

    def _extended_status(self, p):
        def at(i, default=0):
            return p[i] if i < len(p) else default
        self.state = {
            "revision": at(0),
            "left": at(2),
            "right": at(3),
            "placement": at(6),
            "case": at(7),
            "game": at(8) == 1,
            "eq": EQ_NAMES.get(at(9), "off"),
            "touch": at(10),
            "hold": [at(11) >> 4, at(11) & 0x0F],
            "noise": NOISE_NAMES.get(at(12), "off"),
            "ambient": at(23),
            "seamless": at(19) == 0,
            "oneEarbud": at(28) == 1,
            "charging": at(42),
        }
        self.error = ""
        self.touch()

    @property
    def ready(self):
        return self.state is not None

    def set(self, key, value, now):
        s = self.state
        if s is None:
            return
        if key == "noise" and value in self.spec["noise"]:
            s["noise"] = value
            self.send(encode(MSG_NOISE_CONTROLS, [NOISE_VALUES[value]]))
        elif key == "ambient" and value in range(self.spec["ambient_levels"]):
            s["ambient"] = value
            self.send(encode(MSG_AMBIENT_VOLUME, [value]))
        elif key == "eq" and value in EQ_VALUES:
            s["eq"] = value
            self.send(encode(MSG_EQUALIZER, [EQ_VALUES[value]]))
        elif key == "game":
            s["game"] = bool(value)
            self.send(encode(MSG_GAME_MODE, [int(bool(value))]))
        elif key == "touch" or key in (g[0] for g in GESTURES):
            bit = 7 if key == "touch" else next(g[1] for g in GESTURES if g[0] == key)
            s["touch"] = (s["touch"] | 1 << bit) if value else (s["touch"] & ~(1 << bit))
            t = s["touch"]
            # Touchpad on, then single, double, triple pinch, pinch and hold, the
            # two call gestures and, on stem models, the volume swipe.
            payload = [t >> 7 & 1, t >> 3 & 1, t >> 2 & 1, t >> 1 & 1, t & 1, t >> 4 & 1, t >> 5 & 1]
            if self.spec.get("swipe"):
                payload.append(t >> 6 & 1)
            self.send(encode(MSG_LOCK_TOUCHPAD, payload))
        elif key == "seamless":
            s["seamless"] = bool(value)
            self.send(encode(MSG_SEAMLESS_CONNECTION, [0 if value else 1]))
        elif key == "oneEarbud":
            s["oneEarbud"] = bool(value)
            self.send(encode(MSG_ANC_WITH_ONE_EARBUD, [int(bool(value))]))
        elif key in ("holdLeft", "holdRight") and value in (o["value"] for o in HOLD_ACTIONS):
            s["hold"][0 if key == "holdLeft" else 1] = value
            self.send(encode(MSG_TOUCHPAD_OPTION, s["hold"]))
        else:
            return
        self.touch()

    def snapshot(self):
        s = self.state
        if not s:
            return {"battery": [], "controls": [], "settings": [], "summary": [],
                    "active": False, "toggle": None}
        battery = []
        for side, mask in (("left", 0x10), ("right", 0x04), ("case", 0x01)):
            level = s[side]
            if 0 < level <= 100:
                battery.append({"id": side, "label": {"left": "L", "right": "R", "case": "Case"}[side],
                                "level": level, "charging": bool(s["charging"] & mask)})
        noise_options = [option(k, NOISE_LABELS[k]) for k in self.spec["noise"]]
        controls = [
            control("noise", "segmented", "Noise control", s["noise"], noise_options),
            control("ambient", "choice", "Ambient volume", s["ambient"], AMBIENT_LEVELS,
                    visible="ambient" in self.spec["noise"] and s["noise"] == "ambient"),
            control("game", "toggle", "Game mode", s["game"], description="Lower audio latency"),
            control("eq", "list", "Equalizer", s["eq"], EQ_PRESETS),
        ]
        touch_on = bool(s["touch"] & 0x80)
        settings = [
            control("touch", "toggle", "Touch controls", touch_on,
                    description="Pinch and swipe gestures on the stems", section="Gestures"),
        ]
        for key, bit, label in GESTURES:
            if key != "swipe" or self.spec.get("swipe"):
                settings.append(control(key, "toggle", label, bool(s["touch"] >> bit & 1), enabled=touch_on))
        settings += [
            control("holdLeft", "choice", "Left bud", s["hold"][0], HOLD_ACTIONS, enabled=touch_on,
                    section="Pinch and hold", section_description="What a long pinch on each bud does"),
            control("holdRight", "choice", "Right bud", s["hold"][1], HOLD_ACTIONS, enabled=touch_on),
            control("oneEarbud", "toggle", "Noise cancelling with one earbud", s["oneEarbud"],
                    description="Keep noise cancelling on when only one bud is in", section="Other"),
            control("seamless", "toggle", "Seamless connection", s["seamless"],
                    description="Switch between Samsung devices signed in to the same account"),
        ]
        return {
            "battery": battery,
            "controls": controls,
            "settings": settings,
            "summary": [label_of(noise_options, s["noise"])],
            "active": s["noise"] != "off",
            "toggle": {"id": "noise", "on": "anc", "off": "off", "value": s["noise"]},
        }
