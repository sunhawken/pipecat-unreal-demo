"""Blender-side helpers shared by inspect.py and convert.py (run inside Blender: blender -b -P script -- job.json)."""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector


def job_from_argv():
    argv = sys.argv[sys.argv.index("--") + 1:]
    with open(argv[0], encoding="utf-8") as f:
        return json.load(f), argv[0]


def log(*a):
    print("AF:", *a, flush=True)


def import_model(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".blend":
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = src.objects
        for o in dst.objects:
            if o is not None:
                bpy.context.scene.collection.objects.link(o)
    elif ext == ".dae":
        bpy.ops.wm.collada_import(filepath=path)
    else:
        raise RuntimeError("unsupported format: " + ext + " (use .fbx, .glb, .gltf or .blend)")


def skinned_meshes(arm):
    out = []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        mods = [m for m in o.modifiers if m.type == "ARMATURE" and m.object == arm]
        if mods or (o.parent == arm and o.parent_type in ("OBJECT", "ARMATURE", "BONE")):
            out.append(o)
    return out


def pick_armature(prefer=None):
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not arms:
        raise RuntimeError("the file has no armature: it needs a skeleton (rigged humanoid)")
    if prefer:
        for a in arms:
            if a.name == prefer:
                return a

    def score(a):
        ms = skinned_meshes(a)
        names = {g.name for m in ms for g in m.vertex_groups}
        return (len(names & {b.name for b in a.data.bones}), len(a.data.bones))
    return max(arms, key=score)


def _bbox(o):
    ws = [o.matrix_world @ v.co for v in o.data.vertices]
    return [min(w[i] for w in ws) for i in range(3)], [max(w[i] for w in ws) for i in range(3)]


def choose_parts(meshes, override=None):
    """Decide which meshes belong to the character. Returns (kept, report). Rules: exact duplicates are dropped (keeping the
    skinned copy), parts far from the body (a prop left at the origin of another scene) are dropped, tiny unskinned bits lying on
    the floor (ground decals) are dropped. `override` {name: bool} wins over the rules."""
    override = override or {}
    info = {}
    for m in meshes:
        lo, hi = _bbox(m)
        info[m.name] = {"o": m, "lo": lo, "hi": hi, "skinned": len(m.vertex_groups) > 0, "verts": len(m.data.vertices),
                        "faces": len(m.data.polygons), "mats": tuple(s.material.name for s in m.material_slots if s.material)}
    why = {}
    seen = {}
    for n, i in sorted(info.items(), key=lambda kv: (not kv[1]["skinned"], kv[0])):
        key = (i["verts"], i["faces"], tuple(round(x, 3) for x in i["lo"] + i["hi"]), i["mats"])
        if key in seen:
            why[n] = "duplicate of " + seen[key]
        else:
            seen[key] = n
    rest = [i for n, i in info.items() if n not in why]
    big = sorted(rest, key=lambda i: -i["verts"])[:3]
    if big:
        lo = [min(i["lo"][k] for i in big) for k in range(3)]
        hi = [max(i["hi"][k] for i in big) for k in range(3)]
        size = max(hi[k] - lo[k] for k in range(3))
        ctr = [(lo[k] + hi[k]) / 2 for k in range(3)]
        for n, i in info.items():
            if n in why:
                continue
            c = [(i["lo"][k] + i["hi"][k]) / 2 for k in range(3)]
            dist = sum((c[k] - ctr[k]) ** 2 for k in range(3)) ** 0.5
            diag = sum((i["hi"][k] - i["lo"][k]) ** 2 for k in range(3)) ** 0.5
            if dist > 1.5 * size:
                why[n] = "far from the body (%.1fx its height): a stray prop" % (dist / max(size, 1e-9))
            elif not i["skinned"] and diag < 0.12 * size and c[2] < lo[2] + 0.05 * size:
                why[n] = "tiny unskinned object on the floor (decal)"
    kept, report = [], []
    for n, i in info.items():
        inc = n not in why
        if n in override:
            inc = bool(override[n])
        report.append({"name": n, "include": inc, "reason": why.get(n, "") if not inc or n in why else "", "verts": i["verts"],
                       "skinned": i["skinned"]})
        if inc:
            kept.append(i["o"])
        else:
            bpy.data.objects.remove(i["o"], do_unlink=True)
    return kept, report


def _bake_world(objs, arm, M):
    """Multiply every object's WORLD matrix by M (computed first, so parents moving does not double-apply to children),
    then bake it into the data."""
    new = {o: M @ o.matrix_world.copy() for o in objs}
    for o, mw in new.items():
        o.matrix_world = mw
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.context.view_layer.update()


def scale_all(arm, meshes, s):
    """Bake a uniform scale into the armature and meshes (no vertex moves relative to its bones)."""
    _bake_world([arm] + meshes, arm, Matrix.Scale(s, 4))


def load_generic(path, prefer_armature=None, parts_override=None):
    """Import, drop animation / shape keys / helper objects, rest pose, bake all world transforms.
    Returns (armature, [skinned meshes], notes)."""
    notes = []
    import_model(path)
    arm = pick_armature(prefer_armature)
    meshes = skinned_meshes(arm)
    if not meshes:
        raise RuntimeError("no mesh is attached to the armature '%s'" % arm.name)
    meshes, parts = choose_parts(meshes, parts_override)
    if not meshes:
        raise RuntimeError("every mesh was excluded")
    for p in parts:
        if not p["include"]:
            notes.append("part %s left out: %s" % (p["name"], p["reason"] or "excluded by you"))
    load_generic.last_parts = parts

    for a in list(bpy.data.actions):
        bpy.data.actions.remove(a)
    if arm.animation_data:
        arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.location, pb.rotation_quaternion, pb.rotation_euler, pb.scale = (0, 0, 0), (1, 0, 0, 0), (0, 0, 0), (1, 1, 1)

    # shape keys (expressions) block modifier-apply; keep the basis, note the loss
    for m in meshes:
        if m.data.shape_keys:
            notes.append("%s: %d shape keys dropped (the basis shape is kept)" % (m.name, len(m.data.shape_keys.key_blocks) - 1))
            bpy.context.view_layer.objects.active = m
            bpy.ops.object.shape_key_remove(all=True)

    # meshes hung on a single bone (rigid accessories): turn them into full-weight vertex groups
    for m in meshes:
        if m.parent == arm and m.parent_type == "BONE" and m.parent_bone:
            vg = m.vertex_groups.new(name=m.parent_bone)
            vg.add(list(range(len(m.data.vertices))), 1.0, "REPLACE")
            if not [x for x in m.modifiers if x.type == "ARMATURE"]:
                mod = m.modifiers.new("Armature", "ARMATURE")
                mod.object = arm
            m.parent_type = "OBJECT"
            notes.append("%s: rigid mesh on bone '%s' converted to skin weights" % (m.name, m.parent_bone))

    # bake world transforms BEFORE deleting anything (the armature may hang under an empty carrying a rotation)
    bpy.ops.object.select_all(action="DESELECT")
    for o in [arm] + meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in list(bpy.data.objects):
        if o is not arm and o not in meshes:
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    for m in meshes:
        m.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="OBJECT", keep_transform=True)
    for m in meshes:
        if not [x for x in m.modifiers if x.type == "ARMATURE"]:
            mod = m.modifiers.new("Armature", "ARMATURE")
            mod.object = arm
    bpy.context.view_layer.update()
    return arm, meshes, notes


