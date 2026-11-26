"""Bone-mapping tests on synthetic rigs: the mannequin's own joints renamed under common conventions."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from core import bonemap as B  # noqa: E402

Q = json.load(open(os.path.join(HERE, "..", "data", "mannequin_skeleton.json")))
QB = {b["name"]: b for b in Q["bones"]}
FINGERS = ("thumb", "index", "middle", "ring", "pinky")
CORE = list(B.REQUIRED) + ["neck_01", "spine_01", "spine_03", "spine_05", "ball_l", "ball_r", "clavicle_l", "clavicle_r"] + \
    [f"{f}_0{i}_{s}" for f in FINGERS for i in (1, 2, 3) for s in "lr"]
LEFT_X = 1.0 if QB["upperarm_l"]["pos"][0] > 0 else -1.0


def rig(rename):
    """Bones with the mannequin's hierarchy and (Blender space, metres) positions, under another naming scheme."""
    names = {}
    for b in Q["bones"]:
        n = rename(b["name"])
        if n:
            names[b["name"]] = n
    out = []
    for b in Q["bones"]:
        if b["name"] not in names:
            continue
        p = b["parent"]
        while p not in ("None", "", None) and p not in names:
            p = QB[p]["parent"]
        out.append({"name": names[b["name"]], "parent": names.get(p), "weighted": True,
                    "head": [b["pos"][0] / 100, -b["pos"][1] / 100, b["pos"][2] / 100]})
    return out, names


def make_renamer(core, limb, finger):
    """core: single bones, limb: base -> name, finger: (side_letter, finger, seg) -> name, with side handling inline."""
    def rename(n):
        if n in core:
            return core[n]
        for s in "lr":
            if n.endswith("_" + s):
                k = n[:-2]
                if k in limb:
                    return limb[k](s)
                for f in FINGERS:
                    for i in (1, 2, 3):
                        if k == f"{f}_0{i}":
                            return finger(s, f, i)
        return None
    return rename


mixamo = make_renamer(
    {"pelvis": "mixamorig:Hips", "spine_01": "mixamorig:Spine", "spine_03": "mixamorig:Spine1", "spine_05": "mixamorig:Spine2",
     "neck_01": "mixamorig:Neck", "head": "mixamorig:Head"},
    {k: (lambda s, v=v: "mixamorig:%s%s" % ("Left" if s == "l" else "Right", v)) for k, v in
     {"clavicle": "Shoulder", "upperarm": "Arm", "lowerarm": "ForeArm", "hand": "Hand", "thigh": "UpLeg", "calf": "Leg",
      "foot": "Foot", "ball": "ToeBase"}.items()},
    lambda s, f, i: "mixamorig:%sHand%s%d" % ("Left" if s == "l" else "Right", f.capitalize(), i))

biped = make_renamer(
    {"pelvis": "Bip001 Pelvis", "spine_01": "Bip001 Spine", "spine_03": "Bip001 Spine1", "spine_05": "Bip001 Spine2",
     "neck_01": "Bip001 Neck", "head": "Bip001 Head"},
    {k: (lambda s, v=v: "Bip001 %s %s" % (s.upper(), v)) for k, v in
     {"clavicle": "Clavicle", "upperarm": "UpperArm", "lowerarm": "Forearm", "hand": "Hand", "thigh": "Thigh", "calf": "Calf",
      "foot": "Foot", "ball": "Toe0"}.items()},
    lambda s, f, i: "Bip001 %s Finger%d%s" % (s.upper(), FINGERS.index(f), "" if i == 1 else str(i - 1)))

vrm = make_renamer(
    {"pelvis": "J_Bip_C_Hips", "spine_01": "J_Bip_C_Spine", "spine_03": "J_Bip_C_Chest", "spine_05": "J_Bip_C_UpperChest",
     "neck_01": "J_Bip_C_Neck", "head": "J_Bip_C_Head"},
    {k: (lambda s, v=v: "J_Bip_%s_%s" % (s.upper(), v)) for k, v in
     {"clavicle": "Shoulder", "upperarm": "UpperArm", "lowerarm": "LowerArm", "hand": "Hand", "thigh": "UpperLeg",
      "calf": "LowerLeg", "foot": "Foot", "ball": "ToeBase"}.items()},
    lambda s, f, i: "J_Bip_%s_%s%d" % (s.upper(), "Little" if f == "pinky" else f.capitalize(), i))

dotted = make_renamer(
    {"pelvis": "hips", "spine_01": "spine", "spine_03": "spine.001", "spine_05": "chest", "neck_01": "neck", "head": "head"},
    {k: (lambda s, v=v: "%s.%s" % (v, s.upper())) for k, v in
     {"clavicle": "shoulder", "upperarm": "upper_arm", "lowerarm": "forearm", "hand": "hand", "thigh": "thigh", "calf": "shin",
      "foot": "foot", "ball": "toe"}.items()},
    lambda s, f, i: "%s.0%d.%s" % (f, i, s.upper()))


