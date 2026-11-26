"""Re-skin any humanoid onto the default Unreal mannequin skeleton (names, hierarchy and bone FRAMES of SK_Mannequin).

blender -b -P convert_model.py -- job.json

job: {
  "source", "armature" (opt), "out_fbx", "out_dir",
  "mannequin": path to mannequin_skeleton.json,
  "rotation": 3x3 (upright, facing -Y, left on the mannequin's left),
  "scale": source units -> centimetres,
  "mapping": {mannequin bone: source bone},          # joints found in the model (from bonemap.automap, possibly edited)
  "weight_map": {source bone: mannequin bone},       # where each source bone's skin weights go
  "parts": {mesh name: bool},                        # overrides for which meshes belong to the character
  "materials": [{name, base, ...}],                  # only used for the preview renders
  "preview": bool, "pose_arms": bool
}

What it does to the model:
  * skinned meshes: skin weights are merged by bone name onto the mannequin's bones;
  * meshes with NO skin weights (a static body): a mannequin-shaped skeleton is fitted to the body and the weights are
    computed automatically (bone-heat), with a nearest-bone fallback for anything the solver misses;
  * bones the model does not have (legs, hands, fingers of a partial rig) are placed by the mannequin's proportions;
  * the arms are rotated to the mannequin's A-pose directions (so the stock animations land correctly), and the model is
    scaled to centimetres. No other vertex is edited.
Every mannequin bone keeps the mannequin's own frame.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils.geometry import intersect_point_line

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import af_common as C  # noqa: E402
from reshape_body import reshape_reference_body  # noqa: E402

job, _ = C.job_from_argv()
out_dir = job["out_dir"]
os.makedirs(out_dir, exist_ok=True)
MAP = {k: (v["bone"] if isinstance(v, dict) else v) for k, v in job["mapping"].items()}
WMAP = job["weight_map"]
SCALE = float(job["scale"])
report = {"warnings": [], "stats": {}}

# ---- the mannequin, in Blender coordinates (measured round trip: y is mirrored) --------------------------------
S3 = Matrix.Diagonal((1, -1, 1))
qdata = json.load(open(job["mannequin"]))
Q, ORDER = {}, []
for b in qdata["bones"]:
    q = b["quat"]
    Q[b["name"]] = {"parent": None if b["parent"] in ("None", "") else b["parent"],
                    "pos": Vector((b["pos"][0], -b["pos"][1], b["pos"][2])),
                    "rot": S3 @ Quaternion((q[3], q[0], q[1], q[2])).normalized().to_matrix() @ S3}
    ORDER.append(b["name"])

SPECIAL = ("spine_", "neck_", "jiggle_", "lowerarm_twist", "upperarm_twist", "thigh_twist", "calf_twist", "ik_", "interaction",
           "center_of_mass", "root")
LEG = ("thigh", "calf", "foot", "ball")
ARM = ("upperarm", "lowerarm", "hand", "thumb", "index", "middle", "ring", "pinky", "clavicle")
DEFORM = [n for n in ORDER if not n.startswith(("ik_", "interaction", "center_of_mass", "root"))
          and "twist" not in n and "metacarpal" not in n]

# ---- load, filter parts, orient, scale to centimetres ---------------------------------------------------------------
arm, meshes, notes = C.load_generic(job["source"], job.get("armature"), job.get("parts"))
report["warnings"] += notes
report["parts"] = C.load_generic.last_parts
C.rotate_all(arm, meshes, job["rotation"])
C.scale_all(arm, meshes, SCALE)          # everything below is in centimetres
lo, hi = C.mesh_bounds(meshes)
FLOOR = lo[2]
# the model exactly as authored (upright, in cm): the reference for the 1:1 check at the end
ORIG = {m.name: [v.co.copy() for v in m.data.vertices] for m in meshes}
report["stats"]["source_height_units"] = (hi[2] - lo[2]) / SCALE


def aim(obj, bone, cur_dir, tgt_dir):
    pb = obj.pose.bones[bone]
    rot = cur_dir.normalized().rotation_difference(tgt_dir.normalized()).to_matrix().to_4x4()
    h = obj.matrix_world @ pb.head
    m = Matrix.Translation(h) @ rot @ Matrix.Translation(-h)
    pb.matrix = obj.matrix_world.inverted() @ (m @ (obj.matrix_world @ pb.matrix))
    bpy.context.view_layer.update()


def head_w(obj, name):
    bpy.context.view_layer.update()
    return obj.matrix_world @ obj.pose.bones[name].head


ARM_ANGLE = job.get("arm_angle")        # degrees below horizontal for the upper arms, or None = the mannequin's own arm directions


def a_pose(obj, names):
    """names: slot -> bone name on obj. Rotate the arms: to ARM_ANGLE below horizontal if set (only the upper arm turns; the
    forearm and hand follow, so the elbow bend is kept), else every segment to the mannequin's directions."""
    if ARM_ANGLE is not None:
        rad = math.radians(float(ARM_ANGLE))
        for sfx in ("_l", "_r"):
            try:
                up, fo = names["upperarm" + sfx], names["lowerarm" + sfx]
            except KeyError:
                report["warnings"].append("arm chain incomplete on side %s: arm angle step skipped there" % sfx)
                continue
            cur = head_w(obj, fo) - head_w(obj, up)
            hz = Vector((cur.x, cur.y, 0.0))
            if hz.length < 1e-4:
                continue
            tgt = hz.normalized() * math.cos(rad) + Vector((0.0, 0.0, -math.sin(rad)))
            aim(obj, up, cur, tgt)
        return
    for sfx in ("_l", "_r"):
        try:
            up, fo, ha = (names[b + sfx] for b in ("upperarm", "lowerarm", "hand"))
        except KeyError:
            report["warnings"].append("arm chain incomplete on side %s: A-pose step skipped there" % sfx)
            continue
        aim(obj, up, head_w(obj, fo) - head_w(obj, up), Q["lowerarm" + sfx]["pos"] - Q["upperarm" + sfx]["pos"])
        aim(obj, fo, head_w(obj, ha) - head_w(obj, fo), Q["hand" + sfx]["pos"] - Q["lowerarm" + sfx]["pos"])
        mid = names.get("middle_01" + sfx)
        if mid:
            aim(obj, ha, head_w(obj, mid) - head_w(obj, ha), Q["middle_01" + sfx]["pos"] - Q["hand" + sfx]["pos"])


