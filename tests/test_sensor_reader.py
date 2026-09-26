import math
import unittest

from app import SensorReader


class SensorReaderTest(unittest.TestCase):
    def test_pick_max_rejects_non_finite_sensor_values(self) -> None:
        self.assertIsNone(SensorReader._pick_max(None, math.nan))
        self.assertEqual(42.0, SensorReader._pick_max(42.0, math.inf))

    def test_decode_output_never_raises_and_reads_localized_output(self) -> None:
        decode = SensorReader._decode_output
        self.assertEqual("", decode(b""))
        self.assertEqual("time=12ms", decode(b"time=12ms"))
        # Localized GBK console output (ping on zh-CN) must survive UTF-8 mode.
        self.assertEqual("时间=12ms", decode("时间=12ms".encode("cp936")))
        # Genuine UTF-8 output must win over the ANSI codepage fallback.
        self.assertEqual("平均=8ms", decode("平均=8ms".encode("utf-8")))
        # Undecodable garbage degrades to a replacement-char string, never an exception.
        garbage = decode(b"\xff\xfe\x81\x40")
        self.assertIsInstance(garbage, str)
        self.assertIn("\ufffd", garbage)


if __name__ == "__main__":
    unittest.main()