def ue_identity(n):
    skip = n.startswith(("ik_", "interaction", "center", "root")) or "twist" in n or "metacarpal" in n
    return None if skip else n


class Schemes(unittest.TestCase):
    def check(self, rename, label):
        bones, names = rig(rename)
        m = B.automap(bones, Q)
        wrong, missing = [], []
        for slot in CORE:
            src = names.get(slot)
            if src is None:
                continue
            got = m.slots.get(slot, {}).get("bone")
            if got is None:
                missing.append(slot)
            elif got != src:
                wrong.append((slot, got, src))
        self.assertFalse(wrong, f"{label} wrong: {wrong}")
        self.assertFalse(missing, f"{label} missing: {missing}")
        self.assertFalse(m.errors, f"{label} errors: {m.errors}")

    def test_mixamo(self):
        self.check(mixamo, "mixamo")

    def test_biped(self):
        self.check(biped, "biped")

    def test_vrm(self):
        self.check(vrm, "vrm")

    def test_dotted(self):
        self.check(dotted, "dotted")

    def test_ue(self):
        self.check(ue_identity, "ue")

    def test_decoys_with_no_weights_lose(self):
        bones, _ = rig(mixamo)
        dup = [{"name": "ORG-LeftArm", "parent": None, "weighted": False, "head": [0.2, 0, 1.4]}]
        m = B.automap(bones + dup, Q)
        self.assertEqual(m.slots["upperarm_l"]["bone"], "mixamorig:LeftArm")

    def test_swapped_sides_fixed(self):
        def swapped(n):
            r = mixamo(n)
            if r and "Left" in r:
                return r.replace("Left", "Right")
            if r and "Right" in r:
                return r.replace("Right", "Left")
            return r
        bones, _ = rig(swapped)
        m = B.automap(bones, Q)
        B.fix_sides_by_toes(bones, m)
        self.assertTrue(m.swapped_sides)
        self.assertEqual(m.slots["hand_l"]["bone"], "mixamorig:RightHand")

    def test_orientation_identity_for_mannequin_pose(self):
        bones, _ = rig(mixamo)
        m = B.automap(bones, Q)
        R = B.orientation(bones, m, left_sign=LEFT_X)
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(R[i][j], 1.0 if i == j else 0.0, places=3)

    def test_orientation_rotated_model(self):
        bones, _ = rig(mixamo)
        rot = [{**b, "head": [b["head"][0], -b["head"][2], b["head"][1]]} for b in bones]   # lay it down: Y-up exporter
        m = B.automap(rot, Q)
        R = B.orientation(rot, m, left_sign=LEFT_X)
        for b in rot:
            got = B.apply_rot(R, b["head"])
            want = next(x for x in bones if x["name"] == b["name"])["head"]
            for a, c in zip(got, want):
                self.assertAlmostEqual(a, c, places=3)

    def test_weight_map_folds_to_ancestor(self):
        bones, _ = rig(mixamo)
        bones.append({"name": "hair_01", "parent": "mixamorig:Head", "weighted": True, "head": [0, 0, 1.7]})
        bones.append({"name": "sleeve", "parent": "mixamorig:LeftForeArm", "weighted": True, "head": [0, 0, 1.2]})
        w = B.weight_map(bones, B.automap(bones, Q))
        self.assertEqual(w["hair_01"], "head")
        self.assertEqual(w["sleeve"], "lowerarm_l")

    def test_jiggle_helpers(self):
        bones, _ = rig(biped)
        bones += [{"name": "Bone_L_Breast_001", "parent": "Bip001 Spine2", "weighted": True, "head": [0.1, 0, 1.3]},
                  {"name": "Bone_R_Breast_001", "parent": "Bip001 Spine2", "weighted": True, "head": [-0.1, 0, 1.3]},
                  {"name": "Bone_L_Hip", "parent": "Bip001 Pelvis", "weighted": True, "head": [0.1, 0.1, 0.9]},
                  {"name": "Bone_R_Hip", "parent": "Bip001 Pelvis", "weighted": True, "head": [-0.1, 0.1, 0.9]}]
        m = B.automap(bones, Q)
        self.assertEqual(m.slots["jiggle_breast_l"]["bone"], "Bone_L_Breast_001")
        self.assertEqual(m.slots["jiggle_glute_r"]["bone"], "Bone_R_Hip")

    def test_missing_fingers_and_toes_still_maps_core(self):
        bones, _ = rig(mixamo)
        bones = [b for b in bones if "Hand" not in b["name"] or b["name"].endswith("Hand")]
        bones = [b for b in bones if "Toe" not in b["name"]]
        m = B.automap(bones, Q)
        self.assertFalse(m.errors, m.errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
