"""Skin the ORIGINAL Kalina meshes onto the default mannequin's skeleton (names, hierarchy and bone frames of
SK_Mannequin), so the template's animation Blueprint drives her unchanged.

blender -b -P kalina_on_mannequin.py -- <original.fbx> <out.fbx> [test_render_dir]

No vertex of the mesh is edited except by the two honest steps below:
  1. her arms are rotated to the mannequin's A-pose directions (so the stock animations land correctly), and
  2. the model is scaled to centimetres.
Skin weights are merged from her Bip001 bones onto the mannequin bones by name.
"""
import json
import math
import os
import re
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kalina_original_common as K  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
src_fbx, out_fbx = argv[:2]
test_dir = argv[2] if len(argv) > 2 else None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QJSON = os.path.join(ROOT, "avatar_source", "mannequin_skeleton.json")

# ---- the mannequin, expressed in Blender coordinates (measured round trip: y is mirrored) ---------------------
S3 = Matrix.Diagonal((1, -1, 1))


def to_blender_pos(p):
    return Vector((p[0], -p[1], p[2]))


def to_blender_rot(q):  # UE quaternion (x, y, z, w) -> 3x3 in Blender coordinates
    return S3 @ Quaternion((q[3], q[0], q[1], q[2])).normalized().to_matrix() @ S3


qdata = json.load(open(QJSON))
Q = {}
ORDER = []
for b in qdata["bones"]:
    Q[b["name"]] = {"parent": None if b["parent"] in ("None", "") else b["parent"],
                    "pos": to_blender_pos(b["pos"]), "rot": to_blender_rot(b["quat"])}
    ORDER.append(b["name"])
print("mannequin bones:", len(ORDER))

# ---- Kalina, cleaned (upright, rest pose, metres) ------------------------------------------------------------
arm, meshes, actions = K.load_clean(src_fbx)
for a in list(actions):
    bpy.data.actions.remove(a)
bpy.context.view_layer.update()


def head_w(name):
    bpy.context.view_layer.update()
    return arm.matrix_world @ arm.pose.bones[name].head


def aim(bone, cur_dir, tgt_dir):
    pb = arm.pose.bones[bone]
    rot = cur_dir.normalized().rotation_difference(tgt_dir.normalized()).to_matrix().to_4x4()
    h = arm.matrix_world @ pb.head
    m = Matrix.Translation(h) @ rot @ Matrix.Translation(-h)
    pb.matrix = arm.matrix_world.inverted() @ (m @ (arm.matrix_world @ pb.matrix))
    bpy.context.view_layer.update()


# 1. match her arm directions to the mannequin's (leaves legs, spine and head exactly as she is)
for s, sfx in (("L", "_l"), ("R", "_r")):
    up, fo, ha = "Bip001 %s UpperArm" % s, "Bip001 %s Forearm" % s, "Bip001 %s Hand" % s
    aim(up, head_w(fo) - head_w(up), Q["lowerarm" + sfx]["pos"] - Q["upperarm" + sfx]["pos"])
    aim(fo, head_w(ha) - head_w(fo), Q["hand" + sfx]["pos"] - Q["lowerarm" + sfx]["pos"])
    aim(ha, head_w("Bip001 %s Finger2" % s) - head_w(ha), Q["middle_01" + sfx]["pos"] - Q["hand" + sfx]["pos"])

# bake that pose in as the rest pose (deforming the meshes with it), then re-add the modifiers
for m in meshes:
    bpy.context.view_layer.objects.active = m
    bpy.ops.object.modifier_apply(modifier=[x for x in m.modifiers if x.type == "ARMATURE"][0].name)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="POSE")
bpy.ops.pose.select_all(action="SELECT")
bpy.ops.pose.armature_apply(selected=False)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.context.view_layer.update()

# Kalina's posed rest joints, in centimetres
KH = {b.name: (arm.matrix_world @ b.head_local) * 100.0 for b in arm.data.bones}
for m in meshes:
    m.data.transform(Matrix.Scale(100.0, 4))
    m.data.update()

# ---- skin-weight merge: Bip001 bones -> mannequin bones --------------------------------------------------------
FING = {"0": "thumb", "1": "index", "2": "middle", "3": "ring", "4": "pinky"}
HEAD_PREFIX = ("Bone_Hair", "Root_Hair", "Bip001 L_Ear", "Bip001 R_Ear", "Bone_L_Ear", "Bone_R_Ear", "Bone_L_Eye",
               "Bone_R_Eye", "Bone_L_High", "Bone_R_High", "Bip001 Head")
