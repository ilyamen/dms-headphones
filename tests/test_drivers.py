import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "helper"))

from hp import sdp  # noqa: E402
from hp.drivers import find_driver, galaxy_buds, ugreen  # noqa: E402
from hp.session import Session  # noqa: E402

MAX5 = {"address": "00:11:22:33:44:55", "name": "UGREEN HiTune Max5", "alias": "UGREEN HiTune Max5",
        "uuids": ["00001101-0000-1000-8000-00805f9b34fb"], "modalias": ""}
BUDS3 = {"address": "00:11:22:33:44:66", "name": "Buds3 (Anna)", "alias": "Buds3 (Anna)",
         "uuids": ["2e73a4ad-332d-41fc-90e2-16bef06523f2", "d908aab5-7a90-4cbe-8641-86a553db014d"],
         "modalias": "bluetooth:v0075pA013d0001"}


def frames(driver):
    return driver.take_output()


class UgreenTest(unittest.TestCase):
    def driver(self):
        cls, model = find_driver(MAX5)
        self.assertIs(cls, ugreen.UgreenDriver)
        driver = cls(MAX5, model)
        driver.connected(0.0)
        driver.poll(0.0)
        return driver

    def answer(self, driver, command, payload, now=0.1):
        body = bytes([command, 1, len(payload)]) + bytes(payload)
        crc = ugreen.crc16(body)
        driver.received(ugreen.RESPONSE + body + bytes([crc & 0xFF, crc >> 8]), now)

    def test_requests_state_on_connect(self):
        driver = self.driver()
        self.assertEqual(frames(driver), [ugreen.encode(ugreen.CMD_STATE, [0])])
        self.assertEqual(ugreen.encode(ugreen.CMD_GAME, [1])[:6], bytes([0xAA, 0xBB, 0xCC, 8, 1, 1]))

    def test_real_ack_and_reject_frames(self):
        parser = ugreen.FrameParser()
        parser.feed(bytes.fromhex("DDEEFF090101B1C44C"), 0.0)
        self.assertEqual([k for k, _ in parser.frames(0.0)], ["response"])
        # Max5 answer to an ANC change sent while a voice prompt was playing.
        parser.feed(bytes.fromhex("DDEEFFB1003033"), 1.0)
        self.assertEqual(list(parser.frames(1.0)), [])
        self.assertEqual([k for k, _ in parser.frames(1.5)], ["reject"])

    def test_max5_state_and_controls(self):
        driver = self.driver()
        frames(driver)
        # State captured from a real Max5: 60 %, ANC strong, buttons ANC/Game.
        self.answer(driver, ugreen.CMD_STATE, bytes.fromhex("3CFFFFA100000001080000070000000000000000"))
        snap = driver.snapshot()
        self.assertEqual(snap["battery"][0]["level"], 60)
        controls = {c["id"]: c for c in snap["controls"]}
        self.assertEqual(controls["noise"]["value"], "anc")
        self.assertEqual(controls["strength"]["value"], "strong")
        self.assertTrue(controls["ldac"]["value"])
        self.assertFalse(controls["game"]["enabled"])
        self.assertNotIn("spatial", controls)
        settings = {c["id"]: c for c in snap["settings"]}
        self.assertEqual([settings["button%d" % i]["value"] for i in range(4)], [8, 0, 0, 7])
        self.assertEqual(snap["summary"], ["Noise cancelling", "Strong"])

    def test_max5_anc_values(self):
        driver = self.driver()
        frames(driver)
        self.answer(driver, ugreen.CMD_STATE, bytes.fromhex("3CFFFF0000000001080000070000000000000000"))
        frames(driver)
        driver.set("noise", "transparency", 1.0)
        self.assertEqual(frames(driver), [ugreen.encode(ugreen.CMD_ANC, [0x02])])
        self.answer(driver, ugreen.CMD_ANC, [0x02], 1.1)
        driver.poll(1.1)
        frames(driver)  # state re-read
        self.answer(driver, ugreen.CMD_STATE, bytes.fromhex("3CFFFF0200000001080000070000000000000000"), 1.2)
        driver.set("strength", "medium", 2.0)
        self.assertEqual(frames(driver), [ugreen.encode(ugreen.CMD_ANC, [0xB1])])

    def test_ldac_no_op_is_not_sent(self):
        driver = self.driver()
        frames(driver)
        self.answer(driver, ugreen.CMD_STATE, bytes.fromhex("3CFFFF0000000001080000070000000000000000"))
        frames(driver)
        driver.set("ldac", True, 1.0)
        self.assertEqual(frames(driver), [])

    def test_reject_is_retried_once(self):
        driver = self.driver()
        frames(driver)
        self.answer(driver, ugreen.CMD_STATE, bytes.fromhex("3CFFFF0000000000080000070000000000000000"))
        driver.set("game", True, 1.0)
        sent = frames(driver)
        driver.received(bytes.fromhex("DDEEFF01003033"), 1.1)
        driver.poll(1.5)
        self.assertEqual(frames(driver), [])
        driver.poll(3.1)
        self.assertEqual(frames(driver), sent)

    def test_pushed_report(self):
        driver = self.driver()
        frames(driver)
        self.answer(driver, ugreen.CMD_STATE, bytes.fromhex("3CFFFF0000000000080000070000000000000000"))
        driver.received(bytes([0x85, 0x86, 0x87, 0x00, 0x02, 0xC1]), 1.0)
        controls = {c["id"]: c for c in driver.snapshot()["controls"]}
        self.assertEqual((controls["noise"]["value"], controls["strength"]["value"]), ("anc", "light"))


