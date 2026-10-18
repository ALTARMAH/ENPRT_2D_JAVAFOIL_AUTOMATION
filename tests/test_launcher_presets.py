import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import aero_ui
import aero_auto as A
import open_in_aero_auto

class TestLauncherAndPresets(unittest.TestCase):
    def test_builtin_presets_exist(self):
        self.assertEqual(len(aero_ui.ENPRT_PRESETS), 6)
        expected_ids = {"FWA_hero", "FWA_stable", "FWB_hero", "FWB_stable", "RW_hero", "RW_incidence3"}
        actual_ids = {p["id"] for p in aero_ui.ENPRT_PRESETS}
        self.assertEqual(expected_ids, actual_ids)

    def test_load_all_presets_into_app(self):
        app = aero_ui.App()
        app.withdraw()
        try:
            for p in aero_ui.ENPRT_PRESETS:
                app.load_config_json(p)
                cfg = app.read_cfg()
                self.assertIsNotNone(cfg)
                self.assertEqual(cfg[0], p["main"])
                self.assertEqual(len(cfg[1]), len(p["flaps"]))
        finally:
            app.destroy()

    def test_open_in_aero_auto_app(self):
        l_app = open_in_aero_auto.LauncherApp()
        l_app.withdraw()
        try:
            self.assertEqual(len(l_app.presets), 6)
            l_app.select_preset_by_index(0)
            self.assertEqual(l_app.current_cfg["id"], "FWA_hero")
            l_app.select_preset_by_index(4)
            self.assertEqual(l_app.current_cfg["id"], "RW_hero")
        finally:
            l_app.destroy()

if __name__ == "__main__":
    unittest.main()