LIMB = {"Clavicle": "clavicle", "UpperArm": "upperarm", "Forearm": "lowerarm", "ForeTwist": "lowerarm_twist_01",
        "Hand": "hand", "Thigh": "thigh", "Calf": "calf", "Foot": "foot", "Toe0": "ball"}


def kmap(n):
    m = re.match(r"Bone_([LR])_Breast_00[12]$", n)
    if m:
        return "jiggle_breast_%s" % m.group(1).lower()
    m = re.match(r"Bone_([LR])_Hip$", n)
    if m:
        return "jiggle_glute_%s" % m.group(1).lower()
    if n in ("Bip001", "Bip001 Pelvis") or n.startswith(("Root_L_Hip", "Bone_L_Hip", "Root_R_Hip", "Bone_R_Hip")):
        return "pelvis"
    fixed = {"Bip001 Spine": "spine_01", "Bip001 Spine1": "spine_03", "Bip001 Spine2": "spine_05",
             "Bip001 Neck": "neck_01", "Bone_Neck_Twist": "neck_02"}
    if n in fixed:
        return fixed[n]
    if "Breast" in n:
        return "spine_04"
    if n.startswith(HEAD_PREFIX):
        return "head"
    m = re.match(r"Bip001 ([LR]) (Clavicle|UpperArm|Forearm|ForeTwist|Hand|Thigh|Calf|Foot|Toe0)$", n)
    if m:
        return "%s_%s" % (LIMB[m.group(2)], m.group(1).lower())
    m = re.match(r"Bip001 ([LR])ThighTwist$", n)
    if m:
        return "thigh_twist_01_%s" % m.group(1).lower()
    m = re.match(r"Bip001 ([LR]) Finger(\d)(\d?)$", n)
    if m:
        seg = 1 if not m.group(3) else int(m.group(3)) + 1
        return "%s_0%d_%s" % (FING[m.group(2)], seg, m.group(1).lower())
    m = re.match(r"Bone_([LR])_Knee$|Root_([LR])_CalfShape$|Bone_([LR])_CalfShape$", n)
    if m:
        return "calf_%s" % (m.group(1) or m.group(2) or m.group(3)).lower()
    m = re.match(r"Bone_([LR])_Elbow$", n)
    if m:
        return "lowerarm_%s" % m.group(1).lower()
    m = re.match(r"Bone_([LR])_UpperArm_00\d$", n)
    if m:
        return "upperarm_twist_01_%s" % m.group(1).lower()
    m = re.match(r"Bone_([LR])_Wrist_00\d$", n)
    if m:
        return "lowerarm_twist_02_%s" % m.group(1).lower()
    return None


parent_of = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}


def kmap_resolved(n):
    seen = n
    while seen:
        r = kmap(seen)
        if r:
            return r
        seen = parent_of.get(seen)
    return "pelvis"


unmapped = sorted({g.name for m in meshes for g in m.vertex_groups if kmap(g.name) is None})
print("groups folded into their parent's mapping:", unmapped)
stats = {"max_infl": 0, "zero": 0}
JIG = {}   # jiggle bone -> [weighted position sum, weight sum], in cm
for m in meshes:
    names = {g.index: g.name for g in m.vertex_groups}
    per_vertex = []
    for v in m.data.vertices:
        acc = {}
        for ge in v.groups:
            tgt = kmap_resolved(names[ge.group])
            acc[tgt] = acc.get(tgt, 0.0) + ge.weight
        top = sorted(acc.items(), key=lambda kv: -kv[1])[:8]
        tot = sum(w for _, w in top)
        if tot <= 1e-6:
            stats["zero"] += 1
            top, tot = [("pelvis", 1.0)], 1.0
        per_vertex.append([(n, w / tot) for n, w in top])
        stats["max_infl"] = max(stats["max_infl"], len(top))
    for g in list(m.vertex_groups):
        m.vertex_groups.remove(g)
    groups = {}
    for vi, lst in enumerate(per_vertex):
        for n, w in lst:
            if n not in groups:
                groups[n] = m.vertex_groups.new(name=n)
            groups[n].add([vi], w, "REPLACE")
            if n.startswith("jiggle_"):
                acc = JIG.setdefault(n, [Vector(), 0.0])
                acc[0] += m.data.vertices[vi].co * w
                acc[1] += w
print("weights: max influences per vertex = %d, vertices with no weight (sent to pelvis) = %d" % (
    stats["max_infl"], stats["zero"]))

# ---- where each mannequin bone goes in Kalina's body --------------------------------------------------------------
P = {}
DIRECT = {"pelvis": "Bip001 Pelvis", "clavicle": "Clavicle", "upperarm": "UpperArm", "lowerarm": "Forearm",
          "hand": "Hand", "thigh": "Thigh", "calf": "Calf", "foot": "Foot", "ball": "Toe0"}