def bake_pose(obj, mesh_list):
    """Take the current pose as the rest pose, deforming the given meshes with it."""
    for m in mesh_list:
        bpy.context.view_layer.objects.active = m
        mods = [x for x in m.modifiers if x.type == "ARMATURE" and x.object == obj]
        if mods:
            bpy.ops.object.modifier_apply(modifier=mods[0].name)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()


# ---- joint placement ---------------------------------------------------------------------------------------------------
def place_joints(known, chain_pts):
    """Positions for EVERY mannequin bone. `known`: mannequin bone -> Vector (joints really found in the model).
    `chain_pts`: the model's own joints between pelvis and head (for the spine and neck bones).
    Bones the model lacks are placed from the mannequin's offsets, scaled to this body: torso proportions for the trunk,
    the leg length (pelvis height above the floor) for the legs, the arm length for the arms."""
    P = {k: v.copy() for k, v in known.items()}
    P["root"] = Q["root"]["pos"].copy()
    pel, head = P["pelvis"], P["head"]
    body = (head.z - pel.z) / max(Q["head"]["pos"].z - Q["pelvis"]["pos"].z, 1e-6)
    qfoot = min(Q["ball_l"]["pos"].z, Q["ball_r"]["pos"].z)
    leg = max(pel.z - FLOOR, 1.0) / max(Q["pelvis"]["pos"].z - qfoot, 1e-6)
    if "upperarm_l" in P and "lowerarm_l" in P:
        armr = (P["upperarm_l"] - P["lowerarm_l"]).length / max((Q["upperarm_l"]["pos"] - Q["lowerarm_l"]["pos"]).length, 1e-6)
    else:
        armr = body
    ratios = {"body": body, "leg": leg, "arm": armr}

    # spine / neck: along this body's own pelvis -> ... -> head line, at the mannequin's height fractions
    poly = [pel] + sorted(chain_pts, key=lambda v: v.z) + [head]
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

    def derive(qn):
        par = Q[qn]["parent"]
        if not par or par not in P:
            return False
        off = Q[qn]["pos"] - Q[par]["pos"]
        base = qn.split("_")[0]
        if base in LEG:
            off = Vector((off.x * body, off.y * body, off.z * leg))
        elif base in ARM:
            off = off * armr
        else:
            off = off * body
        P[qn] = P[par] + off
        return True

    missing = []
    for qn in ORDER:
        if qn in P or qn.startswith(("ik_", "interaction", "center_of_mass", "root")):
            continue
        if "twist" in qn or "metacarpal" in qn:
            continue
        if not derive(qn):
            P[qn] = P["pelvis"] + (Q[qn]["pos"] - Q["pelvis"]["pos"]) * body
        if qn not in known:
            missing.append(qn)

    def between(qn, qa, qb):
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
        for f in ("index", "middle", "ring", "pinky"):
            between("%s_metacarpal%s" % (f, sfx), "hand" + sfx, "%s_01%s" % (f, sfx))
        P["ik_hand_" + sfx[1:]] = P["hand" + sfx].copy()
        P["ik_foot_" + sfx[1:]] = Vector((P["foot" + sfx].x, P["foot" + sfx].y, 0.0))
    P["ik_foot_root"] = Q["ik_foot_root"]["pos"].copy()
    P["ik_hand_root"] = Q["ik_hand_root"]["pos"].copy()
    P["ik_hand_gun"] = P["hand_r"].copy()
    P["interaction"] = Q["interaction"]["pos"].copy()
    P["center_of_mass"] = Vector(P["pelvis"])
    return P, missing, ratios


