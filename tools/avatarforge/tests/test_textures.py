"""Alpha / hair decisions and texture discovery."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from core import textures as T  # noqa: E402


class Alpha(unittest.TestCase):
    def test_hair_card_cutout_is_masked(self):
        st = {"transparent": 0.55, "opaque": 0.40, "mid": 0.05, "mean": 0.4}
        self.assertEqual(T.decide_alpha("Hair_Cards", st, False)[0], "masked")

    def test_specular_alpha_is_opaque(self):
        # nearly all near-zero: a mask would make the hair vanish (the Kalina case)
        st = {"transparent": 0.97, "opaque": 0.0, "mid": 0.03, "mean": 0.01}
        self.assertEqual(T.decide_alpha("Kalina_Hair", st, False)[0], "opaque")

    def test_soft_continuous_alpha_is_opaque(self):
        st = {"transparent": 0.03, "opaque": 0.0, "mid": 0.97, "mean": 0.5}
        self.assertEqual(T.decide_alpha("Face", st, False)[0], "opaque")

    def test_importer_transparency_flag_ignored_when_texture_has_no_alpha(self):
        self.assertEqual(T.decide_alpha("Material_5", {"none": True}, True)[0], "opaque")

    def test_no_alpha_channel(self):
        self.assertEqual(T.decide_alpha("Body", None, False)[0], "opaque")

    def test_source_material_transparency_without_stats(self):
        self.assertEqual(T.decide_alpha("Leaf", None, True)[0], "masked")

    def test_hair_forced_two_sided(self):
        out = T.merge([{"name": "Hair_Front", "base": None}], {}, {})
        self.assertTrue(out[0]["two_sided"])
        self.assertEqual(out[0]["class"], "hair")

    def test_classes(self):
        self.assertEqual(T.material_class("Eyelashes_Mat"), "hair")
        self.assertEqual(T.material_class("Skin_Body"), "skin")
        self.assertEqual(T.material_class("Fence_01"), "cutout")


class Discover(unittest.TestCase):
    def test_discovery(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for f in ("Kalina_N01_body_diffuse.png", "Kalina_N01_body_normal.png", "Kalina_Face_Diffuse.png",
                      "Kalina_N01_body_ID.png", "Kalina_Face_Mask.png", "kalina_V3_MatCap.png", "Kalina_Hair_Diffuse.png"):
                open(os.path.join(d, f), "wb").write(b"x")
            r = T.discover(d, ["Kalina_N01_body", "Kalina_N01_Face", "Kalina_Hair"])
            self.assertTrue(r["Kalina_N01_body"]["base"].endswith("body_diffuse.png"))
            self.assertTrue(r["Kalina_N01_body"]["normal"].endswith("body_normal.png"))
            self.assertTrue(r["Kalina_N01_Face"]["base"].endswith("Face_Diffuse.png"))
            self.assertTrue(r["Kalina_Hair"]["base"].endswith("Hair_Diffuse.png"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
