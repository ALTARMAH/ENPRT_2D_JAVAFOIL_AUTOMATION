import os, sys, time
import unittest
import aero_auto as A

class TestAeroEnhancements(unittest.TestCase):
    def test_famous_packages_sources(self):
        pkgs = A.get_famous_packages()
        self.assertEqual(len(pkgs), 40)
        for p in pkgs:
            self.assertIn('source_url', p, f"Package {p['id']} missing source_url")
            self.assertTrue(p['source_url'].startswith('http'), f"Invalid URL for {p['id']}: {p['source_url']}")
            self.assertIn('source_title', p, f"Package {p['id']} missing source_title")
            # Check achievement has no emojis
            ach = p.get('achievement', '')
            import re
            emojis = re.findall(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]', ach)
            self.assertEqual(len(emojis), 0, f"Achievement has emojis in {p['id']}: {ach}")

    def test_scoring_profiles(self):
        self.assertIn('cl_stability', A.SCORING_PROFILES)
        prof = A.SCORING_PROFILES['cl_stability']
        self.assertEqual(prof['short'], 'Cl Alpha Stable')
        self.assertIn('Score_ClStability', A.SCORE_FIELDS)

    def test_launch_javafoil_gui(self):
        p1 = A.FAMOUS_PACKAGES[0]
        cfg = (p1['main'], tuple(p1['flaps']))
        ok, msg, proc = A.launch_javafoil_gui(cfg, ground_h=30.0, re_val=300000, title="Test Wing")
        self.assertTrue(ok, f"JavaFoil launch failed: {msg}")
        self.assertIn("JavaFoil GUI launched", msg)
        if proc:
            time.sleep(1)
            # Process is running interactively in background
            self.assertIsNone(proc.poll())
            proc.terminate()

    def test_no_emojis_in_source_files(self):
        import re
        for fn in ['aero_auto.py', 'aero_ui.py']:
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), fn)
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            emojis = re.findall(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]', content)
            self.assertEqual(len(emojis), 0, f"Found {len(emojis)} emojis in {fn}")

if __name__ == '__main__':
    unittest.main()
