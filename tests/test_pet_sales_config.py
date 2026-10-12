"""The approved production rollout must retain an explicit emergency off switch."""

import os
import unittest
from unittest.mock import patch

from main import pet_sales_enabled


class PetSalesConfigurationTests(unittest.TestCase):
    def test_live_sales_enabled_without_old_environment_flag(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(pet_sales_enabled())

    def test_explicit_enable_and_emergency_disable(self):
        for value, expected in (("1", True), (" 1 ", True), ("0", False), (" 0 ", False), ("", False), ("invalid", False)):
            with self.subTest(value=value), patch.dict(os.environ, {"PETS_PAYMENTS_ENABLED": value}):
                self.assertEqual(pet_sales_enabled(), expected)


if __name__ == "__main__":
    unittest.main()
