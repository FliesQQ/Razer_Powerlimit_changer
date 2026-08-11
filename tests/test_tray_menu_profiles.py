"""Tray menu profile visibility helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.profile_manager import ProfileManager


class TestTrayMenuProfiles(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "profiles.json"
        self.mgr = ProfileManager(path=self.path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_default_shows_all(self) -> None:
        ids = self.mgr.tray_menu_profile_ids()
        self.assertEqual(ids, [p.id for p in self.mgr.profiles])
        self.assertEqual(len(self.mgr.tray_menu_profiles()), len(self.mgr.profiles))

    def test_custom_subset_and_order(self) -> None:
        all_ids = [p.id for p in self.mgr.profiles]
        self.assertGreaterEqual(len(all_ids), 2)
        subset = [all_ids[1], all_ids[0]]
        self.mgr.set_tray_menu_profile_ids(subset)
        self.assertEqual(self.mgr.tray_menu_profile_ids(), subset)
        names = [p.name for p in self.mgr.tray_menu_profiles()]
        self.assertEqual(
            names,
            [self.mgr.get(subset[0]).name, self.mgr.get(subset[1]).name],
        )

    def test_delete_prunes_setting(self) -> None:
        all_ids = [p.id for p in self.mgr.profiles]
        victim = all_ids[0]
        self.mgr.set_tray_menu_profile_ids(all_ids)
        self.assertTrue(self.mgr.delete(victim))
        self.assertNotIn(victim, self.mgr.tray_menu_profile_ids())


if __name__ == "__main__":
    unittest.main()
