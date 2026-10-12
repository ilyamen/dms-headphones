"""Minimal SDP client: finds the RFCOMM channel a device offers for a service.

Headsets put their control port on a vendor-chosen RFCOMM channel and announce it
over SDP. BlueZ keeps no copy of the records, and `sdptool` is deprecated and often
not installed, so this speaks the protocol directly over L2CAP PSM 1.
"""

import socket
import struct
import uuid

SDP_PSM = 1
SERVICE_SEARCH_ATTRIBUTE_REQUEST = 0x06
SERVICE_SEARCH_ATTRIBUTE_RESPONSE = 0x07
ERROR_RESPONSE = 0x01

ATTR_SERVICE_CLASS_IDS = 0x0001
ATTR_PROTOCOL_DESCRIPTORS = 0x0004
ATTR_SERVICE_NAME = 0x0100

BASE_UUID_TAIL = "-0000-1000-8000-00805f9b34fb"
UUID_L2CAP = 0x0100
UUID_RFCOMM = 0x0003


def full_uuid(value):
    """Normalize a 16/32-bit short form or a 128-bit UUID to the long string form."""
    if isinstance(value, int):
        return "%08x%s" % (value, BASE_UUID_TAIL)
    return str(uuid.UUID(value))


def _uuid_element(value):
    if isinstance(value, int) and value <= 0xFFFF:
        return bytes([0x19]) + struct.pack(">H", value)
    return bytes([0x1C]) + uuid.UUID(full_uuid(value)).bytes


def _sequence(body):
    if len(body) < 256:
        return bytes([0x35, len(body)]) + body
    return bytes([0x36]) + struct.pack(">H", len(body)) + body


def build_request(service_uuid, transaction=1, continuation=b""):
    """ServiceSearchAttributeRequest for every attribute of matching records."""
    pattern = _sequence(_uuid_element(service_uuid))
    attributes = _sequence(bytes([0x0A]) + struct.pack(">I", 0x0000FFFF))
    params = pattern + struct.pack(">H", 0xFFFF) + attributes + bytes([len(continuation)]) + continuation
    return struct.pack(">BHH", SERVICE_SEARCH_ATTRIBUTE_REQUEST, transaction, len(params)) + params


def parse_element(data, offset=0):
    """Decode one SDP data element; returns (value, next_offset).

    Sequences become lists, UUIDs long-form strings, integers ints, text str.
    """
    header = data[offset]
    kind, size_index = header >> 3, header & 0x07
    offset += 1
    if kind == 0:
        return None, offset
    if size_index < 5:
        length = (1, 2, 4, 8, 16)[size_index]
    else:
        width = (1, 2, 4)[size_index - 5]
        length = int.from_bytes(data[offset:offset + width], "big")
        offset += width
    raw = data[offset:offset + length]
    if len(raw) < length:
        raise ValueError("truncated SDP element")
    end = offset + length
    if kind in (1, 2):
        return int.from_bytes(raw, "big", signed=kind == 2), end
    if kind == 3:
        if length == 16:
            return str(uuid.UUID(bytes=raw)), end
        return full_uuid(int.from_bytes(raw, "big")), end
    if kind in (4, 8):
        return raw.rstrip(b"\x00").decode("utf-8", "replace"), end
    if kind == 5:
        return raw != b"\x00", end
    if kind in (6, 7):
        items = []
        while offset < end:
            item, offset = parse_element(data, offset)
            items.append(item)
        return items, end
    return raw, end


def parse_records(attribute_lists):
    """Turn the AttributeLists sequence into simple record dicts."""
    records = []
    lists, _ = parse_element(attribute_lists)
    for attributes in lists or []:
        pairs = dict(zip(attributes[0::2], attributes[1::2]))
        record = {
            "classes": [c for c in pairs.get(ATTR_SERVICE_CLASS_IDS) or [] if isinstance(c, str)],
            "name": pairs.get(ATTR_SERVICE_NAME) if isinstance(pairs.get(ATTR_SERVICE_NAME), str) else "",
            "channel": None,
        }
        for protocol in pairs.get(ATTR_PROTOCOL_DESCRIPTORS) or []:
            if isinstance(protocol, list) and len(protocol) >= 2 and protocol[0] == full_uuid(UUID_RFCOMM):
                record["channel"] = protocol[1]
        records.append(record)
    return records


def search(address, service_uuid, timeout=8.0):
    """Records of `address` that list `service_uuid`, with their RFCOMM channels."""
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
    sock.settimeout(timeout)
    try:
        sock.connect((address, SDP_PSM))
        collected = b""
        continuation = b""
        for transaction in range(1, 32):
            sock.send(build_request(service_uuid, transaction, continuation))
            reply = sock.recv(4096)
            if not reply or reply[0] == ERROR_RESPONSE:
                raise OSError("SDP request refused")
            if reply[0] != SERVICE_SEARCH_ATTRIBUTE_RESPONSE:
                raise OSError("unexpected SDP reply 0x%02x" % reply[0])
            count = struct.unpack(">H", reply[5:7])[0]
            collected += reply[7:7 + count]
            state_length = reply[7 + count]
            continuation = reply[8 + count:8 + count + state_length]
            if not continuation:
                break
        return parse_records(collected) if collected else []
    finally:
        sock.close()