def chain_points(KH):
    return [KH[MAP[s]] for s in ("spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "neck_01", "neck_02")
            if s in MAP and MAP[s] in KH]


def known_from(KH):
    return {slot: KH[src].copy() for slot, src in MAP.items() if slot in Q and src in KH and not slot.startswith(SPECIAL)}


def make_armature(name, P, bones):
    """An armature with the given mannequin bones at P, with proper tails (towards the child) so heat weighting sees real
    bone segments instead of stubs."""
    data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    have = set(bones)

    def deform_parent(n):
        p = Q[n]["parent"]
        while p and p not in have:
            p = Q[p]["parent"]
        return p

    kids = {}
    for n in bones:
        kids.setdefault(deform_parent(n), []).append(n)
    ebs = {}
    for n in bones:
        eb = data.edit_bones.new(n)
        eb.head = P[n]
        ch = kids.get(n, [])
        if ch:
            tgt = max((P[c] for c in ch), key=lambda v: (v - P[n]).length)       # the chain that continues furthest
            tail = tgt if (tgt - P[n]).length > 1.0 else P[n] + Vector((0, 0, 4))
        else:
            par = deform_parent(n)
            d = (P[n] - P[par]) if par else Vector((0, 0, 1))
            d = d.normalized() if d.length > 1e-6 else Vector((0, 0, 1))
            tail = P[n] + Vector((0, 0, 14)) if n == "head" else P[n] + d * 4.0
        eb.tail = tail
        ebs[n] = eb
    for n in bones:
        p = deform_parent(n)
        if p:
            ebs[n].parent = ebs[p]
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


# ---- 0. meshes with no skin weights: fit a skeleton, auto-weight, pose ------------------------------------------------------
static = [m for m in meshes if len(m.vertex_groups) == 0]
skinned = [m for m in meshes if m not in static]
bpy.context.view_layer.update()
KH0 = {b.name: arm.matrix_world @ b.head_local for b in arm.data.bones}
TMP_JOINTS = {}
PREMAPPED = set()
BF = job.get("body_from")
if static:
    report["warnings"].append("%d mesh(es) had no skin weights (%s): rigged automatically" % (len(static), ", ".join(m.name for m in static)))
    if "pelvis" not in MAP or "head" not in MAP:
        raise RuntimeError("pelvis and head must be mapped to rig a static body")
    P0, _, _ = place_joints(known_from(KH0), chain_points(KH0))
    tmp = make_armature("AF_tmp", P0, DEFORM)
    # Heat weighting treats every UV/normal-split shell as a separate solid, so vertices that sit at the same spot but were
    # split (seams) get different weights and tear apart when posed. Weight a WELDED copy instead, then give every original
    # vertex the weights of its welded twin.
    import bmesh
    from mathutils import kdtree
    for m in static:
        w = m.copy()
        w.data = m.data.copy()
        bpy.context.scene.collection.objects.link(w)
        for mod in list(w.modifiers):
            w.modifiers.remove(mod)
        bm = bmesh.new()
        bm.from_mesh(w.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-3)      # 0.01 mm (the model is in cm)
        bm.to_mesh(w.data)
        bm.free()
        bpy.ops.object.select_all(action="DESELECT")
        w.select_set(True)
        tmp.select_set(True)
        bpy.context.view_layer.objects.active = tmp
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        wnames = {g.index: g.name for g in w.vertex_groups}
        kd = kdtree.KDTree(len(w.data.vertices))
        for v in w.data.vertices:
            kd.insert(v.co, v.index)
        kd.balance()
        for g in list(m.vertex_groups):
            m.vertex_groups.remove(g)
        mgroups = {}
        for v in m.data.vertices:
            _, wi, _ = kd.find(v.co)
            for ge in w.data.vertices[wi].groups:
                n = wnames[ge.group]
                if ge.weight > 1e-4:
                    (mgroups.get(n) or mgroups.setdefault(n, m.vertex_groups.new(name=n))).add([v.index], ge.weight, "REPLACE")
        report["stats"]["static_welded_vertices"] = report["stats"].get("static_welded_vertices", 0) + (len(m.data.vertices) - len(w.data.vertices))
        bpy.data.objects.remove(w, do_unlink=True)
        mod = m.modifiers.new("Armature", "ARMATURE")
        mod.object = tmp
        m.parent = tmp
    # anything the heat solver left without weight: nearest bone segment
    seg = [(n, tmp.data.bones[n].head_local.copy(), tmp.data.bones[n].tail_local.copy()) for n in DEFORM]

    def seg_dist(co, a, b):
        pt, f = intersect_point_line(co, a, b)
        pt = a if f < 0 else b if f > 1 else pt
        return (co - pt).length

    unweighted = 0
    for m in static:
        names = {g.index: g.name for g in m.vertex_groups}
        for v in m.data.vertices:
            if sum(ge.weight for ge in v.groups if names.get(ge.group) in DEFORM) > 1e-4:
                continue
            unweighted += 1
            best = min(seg, key=lambda s: seg_dist(v.co, s[1], s[2]))
            (m.vertex_groups.get(best[0]) or m.vertex_groups.new(name=best[0])).add([v.index], 1.0, "REPLACE")
    report["stats"]["static_vertices"] = sum(len(m.data.vertices) for m in static)
    report["stats"]["static_vertices_fallback_weighted"] = unweighted
    C.log("auto-weights: %d static vertices, %d needed the nearest-bone fallback" % (report["stats"]["static_vertices"], unweighted))
    if job.get("pose_arms", True):
        a_pose(tmp, {k: k for k in DEFORM})
    bake_pose(tmp, static)
    TMP_JOINTS = {b.name: tmp.matrix_world @ b.head_local for b in tmp.data.bones}
    bpy.data.objects.remove(tmp, do_unlink=True)
    for m in static:
        m.parent = arm
        m.matrix_parent_inverse = Matrix.Identity(4)

EXT_PREFIX = ("hand_", "thumb_", "index_", "middle_", "ring_", "pinky_", "foot_", "ball_", "thigh_", "calf_")


def ext_weight(mesh, v, names):
    return sum(ge.weight for ge in v.groups if names.get(ge.group, "").startswith(EXT_PREFIX))


if BF and static:
    import bmesh
    spec_mats = {mt["name"]: mt for mt in job.get("materials", [])}
    target = max(static, key=lambda m: len(m.data.vertices))
    # the reference body, reshaped onto the target (hands and feet are NOT trusted: different anatomy)
    kb, ov = reshape_reference_body(BF, target, TMP_JOINTS or P0, spec_mats, Q, DEFORM, out_dir, C.log)
    # the reference loses its hands and feet ...
    kn = {g.index: g.name for g in kb.vertex_groups}
    bm = bmesh.new()
    bm.from_mesh(kb.data)
    drop = [v for v in bm.verts if ext_weight(kb, kb.data.vertices[v.index], kn) > 0.7]
    bmesh.ops.delete(bm, geom=drop, context="VERTS")
    bm.to_mesh(kb.data)
    bm.free()
    kb.data.update()
    # ... and the target keeps ONLY its own hands and feet (heat weights), nudged out a hair so they win the overlap band
    piece = target.copy()
    piece.data = target.data.copy()
    piece.name = "Hands_Feet_" + target.name
    bpy.context.scene.collection.objects.link(piece)
    tn = {g.index: g.name for g in piece.vertex_groups}
    bm = bmesh.new()
    bm.from_mesh(piece.data)
    drop = [v for v in bm.verts if ext_weight(piece, piece.data.vertices[v.index], tn) < 0.4]
    bmesh.ops.delete(bm, geom=drop, context="VERTS")
    bm.normal_update()
    for v in bm.verts:
        v.co += v.normal * 0.03
    bm.to_mesh(piece.data)
    bm.free()
    piece.data.update()
    for mod in list(piece.modifiers):
        piece.modifiers.remove(mod)
    static = [m for m in static if m is not target]
    meshes = [m for m in meshes if m is not target] + [kb, piece]
    bpy.data.objects.remove(target, do_unlink=True)
    PREMAPPED.update([kb.name, piece.name])
    report.setdefault("extra_materials", []).append(
        {"name": ov["material"], "base": ov["png"], "normal": None, "rough": None, "metal": None, "alpha_mode": "opaque",
         "two_sided": False, "class": "skin"})
    report["warnings"].append("body = reshaped reference body (its weights, UVs, jiggle) + the model's own hands, legs and feet")
skinned = [m for m in meshes if m not in static and m.name not in PREMAPPED]
# ---- 1. arms of the source skeleton to the mannequin's A-pose, bake into the skinned meshes ---------------------------------------
if skinned and job.get("pose_arms", True):
    a_pose(arm, MAP)
    bake_pose(arm, skinned)
bpy.context.view_layer.update()
KH = {b.name: arm.matrix_world @ b.head_local for b in arm.data.bones}

# ---- 2. skin weights of the skinned meshes: source bones -> mannequin bones ---------------------------------------------------------
stats = {"max_infl": 0, "zero": 0}
JIG = {}
for m in skinned:
    names = {g.index: g.name for g in m.vertex_groups}
    per_vertex = []
    for v in m.data.vertices:
        acc = {}
        for ge in v.groups:
            tgt = WMAP.get(names[ge.group], "pelvis")
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
for m in [x for x in meshes if x in static or x.name in PREMAPPED]:
    pn = {g.index: g.name for g in m.vertex_groups}
    for sv in m.data.vertices:
        stats["max_infl"] = max(stats["max_infl"], len(sv.groups))
        for ge in sv.groups:
            if pn[ge.group].startswith("jiggle_"):
                acc = JIG.setdefault(pn[ge.group], [Vector(), 0.0])
                acc[0] += sv.co * ge.weight
                acc[1] += ge.weight
report["stats"].update(max_influences=stats["max_infl"], vertices_without_weight=stats["zero"])
C.log("weights: max influences/vertex %d, vertices with no weight %d" % (stats["max_infl"], stats["zero"]))

# ---- 3. where each mannequin bone goes in this body ------------------------------------------------------------------------------------
known = known_from(KH)
for slot, v in TMP_JOINTS.items():          # joints the model lacks, from the fitted + posed temporary skeleton
    if slot not in known and slot in Q and not slot.startswith(SPECIAL):
        known[slot] = v.copy()
P, missing_slots, ratios = place_joints(known, chain_points(KH))
absent = sorted(s for s in missing_slots if s in DEFORM)
if absent:
    report["warnings"].append("not in the model, placed by proportions (%d bones): %s" % (len(absent), ", ".join(absent[:12]) + ("..." if len(absent) > 12 else "")))
report["stats"]["ratios"] = ratios
miss = [n for n in ORDER if n not in P]
if miss:
    raise RuntimeError("bones without a position: %s" % miss)

# ---- 4. build the skeleton: mannequin names, hierarchy and FRAMES, at this body's joints -----------------------------------------------------
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

JIGGLE_PARENT = {"jiggle_breast_l": "spine_05", "jiggle_breast_r": "spine_05", "jiggle_glute_l": "pelvis",
                 "jiggle_glute_r": "pelvis"}
# an unweighted jiggle bone sits at the mannequin-shaped default (breasts on the chest, glutes behind the pelvis)
DEFAULT_JIG = {"jiggle_breast_l": Vector((9.0, -9.0, 0.0)), "jiggle_breast_r": Vector((-9.0, -9.0, 0.0)),
               "jiggle_glute_l": Vector((9.0, 9.0, -6.0)), "jiggle_glute_r": Vector((-9.0, 9.0, -6.0))}
for jn, parent in JIGGLE_PARENT.items():
    if jn in JIG and JIG[jn][1] > 1e-6:
        centre = JIG[jn][0] / JIG[jn][1]
    else:
        centre = P[parent] + DEFAULT_JIG[jn] * ratios["body"]
    eb = new_data.edit_bones.new(jn)
    eb.head = centre
    eb.tail = centre + Vector((0, 3, 0))
    M = Q[parent]["rot"].to_4x4()
    M.translation = centre
    eb.matrix = M
    eb.parent = eb_map[parent]
    eb_map[jn] = eb
bpy.ops.object.mode_set(mode="OBJECT")

worst = 0.0
for qn in ORDER:
    got = new_data.bones[qn].matrix_local.to_3x3()
    worst = max(worst, max(abs(got[i][j] - Q[qn]["rot"][i][j]) for i in range(3) for j in range(3)))
report["stats"]["worst_frame_deviation"] = worst
C.log("bone frames: worst matrix deviation from the mannequin = %.2e" % worst)

# ---- 5. hook the meshes up to the new skeleton, drop the old one --------------------------------------------------------------------------
for m in meshes:
    mods = [x for x in m.modifiers if x.type == "ARMATURE"]
    mod = mods[0] if mods else m.modifiers.new("Armature", "ARMATURE")
    mod.object = new_arm
    m.parent = new_arm
    m.matrix_parent_inverse = Matrix.Identity(4)
bpy.data.objects.remove(arm, do_unlink=True)

# ---- 1:1 check: how far did every vertex move from where the model had it? --------------------------------------------------------------
moved, worst, total, sum_d, by_part = 0, 0.0, 0, 0.0, {}
for m in meshes:
    if m.name not in ORIG:          # a replacement body (reshaped reference) has no authored original to compare with
        continue
    pm = 0
    for v, o in zip(m.data.vertices, ORIG[m.name]):
        d = (v.co - o).length
        total += 1
        sum_d += d
        if d > 0.05:            # more than half a millimetre
            moved += 1
            pm += 1
        worst = max(worst, d)
    by_part[m.name] = pm
report["stats"]["shape_check"] = {"vertices": total, "moved_over_0.5mm": moved, "max_displacement_cm": worst,
                                   "mean_displacement_cm": sum_d / max(total, 1), "moved_by_mesh": by_part}
C.log("1:1 check: %d of %d vertices moved more than 0.5 mm (max %.2f cm); by mesh %s" % (moved, total, worst, by_part))

lo = [1e18] * 3
hi = [-1e18] * 3
for m in meshes:
    for v in m.data.vertices:
        for i in range(3):
            lo[i] = min(lo[i], v.co[i])
            hi[i] = max(hi[i], v.co[i])
report["stats"]["height_cm"] = hi[2] - lo[2]
report["stats"]["bounds_cm"] = {"min": lo, "max": hi}
report["stats"]["vertices"] = sum(len(m.data.vertices) for m in meshes)
report["stats"]["scale_cm_per_unit"] = SCALE
C.log("result height %.1f cm" % (hi[2] - lo[2]))

# ---- 6. previews: textured, rest pose and a test pose ------------------------------------------------------------------------------------------
if job.get("preview", True) and job.get("preview_dir"):
    pdir = job["preview_dir"]
    os.makedirs(pdir, exist_ok=True)
    scn = bpy.context.scene
    scn.render.engine = "BLENDER_WORKBENCH"
    scn.render.resolution_x, scn.render.resolution_y = 600, 800
    scn.render.film_transparent = False
    scn.display.shading.light = "STUDIO"
    scn.display.shading.color_type = "TEXTURE"
    scn.display.shading.background_type = "VIEWPORT"
    scn.display.shading.background_color = (0.16, 0.17, 0.2)
    if scn.world is None:
        scn.world = bpy.data.worlds.new("w")
    spec = {mt["name"]: mt for mt in job.get("materials", [])}
    for _em in report.get("extra_materials", []):
        spec[_em["name"]] = _em
    for _n, _ov in report.get("material_overrides", {}).items():     # e.g. a texture baked onto a replacement body
        spec[_n] = {**spec.get(_n, {}), **_ov}
    for m in meshes:
        for slot in m.material_slots:
            mat = slot.material
            if not mat or mat.name not in spec or not spec[mat.name].get("base"):
                continue
            mat.use_nodes = True
            nt = mat.node_tree
            nt.nodes.clear()
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
            tex = nt.nodes.new("ShaderNodeTexImage")
            try:
                tex.image = bpy.data.images.load(spec[mat.name]["base"], check_existing=True)
                nt.links.new(tex.outputs["Color"], bs.inputs["Base Color"])
                if spec[mat.name].get("alpha_mode") == "masked":
                    # a real cut-out: show the strands, hide the gaps (the same choice the Unreal import makes)
                    nt.links.new(tex.outputs["Alpha"], bs.inputs["Alpha"])
                    if hasattr(mat, "blend_method"):
                        mat.blend_method = "CLIP"
                    if hasattr(mat, "surface_render_method"):
                        mat.surface_render_method = "DITHERED"
                else:
                    # alpha is data (or absent): it must not make the mesh transparent
                    tex.image.alpha_mode = "NONE"
                    if hasattr(mat, "blend_method"):
                        mat.blend_method = "OPAQUE"
            except Exception:
                pass
            nt.links.new(bs.outputs["BSDF"], out.inputs["Surface"])
    cam_d = bpy.data.cameras.new("c")
    cam_d.type, cam_d.ortho_scale = "ORTHO", max(hi[2] - lo[2], 100) * 1.18
    cam = bpy.data.objects.new("c", cam_d)
    scn.collection.objects.link(cam)
    scn.camera = cam
    cz = (lo[2] + hi[2]) / 2

    def shoot(tag):
        views = {"front": ((math.radians(90), 0, 0), (0, -600, cz)),
                 "back": ((math.radians(90), 0, math.radians(180)), (0, 600, cz)),
                 "side": ((math.radians(90), 0, math.radians(90)), (600, 0, cz))}
        for name, (rot, loc) in views.items():
            cam.location, cam.rotation_euler = loc, rot
            scn.render.filepath = os.path.join(pdir, "%s_%s.png" % (tag, name))
            bpy.ops.render.render(write_still=True)

    def swing(bone, axis, deg):
        pb = new_arm.pose.bones[bone]
        h = new_arm.matrix_world @ pb.head
        r = Matrix.Rotation(math.radians(deg), 4, axis)
        pb.matrix = new_arm.matrix_world.inverted() @ (Matrix.Translation(h) @ r @ Matrix.Translation(-h) @ (new_arm.matrix_world @ pb.matrix))
        bpy.context.view_layer.update()

    shoot("rest")
    swing("upperarm_l", "Y", 70)
    swing("upperarm_r", "Y", -35)
    swing("thigh_l", "X", -50)
    swing("calf_l", "X", 70)
    swing("spine_03", "X", 18)
    swing("head", "Z", 25)
    cam.location, cam.rotation_euler = (0, -600, cz), (math.radians(90), 0, 0)
    scn.render.filepath = os.path.join(pdir, "posed_front.png")
    bpy.ops.render.render(write_still=True)
    C.log("previews written to " + pdir)

# ---- 7. export -------------------------------------------------------------------------------------------------------------------------------------
if bpy.context.object and bpy.context.object.mode != "OBJECT":
    bpy.ops.object.mode_set(mode="OBJECT")
for pb in new_arm.pose.bones:
    pb.location, pb.rotation_quaternion, pb.rotation_euler, pb.scale = (0, 0, 0), (1, 0, 0, 0), (0, 0, 0), (1, 1, 1)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.fbx(
    filepath=job["out_fbx"], use_selection=True, object_types={"ARMATURE", "MESH"}, add_leaf_bones=False, bake_anim=False,
    apply_scale_options="FBX_SCALE_NONE", path_mode="STRIP", axis_forward="-Z", axis_up="Y",
    mesh_smooth_type="FACE", use_tspace=True)
report["fbx"] = job["out_fbx"]
report["materials_used"] = sorted({s.material.name for m in meshes for s in m.material_slots if s.material})
with open(os.path.join(out_dir, "convert.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, indent=1)
C.log("CONVERT OK ->", job["out_fbx"])
