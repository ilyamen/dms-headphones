"""RFCOMM connection to a headset's control port."""

import socket
import struct

SOL_BLUETOOTH = 274
BT_SECURITY = 4
# Encrypted link without requiring MITM protection: headsets pair with "just
# works", so asking for more would fail on an otherwise healthy bond.
BT_SECURITY_MEDIUM = 2


def open_rfcomm(address, channel, timeout=8.0):
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    try:
        sock.setsockopt(SOL_BLUETOOTH, BT_SECURITY, struct.pack("BB", BT_SECURITY_MEDIUM, 0))
        sock.settimeout(timeout)
        sock.connect((address, channel))
        sock.setblocking(False)
        return sock
    except BaseException:
        sock.close()
        raise
