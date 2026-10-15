import os
import tempfile
import unittest
import aero_auto as A

class TestCadExports(unittest.TestCase):
    def setUp(self):
        A.load_all(A.AIRFOIL_DIR)
        self.tmp_dir = tempfile.mkdtemp()
        self.cfg = ('s1223', [('e423', 35.0, 15.0, 98.0, 5.0), ('e423', 25.0, 30.0, 130.0, 15.0)])

    def tearDown(self):
        import shutil
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)

    def test_export_dxf_spline_continuous(self):
        out_p = os.path.join(self.tmp_dir, "test_wing.dxf")
        res = A.export_dxf(self.cfg, out_p, chord_mm=300.0, spline_mode=True)
        self.assertTrue(os.path.isfile(res))
        with open(res, 'r', encoding='ascii', errors='ignore') as f:
            content = f.read()
        self.assertIn("AcDbSpline", content)
        self.assertIn("SPLINE", content)
        self.assertIn("AcDbPolyline", content)
        self.assertIn("LWPOLYLINE", content)
        self.assertIn("EOF", content)

    def test_export_step_3d_solid(self):
        out_p = os.path.join(self.tmp_dir, "test_wing.step")
        res = A.export_step(self.cfg, out_p, chord_mm=300.0, span_mm=500.0)
        self.assertTrue(os.path.isfile(res))
        with open(res, 'r', encoding='ascii', errors='ignore') as f:
            content = f.read()
        self.assertIn("ISO-10303-21", content)
        self.assertIn("HEADER", content)
        self.assertTrue("MANIFOLD_SOLID_BREP" in content or "ADVANCED_BREP_SHAPE_REPRESENTATION" in content)
        self.assertIn("END-ISO-10303-21", content)

    def test_export_step_builtin_fallback(self):
        outlines = A.build_outlines(self.cfg)
        outlines_mm = [pts * 300.0 for pts in outlines]
        out_p = os.path.join(self.tmp_dir, "test_builtin.step")
        res = A._export_step_builtin(outlines_mm, out_p, span_mm=400.0, title="Fallback Test")
        self.assertTrue(os.path.isfile(res))
        with open(res, 'r', encoding='ascii', errors='ignore') as f:
            content = f.read()
        self.assertIn("ISO-10303-21", content)
        self.assertIn("MANIFOLD_SOLID_BREP", content)
        self.assertIn("CLOSED_SHELL", content)
        self.assertIn("ADVANCED_FACE", content)

    def test_export_freecad_macro(self):
        out_p = os.path.join(self.tmp_dir, "test_macro.FCMacro")
        res = A.export_freecad_macro(self.cfg, out_p, chord_mm=300.0, span_mm=600.0)
        self.assertTrue(os.path.isfile(res))
        with open(res, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("# -*- coding: utf-8 -*-", content)
        self.assertIn("Part.BSplineCurve()", content)
        self.assertIn("approximate(", content)
        self.assertIn("face = Part.Face(wire)", content)
        self.assertIn("solid = face.extrude", content)
        self.assertIn("s1223", content)
        self.assertIn("e423", content)

if __name__ == '__main__':
    unittest.main()
