"""Reshape a properly skinned reference body (mannequin-named weights, e.g. Kalina) so it looks like a static target body, and
re-texture it. Used by convert_model.py when job["body_from"] is set.

Why: a static body has no skin weights and automatic weighting is only so good. A reference body that already deforms well
(its own game weights, UVs, jiggle bones) takes the target's SHAPE and the target's COLOUR instead; its topology, UV layout
and weights stay untouched, so it animates exactly as well as the reference did.

Steps: pose the reference skeleton onto the target's joints (its weights deform it) -> cut off its head part -> wrap it onto
the target surface in smoothed passes -> bake the target's colour onto the reference's own UV layout."""
import os

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

import af_common as C


def reshape_reference_body(spec, target, P0, mat_spec, Q, DEFORM, out_dir, log):
    """spec: {"fbx", "mesh" (name of the body mesh in the reference), "label", "tex_size"}; target: the static body object;
    P0: mannequin bone -> Vector, this model's joints (cm); mat_spec: {material name: {"base": path}}.
    Returns (new mesh object, {"material": name, "png": path})."""
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.fbx(filepath=spec["fbx"])
    new = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    ref_arm = next(o for o in new if o.type == "ARMATURE")
    ref = next(o for o in new if o.type == "MESH" and o.name.split(".")[0] == spec.get("mesh", "Body"))
    for o in new:
        if o is not ref_arm and o is not ref:
            bpy.data.objects.remove(o, do_unlink=True)
    ref.name = "Body_" + spec.get("label", "Reshaped")
    C._bake_world([ref_arm, ref], ref_arm, Matrix.Scale(100.0, 4))      # an FBX import is in metres: back to the cm numbers used here
    for b in ref_arm.data.bones:
        b.inherit_scale = "NONE"
    Pk = {b.name: ref_arm.matrix_world @ b.head_local for b in ref_arm.data.bones}

    # 1. pose the reference skeleton onto this model's joints
    kids = {}
    for n in DEFORM:
        par = Q[n]["parent"]
        while par and par not in DEFORM:
            par = Q[par]["parent"]
        kids.setdefault(par, []).append(n)
    for n in DEFORM:
        pb = ref_arm.pose.bones[n]
        R = Matrix.Identity(3)
        ch = kids.get(n, [])
        if ch:
            c = max(ch, key=lambda x: (P0[x] - P0[n]).length)
            a, b = Pk[c] - Pk[n], P0[c] - P0[n]
            if a.length > 1e-4 and b.length > 1e-4:
                R = a.rotation_difference(b).to_matrix()
        pb.matrix = Matrix.Translation(P0[n]) @ (R @ pb.bone.matrix_local.to_3x3()).to_4x4()
        bpy.context.view_layer.update()
    bpy.context.view_layer.objects.active = ref
    mods = [m for m in ref.modifiers if m.type == "ARMATURE"]
    bpy.ops.object.modifier_apply(modifier=mods[0].name)

    # 2. cut the head away (the model's own face and hair cover it)
    names = {g.index: g.name for g in ref.vertex_groups}
    bm = bmesh.new()
    bm.from_mesh(ref.data)
    verts = ref.data.vertices
    drop = [v for v in bm.verts if sum(ge.weight for ge in verts[v.index].groups if names[ge.group] == "head") > 0.5]
    bmesh.ops.delete(bm, geom=drop, context="VERTS")
    bm.to_mesh(ref.data)
    bm.free()
    ref.data.update()

    # 3. wrap onto the target in smoothed passes (seam-safe: split vertices share one displacement)
    bvh = BVHTree.FromObject(target, bpy.context.evaluated_depsgraph_get())
    canon, cid = {}, []
    for v in ref.data.vertices:
        cid.append(canon.setdefault(tuple(round(c * 1e3) for c in v.co), len(canon)))
    nbr = [set() for _ in range(len(canon))]
    for e in ref.data.edges:
        a, b = cid[e.vertices[0]], cid[e.vertices[1]]
        if a != b:
            nbr[a].add(b)
            nbr[b].add(a)
    nbr = [list(x) for x in nbr]
    for smooth in (14, 10, 6, 3, 1):
        d = [Vector() for _ in range(len(canon))]
        cnt = [0] * len(canon)
        for v in ref.data.vertices:
            loc, _n, _i, _dist = bvh.find_nearest(v.co)
            if loc is not None:
                d[cid[v.index]] += loc - v.co
                cnt[cid[v.index]] += 1
        d = [d[i] / max(cnt[i], 1) for i in range(len(d))]
        for _ in range(smooth):
            d = [(d[i] + (sum((d[j] for j in nbr[i]), Vector()) / len(nbr[i]) if nbr[i] else d[i])) * 0.5 for i in range(len(d))]
        for v in ref.data.vertices:
            v.co += d[cid[v.index]]
    ref.data.update()

    # 4. bake the target's colour onto the reference's own UV layout
    tmat = target.material_slots[0].material
    base = mat_spec.get(tmat.name, {}).get("base")
    if not base:
        raise RuntimeError("the target body's material has no base-colour texture to bake")
    size = int(spec.get("tex_size", 2048))
    img = bpy.data.images.new("AF_body_bake", size, size, alpha=False)
    src = bpy.data.materials.new("AF_src")
    src.use_nodes = True
    nt = src.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    tx = nt.nodes.new("ShaderNodeTexImage")
    tx.image = bpy.data.images.load(base, check_existing=True)
    tx.image.alpha_mode = "NONE"
    nt.links.new(tx.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    saved = [s.material for s in target.material_slots]
    for s in target.material_slots:
        s.material = src
    dst = bpy.data.materials.new(tmat.name + "_AFdst")
    dst.use_nodes = True
    dnt = dst.node_tree
    dnt.nodes.clear()
    dout = dnt.nodes.new("ShaderNodeOutputMaterial")
    dbs = dnt.nodes.new("ShaderNodeBsdfPrincipled")
    dtx = dnt.nodes.new("ShaderNodeTexImage")
    dtx.image = img
    dnt.links.new(dtx.outputs["Color"], dbs.inputs["Base Color"])
    dnt.links.new(dbs.outputs["BSDF"], dout.inputs["Surface"])
    dnt.nodes.active = dtx
    ref.data.materials.clear()
    ref.data.materials.append(dst)
    ref.data.uv_layers.active_index = 0
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = 1
    scn.view_settings.view_transform = "Standard"
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    ref.select_set(True)
    bpy.context.view_layer.objects.active = ref
    bpy.ops.object.bake(type="EMIT", use_selected_to_active=True, margin=16, margin_type="EXTEND", max_ray_distance=3.0,
                        cage_extrusion=1.0, use_clear=True)
    png = os.path.join(out_dir, "textures", "%s_on_%s_UV.png" % (tmat.name, spec.get("label", "Reshaped")))
    os.makedirs(os.path.dirname(png), exist_ok=True)
    img.filepath_raw = png
    img.file_format = "PNG"
    img.save()
    for s, m in zip(target.material_slots, saved):
        s.material = m
    final = bpy.data.materials.new("%s_%sUV" % (tmat.name, spec.get("label", "Reshaped")))   # a new material: it has its own texture
    ref.data.materials.clear()
    ref.data.materials.append(final)
    bpy.data.objects.remove(ref_arm, do_unlink=True)
    ref.parent = None
    log("reshaped the reference body onto %s: %d vertices, texture baked to %s" % (target.name, len(ref.data.vertices), png))
    return ref, {"material": final.name, "png": png}
