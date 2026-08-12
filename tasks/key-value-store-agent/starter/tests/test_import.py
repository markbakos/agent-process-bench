import unittest

from src import kvstore


class ImportTest(unittest.TestCase):
    def test_module_is_importable(self) -> None:
        self.assertIsNotNone(kvstore)