def rotate_all(arm, meshes, R3):
    """Rotate armature and meshes about the world origin by the 3x3 R (row-major lists) and bake it."""
    M = Matrix([list(R3[0]) + [0], list(R3[1]) + [0], list(R3[2]) + [0], [0, 0, 0, 1]])
    _bake_world([arm] + meshes, arm, M)


def bone_table(arm, meshes):
    """[{name, parent, head, tail, weighted, mass}] in world space."""
    mass = {}
    for m in meshes:
        names = {g.index: g.name for g in m.vertex_groups}
        for v in m.data.vertices:
            for ge in v.groups:
                if ge.weight > 1e-4:
                    mass[names[ge.group]] = mass.get(names[ge.group], 0.0) + ge.weight
    out = []
    for b in arm.data.bones:
        h = arm.matrix_world @ b.head_local
        t = arm.matrix_world @ b.tail_local
        out.append({"name": b.name, "parent": b.parent.name if b.parent else None, "head": [h.x, h.y, h.z],
                    "tail": [t.x, t.y, t.z], "weighted": mass.get(b.name, 0.0) > 0.0, "mass": mass.get(b.name, 0.0)})
    return out


def mesh_bounds(meshes):
    lo = [1e18] * 3
    hi = [-1e18] * 3
    for m in meshes:
        for v in m.data.vertices:
            w = m.matrix_world @ v.co
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    return lo, hi


