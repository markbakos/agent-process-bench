import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from support_sla_router import SLARouter


class SmokeTest(unittest.TestCase):
    def test_public_api_is_importable(self):
        self.assertTrue(callable(SLARouter))
