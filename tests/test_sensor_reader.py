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

        # Genuine UTF-8 must win over the Windows ANSI fallback.
        self.assertEqual("平均=8ms", decode("平均=8ms".encode("utf-8")))

        # Exercise the actual Windows ANSI code page on whichever locale CI
        # uses: pick a value that round-trips through mbcs but is not valid
        # UTF-8 bytes, so the fallback path is precisely verified everywhere.
        ansi_sample = None
        ansi_bytes = None
        for candidate in ("é=12ms", "ä=12ms", "时间=12ms"):
            try:
                encoded = candidate.encode("mbcs")
            except UnicodeEncodeError:
                continue
            try:
                encoded.decode("utf-8")
            except UnicodeDecodeError:
                ansi_sample = candidate
                ansi_bytes = encoded
                break

        self.assertIsNotNone(ansi_sample)
        self.assertEqual(ansi_sample, decode(ansi_bytes))

        # zh-CN machines specifically emit GBK/CP936 localized console text.
        try:
            import ctypes

            acp = ctypes.windll.kernel32.GetACP()
        except Exception:
            acp = None
        if acp == 936:
            self.assertEqual(
                "时间=12ms",
                decode("时间=12ms".encode("cp936")),
            )

        # Arbitrary bytes must degrade to text rather than raise.
        garbage = decode(b"\xff\xfe\x81\x40")
        self.assertIsInstance(garbage, str)


if __name__ == "__main__":
    unittest.main()
