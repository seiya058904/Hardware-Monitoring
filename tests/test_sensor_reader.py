import math
import unittest

from app import SensorReader


class SensorReaderTest(unittest.TestCase):
    def test_pick_max_rejects_non_finite_sensor_values(self) -> None:
        self.assertIsNone(SensorReader._pick_max(None, math.nan))
        self.assertEqual(42.0, SensorReader._pick_max(42.0, math.inf))


if __name__ == "__main__":
    unittest.main()
