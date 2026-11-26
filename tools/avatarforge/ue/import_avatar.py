"""Import an AvatarForge FBX onto the default mannequin skeleton in Unreal, with textures and materials, then verify.
Run through tools\\Run-UEPython.ps1 with the environment variable AVATARFORGE_JOB pointing at the job JSON:
  {"fbx", "dest": "/Game/Avatars/Name", "name": "SK_Name", "skeleton": "/Game/.../SK_Mannequin",
   "mannequin": path to mannequin_skeleton.json, "materials": [{name, base, normal, rough, metal, alpha_mode, two_sided}],
   "result": path}"""
import json
import math
import os
import re

import unreal

JOB = json.load(open(os.environ["AVATARFORGE_JOB"], encoding="utf-8"))
DEST, NAME = JOB["dest"], JOB["name"]
at = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
result = {"ok": False, "log": [], "slots": {}}


def log(m):
    unreal.log("AVATARFORGE: " + str(m))
    result["log"].append(str(m))


def safe(s):
    return re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_")


def save_result():
    json.dump(result, open(JOB["result"], "w", encoding="utf-8"), indent=1)


try:
    # ---- textures -----------------------------------------------------------------------------------------------
    tex_assets = {}
    tasks, wanted = [], []
    for mat in JOB["materials"]:
        for kind in ("base", "normal", "rough", "metal"):
            p = mat.get(kind)
            if p and os.path.exists(p) and p not in tex_assets:
                asset = "T_%s_%s" % (safe(mat["name"]), kind)
                t = unreal.AssetImportTask()
                t.set_editor_property("filename", p)
                t.set_editor_property("destination_path", DEST + "/Textures")
                t.set_editor_property("destination_name", asset)
                t.set_editor_property("automated", True)
                t.set_editor_property("replace_existing", True)
                t.set_editor_property("save", True)
                tasks.append(t)
                tex_assets[p] = (asset, kind)
    if tasks:
        at.import_asset_tasks(tasks)
    for p, (asset, kind) in tex_assets.items():
        tex = eal.load_asset("%s/Textures/%s" % (DEST, asset))
        if tex is None:
            log("texture failed to import: " + p)
            continue
        if kind == "normal":
            tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
            tex.set_editor_property("srgb", False)
        elif kind in ("rough", "metal"):
            tex.set_editor_property("srgb", False)
        eal.save_loaded_asset(tex)

    def tex_node(mat, kind_path, x, y, normal=False):
        n = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSample, x, y)
        n.set_editor_property("texture", eal.load_asset(kind_path))
        if normal:
            n.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
        return n

    def const(mat, v, x, y):
        c = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, x, y)
        c.set_editor_property("r", v)
        return c

    def make_material(spec):
        name = "M_%s" % safe(spec["name"])
        path = "%s/Materials/%s" % (DEST, name)
        if eal.does_asset_exist(path):
            mat = eal.load_asset(path)
            mel.delete_all_material_expressions(mat)
        else:
            mat = at.create_asset(name, DEST + "/Materials", unreal.Material, unreal.MaterialFactoryNew())
        tp = lambda k: "%s/Textures/%s" % (DEST, tex_assets[spec[k]][0]) if spec.get(k) in tex_assets else None
        if tp("base"):
            d = tex_node(mat, tp("base"), -600, 0)
            mel.connect_material_property(d, "RGB", unreal.MaterialProperty.MP_BASE_COLOR)
            if spec.get("alpha_mode") == "masked":
                # real cut-out (hair cards, lashes, leaves): masked, never translucent, so there is no sorting artefact
                mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
                mat.set_editor_property("opacity_mask_clip_value", 0.35)
                mel.connect_material_property(d, "A", unreal.MaterialProperty.MP_OPACITY_MASK)
        else:
            mel.connect_material_property(const(mat, 0.6, -600, 0), "", unreal.MaterialProperty.MP_BASE_COLOR)
        if tp("normal"):
            mel.connect_material_property(tex_node(mat, tp("normal"), -600, 300, True), "RGB", unreal.MaterialProperty.MP_NORMAL)
        if tp("rough"):
            mel.connect_material_property(tex_node(mat, tp("rough"), -600, 600), "R", unreal.MaterialProperty.MP_ROUGHNESS)
        else:
            # hair and cloth cards read better rougher than skin
            rough = 0.85 if spec.get("class") in ("hair", "cutout") else 0.7
            mel.connect_material_property(const(mat, rough, -300, 200), "", unreal.MaterialProperty.MP_ROUGHNESS)
        if tp("metal"):
            mel.connect_material_property(tex_node(mat, tp("metal"), -600, 900), "R", unreal.MaterialProperty.MP_METALLIC)
        # without this a packaged/game run cannot build the skinned-mesh shader permutation and shows the grey default
        mat.set_editor_property("used_with_skeletal_mesh", True)
        if spec.get("two_sided"):
            mat.set_editor_property("two_sided", True)
        mel.recompile_material(mat)
        eal.save_loaded_asset(mat)
        return mat

    MATS = {m["name"]: make_material(m) for m in JOB["materials"]}

    # ---- the mesh, bound to the mannequin's own skeleton ---------------------------------------------------------
    skeleton = eal.load_asset(JOB["skeleton"])
    assert skeleton, "mannequin skeleton not found: " + JOB["skeleton"]
    opts = unreal.FbxImportUI()
    opts.set_editor_property("import_mesh", True)
    opts.set_editor_property("import_as_skeletal", True)
    opts.set_editor_property("import_materials", False)
    opts.set_editor_property("import_textures", False)
    opts.set_editor_property("import_animations", False)
    opts.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    opts.set_editor_property("skeleton", skeleton)
    opts.skeletal_mesh_import_data.set_editor_property("import_morph_targets", False)
    t = unreal.AssetImportTask()
    t.set_editor_property("filename", JOB["fbx"])
    t.set_editor_property("destination_path", DEST)
    t.set_editor_property("destination_name", NAME)
    t.set_editor_property("automated", True)
    t.set_editor_property("replace_existing", True)
    t.set_editor_property("save", True)
    t.set_editor_property("options", opts)
    at.import_asset_tasks([t])

    skm = eal.load_asset("%s/%s" % (DEST, NAME))
    assert skm, "import failed"
    sk = skm.get_editor_property("skeleton")
    result["skeleton_used"] = sk.get_path_name() if sk else None
    log("skeleton used = %s (wanted %s)" % (result["skeleton_used"], skeleton.get_path_name()))
    new = []
    for s in skm.get_editor_property("materials"):
        sn = str(s.get_editor_property("material_slot_name"))
        m = MATS.get(sn)
        result["slots"][sn] = m.get_name() if m else None
        log("slot %s -> %s" % (sn, m.get_name() if m else "(none)"))
        if m:
            s.set_editor_property("material_interface", m)
        new.append(s)
    skm.set_editor_property("materials", new)
    eal.save_loaded_asset(skm)
    eal.save_loaded_asset(skeleton)   # the import may have merged the jiggle bones into the shared skeleton

    # ---- verify every bone frame against the mannequin's ------------------------------------------------------------
    q = json.load(open(JOB["mannequin"]))["bones"]
    mod = unreal.SkeletonModifier()
    mod.set_skeletal_mesh(skm)
    have = [str(n) for n in mod.get_all_bone_names()]
    worst, worst_bone, scaled, missing = 0.0, "", 0, []
    for b in q:
        if b["name"] not in have:
            missing.append(b["name"])
            continue
        tr = mod.get_bone_transform(b["name"], True)
        r = tr.rotation
        dot = abs(r.x * b["quat"][0] + r.y * b["quat"][1] + r.z * b["quat"][2] + r.w * b["quat"][3])
        ang = math.degrees(2 * math.acos(min(1.0, dot)))
        if ang > worst:
            worst, worst_bone = ang, b["name"]
        if abs(tr.scale3d.x - 1.0) > 1e-3:
            scaled += 1
    bd = skm.get_bounds()
    result.update(bones=len(have), missing_bones=missing, worst_frame_deg=worst, worst_bone=worst_bone, scaled_bones=scaled,
                  jiggle_bones=[n for n in have if n.startswith("jiggle_")],
                  bounds_extent=[bd.box_extent.x, bd.box_extent.y, bd.box_extent.z], asset="%s/%s.%s" % (DEST, NAME, NAME))
    log("bones %d, missing %s, worst frame %.3f deg (%s), non-unit scale %d" % (len(have), missing, worst, worst_bone, scaled))
    eal.save_directory(DEST)
    result["ok"] = not missing and worst < 0.05
    log("DONE ok=%s" % result["ok"])
except Exception as e:  # report instead of dying silently
    import traceback
    result["error"] = "%s\n%s" % (e, traceback.format_exc())
    log("ERROR " + str(e))
finally:
    save_result()
