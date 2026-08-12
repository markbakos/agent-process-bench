import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from appointment_scheduler import Scheduler


class SmokeTest(unittest.TestCase):
    def test_public_api_is_importable(self):
        self.assertTrue(callable(Scheduler))