def alpha_stats(path):
    """Look at the alpha channel of a texture: is it a real cut-out mask (mostly 0 and 1) or continuous data (specular etc.)?
    Returns None when the image has no alpha."""
    try:
        img = bpy.data.images.load(path, check_existing=True)
        if img.channels < 4:
            return {"none": True}
        tmp = img.copy()
        w, h = tmp.size
        if w == 0 or h == 0:
            return None
        tmp.scale(min(w, 512), min(h, 512))
        import numpy as np
        px = np.empty(len(tmp.pixels), dtype=np.float32)
        tmp.pixels.foreach_get(px)
        a = px.reshape(-1, 4)[:, 3]
        bpy.data.images.remove(tmp)
        n = float(a.size)
        out = {"transparent": float((a < 0.1).sum()) / n, "opaque": float((a > 0.9).sum()) / n,
               "mid": float(((a >= 0.1) & (a <= 0.9)).sum()) / n, "mean": float(a.mean())}
        if out["opaque"] > 0.999:
            return {"none": True}   # an alpha channel that is solid white carries nothing
        return out
    except Exception:
        return None


def extract_materials(meshes, out_dir):
    """[{name, base, normal, rough, metal, alpha_img, alpha_mode, two_sided}] from Principled node trees. Packed images are
    saved into out_dir/textures."""
    os.makedirs(os.path.join(out_dir, "textures"), exist_ok=True)

    def image_path(img):
        if img is None:
            return None
        if img.packed_file or not img.filepath:
            p = os.path.join(out_dir, "textures", (img.name if img.name.lower().endswith(".png") else img.name + ".png"))
            try:
                img.filepath_raw = p
                img.file_format = "PNG"
                img.save()
                return p
            except Exception:
                return None
        p = bpy.path.abspath(img.filepath)
        return p if os.path.exists(p) else None

    def src_image(socket):
        if socket is None or not socket.is_linked:
            return None
        node = socket.links[0].from_node
        for _ in range(6):
            if node.type == "TEX_IMAGE":
                return node.image
            ins = [i for i in node.inputs if i.is_linked]
            if not ins:
                return None
            node = ins[0].links[0].from_node
        return None

    out, seen = [], set()
    for m in meshes:
        for slot in m.material_slots:
            mat = slot.material
            if not mat or mat.name in seen:
                continue
            seen.add(mat.name)
            rec = {"name": mat.name, "meshes": sorted({mm.name for mm in meshes if any(sl.material == mat for sl in mm.material_slots)}),
                   "base": None, "normal": None, "rough": None, "metal": None, "alpha_img": None,
                   "alpha_mode": "opaque", "two_sided": not getattr(mat, "use_backface_culling", False)}
            if mat.use_nodes and mat.node_tree:
                bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
                if bsdf:
                    rec["base"] = image_path(src_image(bsdf.inputs.get("Base Color")))
                    rec["normal"] = image_path(src_image(bsdf.inputs.get("Normal")))
                    rec["rough"] = image_path(src_image(bsdf.inputs.get("Roughness")))
                    rec["metal"] = image_path(src_image(bsdf.inputs.get("Metallic")))
                    a = bsdf.inputs.get("Alpha")
                    if a is not None and a.is_linked:
                        rec["alpha_mode"] = "masked"
            bm = getattr(mat, "blend_method", None)
            if bm in ("CLIP", "HASHED", "BLEND") and rec["alpha_mode"] == "opaque" and rec["base"]:
                rec["alpha_mode"] = "masked"
            rec["alpha_stats"] = alpha_stats(rec["base"]) if rec["base"] else None
            out.append(rec)
    return out