class GalaxyBudsTest(unittest.TestCase):
    # ExtendedStatusUpdate from a Buds FE (GalaxyBudsClient test data): 58/89 %,
    # both worn, touch on with all gestures, hold = volume on both buds.
    FE_STATUS = bytes.fromhex("fd31106102063a590100110000008f3300004a014a01030004650001001000000101"
                              "110300000000e80300009d0e1d005000c2cfdd")

    def driver(self):
        cls, model = find_driver(BUDS3)
        self.assertIs(cls, galaxy_buds.GalaxyBudsDriver)
        self.assertEqual(model, "Galaxy Buds3")
        driver = cls(BUDS3, model)
        driver.connected(0.0)
        return driver

    def test_crc_matches_real_frame(self):
        messages, rest = galaxy_buds.decode_stream(self.FE_STATUS + b"\xfd\x03")
        self.assertEqual(rest, b"\xfd\x03")
        self.assertEqual(messages[0][0], galaxy_buds.MSG_EXTENDED_STATUS)

    def test_status_and_greeting(self):
        driver = self.driver()
        self.assertEqual(frames(driver), [galaxy_buds.encode(galaxy_buds.MSG_EXTENDED_STATUS)])
        driver.received(self.FE_STATUS[:20], 0.1)
        driver.received(self.FE_STATUS[20:], 0.2)
        self.assertEqual(frames(driver), [galaxy_buds.encode(galaxy_buds.MSG_MANAGER_INFO, [1, 1, 34])])
        snap = driver.snapshot()
        self.assertEqual([(b["id"], b["level"]) for b in snap["battery"]], [("left", 58), ("right", 89)])
        controls = {c["id"]: c for c in snap["controls"]}
        self.assertEqual(controls["noise"]["value"], "off")
        settings = {c["id"]: c for c in snap["settings"]}
        self.assertTrue(settings["touch"]["value"])
        self.assertEqual(settings["holdLeft"]["value"], 3)

    def test_setters(self):
        driver = self.driver()
        driver.received(self.FE_STATUS, 0.1)
        frames(driver)
        driver.set("noise", "anc", 1.0)
        driver.set("eq", "bass", 1.0)
        driver.set("game", True, 1.0)
        driver.set("touch", False, 1.0)
        self.assertEqual(frames(driver), [
            galaxy_buds.encode(0x78, [1]),
            galaxy_buds.encode(0x86, [1]),
            galaxy_buds.encode(0x85, [1]),
            galaxy_buds.encode(0x90, [0, 1, 1, 1, 1, 0, 0, 0]),
        ])

    def test_acknowledgement_is_the_truth(self):
        driver = self.driver()
        driver.received(self.FE_STATUS, 0.1)
        driver.set("game", True, 1.0)
        driver.set("noise", "anc", 1.0)
        # Real acks from the Buds3: game mode applied, noise mode refused (off)
        driver.received(bytes.fromhex("fd05504285018187dd"), 1.1)
        driver.received(galaxy_buds.encode(galaxy_buds.MSG_ACK, [0x78, 0]), 1.2)
        controls = {c["id"]: c["value"] for c in driver.snapshot()["controls"]}
        self.assertEqual((controls["game"], controls["noise"]), (True, "off"))
        driver.received(bytes.fromhex("fd0cd0429001010101010101002a22dd"), 1.3)
        settings = {c["id"]: c["value"] for c in driver.snapshot()["settings"]}
        self.assertEqual((settings["touch"], settings["pinch"], settings["swipe"]), (True, True, False))

    def test_noise_update_pushed(self):
        driver = self.driver()
        driver.received(self.FE_STATUS, 0.1)
        driver.received(galaxy_buds.encode(galaxy_buds.MSG_NOISE_CONTROLS_UPDATE, [1]), 0.5)
        self.assertEqual(driver.snapshot()["summary"], ["Noise cancelling"])

    def test_real_buds3_status(self):
        # Captured from the Galaxy Buds3 this was written on: 99/99 %, both worn,
        # every gesture on, pinch and hold = noise control, seamless on.
        payload = bytes.fromhex("04056363010011000000ff2200004d014d01030004cc00000410000100000000000000"
                                "0100000000000000000000000000020000010100000000")
        driver = self.driver()
        driver.received(galaxy_buds.encode(galaxy_buds.MSG_EXTENDED_STATUS, payload), 0.1)
        snap = driver.snapshot()
        self.assertEqual([c["value"] for c in snap["controls"][0]["options"]], ["off", "anc"])
        settings = {c["id"]: c["value"] for c in snap["settings"]}
        self.assertEqual(settings, {"touch": True, "pinch": True, "doublePinch": True, "triplePinch": True,
                                    "pinchHold": True, "swipe": True, "holdLeft": 2, "holdRight": 2,
                                    "oneEarbud": False, "seamless": True})
        frames(driver)
        driver.set("swipe", False, 1.0)
        self.assertEqual(frames(driver), [galaxy_buds.encode(0x90, [1, 1, 1, 1, 1, 1, 1, 0])])

    def test_name_fallback_and_other_devices(self):
        self.assertEqual(find_driver(dict(BUDS3, uuids=[galaxy_buds.SPP_SERVICE]))[1], "Galaxy Buds3")
        self.assertEqual(find_driver(dict(BUDS3, uuids=[galaxy_buds.SPP_SERVICE], name="Buds3 Pro"))[1], None)
        self.assertEqual(find_driver({"name": "JBL TUNE770NC", "uuids": []}), (None, None))


