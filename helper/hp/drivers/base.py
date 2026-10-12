"""What every headset driver provides to the session.

A driver turns the vendor protocol into a model-independent description: the
battery levels and a list of controls. The plugin renders that description, so a
new headset needs a driver and nothing else.

Controls are dicts:
    id           what `set` receives
    kind         "segmented" (full-width mode switch), "choice" (labelled row of
                 buttons), "toggle" or "list" (dropdown)
    label        English text; the plugin translates it
    value        current value
    options      [{"value", "label"}] for everything but toggles
    description  optional second line
    enabled      False greys the control out
    visible      False hides it
    section      optional heading shown above the control (settings page)
Labels and descriptions stay English here and are translated in the plugin.
"""


def option(value, label):
    return {"value": value, "label": label}


def control(id, kind, label, value, options=None, description="", enabled=True, visible=True,
            section="", section_description=""):
    entry = {"id": id, "kind": kind, "label": label, "value": value,
             "description": description, "enabled": enabled, "visible": visible,
             "section": section, "sectionDescription": section_description}
    if options is not None:
        entry["options"] = options
    return entry


def label_of(options, value):
    return next((o["label"] for o in options if o["value"] == value), "")


class Driver:
    # Material Symbols icon for the headset type
    icon = "headphones"
    # Seconds to wait after the audio link comes up before opening the control
    # port; some headsets ignore it while they are still setting up.
    settle = 1.0

    def __init__(self, info, model):
        self.info = info
        self.model = model
        self.changed = True
        self.error = ""
        self._out = []

    @classmethod
    def match(cls, info):
        """Model entry for a BlueZ device, or None if this driver does not handle it."""
        return None

    def channel(self):
        """RFCOMM channel of the control port."""
        raise NotImplementedError

    def connected(self, now):
        """The control port is open."""

    def received(self, data, now):
        """Bytes arrived from the headset."""

    def poll(self, now):
        """Called a few times a second for timeouts and retries."""

    def set(self, key, value, now):
        """The user changed control `key` to `value`."""

    def refresh(self):
        """Ask the headset for its full state again."""

    @property
    def ready(self):
        """True once the headset has reported its state."""
        return False

    @property
    def busy(self):
        return False

    def snapshot(self):
        """{"battery": [...], "controls": [...], "settings": [...], "summary": [...],
        "active": bool, "toggle": {"id", "on", "off"} or None}"""
        raise NotImplementedError

    # Session side

    def send(self, frame):
        self._out.append(bytes(frame))

    def take_output(self):
        out, self._out = self._out, []
        return out

    def touch(self):
        self.changed = True