P["root"] = Q["root"]["pos"].copy()
P["pelvis"] = KH["Bip001 Pelvis"].copy()
P["head"] = KH["Bip001 Head"].copy()
for s, sfx in (("L", "_l"), ("R", "_r")):
    for qn in ("clavicle", "upperarm", "lowerarm", "hand", "thigh", "calf", "foot", "ball"):
        P[qn + sfx] = KH["Bip001 %s %s" % (s, DIRECT[qn])].copy()
    for fi, fname in FING.items():
        for seg, suffix in ((1, ""), (2, "1"), (3, "2")):
            P["%s_0%d%s" % (fname, seg, sfx)] = KH["Bip001 %s Finger%s%s" % (s, fi, suffix)].copy()

# spine / neck: place by height along her own pelvis -> neck -> head line, using the mannequin's proportions
poly = [KH[n] for n in ("Bip001 Pelvis", "Bip001 Spine", "Bip001 Spine1", "Bip001 Spine2", "Bip001 Neck", "Bip001 Head")]
zq0, zq1 = Q["pelvis"]["pos"].z, Q["head"]["pos"].z
for qn in ("spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "neck_01", "neck_02"):
    t = (Q[qn]["pos"].z - zq0) / (zq1 - zq0)
    z = poly[0].z + t * (poly[-1].z - poly[0].z)
    for a, b in zip(poly, poly[1:]):
        if a.z <= z <= b.z or b.z <= z <= a.z:
            f = 0.0 if abs(b.z - a.z) < 1e-6 else (z - a.z) / (b.z - a.z)
            P[qn] = a.lerp(b, f)
            break
    else:
        P[qn] = poly[-1].copy()


def between(qn, qa, qb):
    """Position on the segment between two already-placed bones, at the same fraction as on the mannequin."""
    a, b = Q[qa]["pos"], Q[qb]["pos"]
    d = b - a
    f = 0.5 if d.length_squared < 1e-9 else max(0.0, min(1.0, (Q[qn]["pos"] - a).dot(d) / d.length_squared))
    P[qn] = P[qa].lerp(P[qb], f)


for sfx in ("_l", "_r"):
    for i in (1, 2):
        between("upperarm_twist_0%d%s" % (i, sfx), "upperarm" + sfx, "lowerarm" + sfx)
        between("lowerarm_twist_0%d%s" % (i, sfx), "lowerarm" + sfx, "hand" + sfx)
        between("thigh_twist_0%d%s" % (i, sfx), "thigh" + sfx, "calf" + sfx)
        between("calf_twist_0%d%s" % (i, sfx), "calf" + sfx, "foot" + sfx)
    for fname in ("index", "middle", "ring", "pinky"):
        between("%s_metacarpal%s" % (fname, sfx), "hand" + sfx, "%s_01%s" % (fname, sfx))
    P["ik_hand_" + sfx[1:]] = P["hand" + sfx].copy()
    P["ik_foot_" + sfx[1:]] = Vector((P["foot" + sfx].x, P["foot" + sfx].y, 0.0))
P["ik_foot_root"] = Q["ik_foot_root"]["pos"].copy()
P["ik_hand_root"] = Q["ik_hand_root"]["pos"].copy()
P["ik_hand_gun"] = P["hand_r"].copy()
P["interaction"] = Q["interaction"]["pos"].copy()
P["center_of_mass"] = Vector((P["pelvis"].x, P["pelvis"].y, P["pelvis"].z))
missing = [n for n in ORDER if n not in P]
print("bones without a position:", missing)
assert not missing

# ---- build the skeleton: mannequin names, hierarchy and FRAMES, at Kalina's joints ------------------------------
us = bpy.context.scene.unit_settings
us.system, us.scale_length, us.length_unit = "METRIC", 0.01, "CENTIMETERS"
new_data = bpy.data.armatures.new("Armature")
new_arm = bpy.data.objects.new("Armature", new_data)
bpy.context.scene.collection.objects.link(new_arm)
bpy.context.view_layer.objects.active = new_arm
bpy.ops.object.mode_set(mode="EDIT")
eb_map = {}
for qn in ORDER:
    eb = new_data.edit_bones.new(qn)
    eb.head = P[qn]
    eb.tail = P[qn] + Vector((0, 3, 0))
    M = Q[qn]["rot"].to_4x4()
    M.translation = P[qn]
    eb.matrix = M
    if Q[qn]["parent"]:
        eb.parent = eb_map[Q[qn]["parent"]]
    eb_map[qn] = eb

JIGGLE_PARENT = {"jiggle_breast_l": "spine_05", "jiggle_breast_r": "spine_05",
                 "jiggle_glute_l": "pelvis", "jiggle_glute_r": "pelvis"}
for jn, parent in JIGGLE_PARENT.items():
    centre = JIG[jn][0] / JIG[jn][1]
    eb = new_data.edit_bones.new(jn)
    eb.head = centre
    eb.tail = centre + Vector((0, 3, 0))
    M = Q[parent]["rot"].to_4x4()
    M.translation = centre
    eb.matrix = M
    eb.parent = eb_map[parent]
    eb_map[jn] = eb
    print("jiggle bone %-16s parent=%-9s at (blender cm) %s  weight mass=%.0f" % (
        jn, parent, tuple(round(v, 1) for v in centre), JIG[jn][1]))
bpy.ops.object.mode_set(mode="OBJECT")

worst = 0.0
for qn in ORDER:
    got = new_data.bones[qn].matrix_local.to_3x3()
    worst = max(worst, max(abs(got[i][j] - Q[qn]["rot"][i][j]) for i in range(3) for j in range(3)))
print("bone frames: worst matrix deviation from the mannequin's = %.2e" % worst)

# ---- hook the meshes up to the new skeleton, drop the old one ----------------------------------------------------
for m in meshes:
    # (applying the pose above consumed the old Armature modifier; skinning needs a fresh one on the new skeleton)
    mods = [x for x in m.modifiers if x.type == "ARMATURE"]
    mod = mods[0] if mods else m.modifiers.new("Armature", "ARMATURE")
    mod.object = new_arm
    m.parent = new_arm
    m.matrix_parent_inverse = Matrix.Identity(4)
    print("skin: %s -> %d vertex groups, modifier=%s" % (m.name, len(m.vertex_groups), mod.name))
bpy.data.objects.remove(arm, do_unlink=True)

# ---- optional: pose it and look, before trusting it -------------------------------------------------------------
if test_dir:
    os.makedirs(test_dir, exist_ok=True)
    scn = bpy.context.scene
    scn.render.engine = "BLENDER_WORKBENCH"
    scn.render.resolution_x = scn.render.resolution_y = 700
    scn.display.shading.light = "STUDIO"
    scn.display.shading.color_type = "OBJECT"
    for m, col in zip(meshes, ((0.7, 0.55, 0.45, 1), (0.8, 0.7, 0.6, 1), (0.8, 0.8, 0.85, 1))):
        m.color = col
    cam_d = bpy.data.cameras.new("c")
    cam_d.type, cam_d.ortho_scale = "ORTHO", 230
    cam = bpy.data.objects.new("c", cam_d)
    scn.collection.objects.link(cam)
    scn.camera = cam

    def swing(bone, axis, deg):
        pb = new_arm.pose.bones[bone]
        h = new_arm.matrix_world @ pb.head
        r = Matrix.Rotation(math.radians(deg), 4, axis)
        pb.matrix = new_arm.matrix_world.inverted() @ (Matrix.Translation(h) @ r @ Matrix.Translation(-h) @ (new_arm.matrix_world @ pb.matrix))
        bpy.context.view_layer.update()

    def shoot(tag):
        for name, rot, loc in (("front", (math.radians(90), 0, 0), (0, -600, 95)), ("side", (math.radians(90), 0, math.radians(90)), (600, 0, 95))):
            cam.location, cam.rotation_euler = loc, rot
            scn.render.filepath = os.path.join(test_dir, "%s_%s.png" % (tag, name))
            bpy.ops.render.render(write_still=True)

    shoot("rest")
    swing("upperarm_l", "Y", 70)       # raise the left arm sideways
    swing("upperarm_r", "Y", -35)
    swing("thigh_l", "X", -50)         # kick the left leg forward
    swing("calf_l", "X", 70)           # bend the knee
    swing("spine_03", "X", 18)         # lean
    swing("head", "Z", 25)
    shoot("posed")

bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
for pb in new_arm.pose.bones:
    pb.location, pb.rotation_quaternion, pb.rotation_euler, pb.scale = (0, 0, 0), (1, 0, 0, 0), (0, 0, 0), (1, 1, 1)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.fbx(
    filepath=out_fbx, use_selection=True, object_types={"ARMATURE", "MESH"}, add_leaf_bones=False, bake_anim=False,
    apply_scale_options="FBX_SCALE_NONE", path_mode="STRIP", axis_forward="-Z", axis_up="Y",
    mesh_smooth_type="FACE", use_tspace=True)
print("WROTE", out_fbx)