class SdpTest(unittest.TestCase):
    def test_parse_rfcomm_record(self):
        # One record: classes [SPP], protocols [[L2CAP], [RFCOMM, 12]], name
        attributes = (bytes.fromhex("0900013503191101")
                      + bytes.fromhex("090004350c3503190100350519000308") + bytes([12])
                      + bytes.fromhex("090100") + bytes([0x25, 4]) + b"Max5")
        lists = bytes([0x35, len(attributes) + 2, 0x35, len(attributes)]) + attributes
        records = sdp.parse_records(lists)
        self.assertEqual(records, [{"classes": [sdp.full_uuid(0x1101)], "name": "Max5", "channel": 12}])

    def test_request_layout(self):
        request = sdp.build_request("2e73a4ad-332d-41fc-90e2-16bef06523f2")
        self.assertEqual(request[0], 0x06)
        self.assertEqual(request[5:8], bytes([0x35, 0x11, 0x1C]))


class SessionTest(unittest.TestCase):
    def test_links_every_supported_headset(self):
        states = []
        jbl = {"address": "00:11:22:33:44:77", "name": "JBL TUNE770NC", "uuids": []}
        infos = {jbl["address"]: jbl, MAX5["address"]: MAX5, BUDS3["address"]: BUDS3}
        session = Session(states.append, probe=infos.get, connect=lambda *a: None)
        session.handle({"cmd": "devices", "addresses": [BUDS3["address"], jbl["address"], MAX5["address"]]}, 0.0)
        devices = states[-1]["devices"]
        self.assertEqual([d["device"]["model"] for d in devices], ["Galaxy Buds3", "UGREEN HiTune Max5"])
        self.assertEqual({d["status"] for d in devices}, {"connecting"})
        session.handle({"cmd": "devices", "addresses": [jbl["address"], MAX5["address"]]}, 1.0)
        self.assertEqual([d["device"]["model"] for d in states[-1]["devices"]], ["UGREEN HiTune Max5"])
        session.handle({"cmd": "devices", "addresses": []}, 2.0)
        self.assertEqual(states[-1]["devices"], [])


if __name__ == "__main__":
    unittest.main()
