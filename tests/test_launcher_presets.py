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
                self.assertEqual(app.cfg_name_var.get(), p["name"])
        finally:
            app.destroy()

    def test_save_and_load_config_json(self):
        import tempfile, json
        from tkinter import filedialog
        app = aero_ui.App()
        app.withdraw()
        try:
            app.load_config_json(aero_ui.ENPRT_PRESETS[0])
            app.cfg_name_var.set("Test_Wing_Alpha")
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
                tmp_json = tf.name

            orig_ask = filedialog.asksaveasfilename
            try:
                filedialog.asksaveasfilename = lambda **kwargs: tmp_json
                app.on_save_config_json()
                self.assertTrue(os.path.exists(tmp_json))
                self.assertGreater(os.path.getsize(tmp_json), 0)

                with open(tmp_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.assertEqual(data["name"], "Test_Wing_Alpha")
                self.assertEqual(data["main"], "e423")
                self.assertEqual(len(data["flaps"]), 2)
            finally:
                filedialog.asksaveasfilename = orig_ask
                if os.path.exists(tmp_json):
                    os.remove(tmp_json)
        finally:
            app.destroy()

    def test_save_current_run_archive(self):
        import tempfile, zipfile
        from tkinter import filedialog
        app = aero_ui.App()
        app.withdraw()
        try:
            app.load_config_json(aero_ui.ENPRT_PRESETS[0])
            app.cfg_name_var.set("Archive_Test_Run")
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
                tmp_zip = tf.name

            orig_ask = filedialog.asksaveasfilename
            try:
                filedialog.asksaveasfilename = lambda **kwargs: tmp_zip
                app.on_save_current_run_archive()
                self.assertTrue(os.path.exists(tmp_zip))
                with zipfile.ZipFile(tmp_zip, 'r') as z:
                    names = z.namelist()
                    self.assertIn("config_Archive_Test_Run.json", names)
            finally:
                filedialog.asksaveasfilename = orig_ask
                if os.path.exists(tmp_zip):
                    os.remove(tmp_zip)
        finally:
            app.destroy()

    def test_go_to_graphs_generates_configured(self):
        app = aero_ui.App()
        app.withdraw()
        try:
            app.load_config_json(aero_ui.ENPRT_PRESETS[0])
            app.cfg_name_var.set("Test_Go_To_Graphs")
            app.notebook.select(app.tab_cfg)
            app.on_go_to_graphs()
            self.assertEqual(app.notebook.select(), str(app.tab_gr))
            self.assertEqual(app.gr_selected_rid, "Test_Go_To_Graphs")
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
            l_app.presets.append({"id": "custom_temp", "main": "s1223", "flaps": []})
            self.assertEqual(len(l_app.presets), 7)
            l_app.on_reset_presets()
            self.assertEqual(len(l_app.presets), 6)
        finally:
            l_app.destroy()

if __name__ == "__main__":
    unittest.main()
