"""Import Kalina_OnMannequin.fbx onto the default mannequin's skeleton asset (SK_Mannequin) as
/Game/KalinaMannequin/SK_Kalina_Mannequin, with her textures/materials, and check every bone frame against Quinn's.
Run via tools\Run-UEPython.ps1."""
import json
import math
import os
import unreal

ROOT = r"C:\AIProjects\PipecatUnreal"
FBX = os.path.join(ROOT, "avatar_source", "original_clean", "Kalina_OnMannequin.fbx")
SRC = os.path.join(ROOT, "third_party", "kalina_original", "Model_Hero_Kalina_N01")
DEST = "/Game/KalinaMannequin"
SKELETON = "/Game/Characters/Mannequins/Meshes/SK_Mannequin"

at = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary


def log(m):
    unreal.log("KALINA: " + str(m))


# ---- textures + materials (the game's own textures) ---------------------------------------------------------------
TEX = ["Kalina_N01_body_diffuse", "Kalina_N01_body_normal", "Kalina_Face_Diffuse", "Kalina_Hair_Diffuse",
       "Kalina_Hair_Normal"]
tasks = []
for name in TEX:
    t = unreal.AssetImportTask()
    t.set_editor_property("filename", os.path.join(SRC, name + ".png"))
    t.set_editor_property("destination_path", DEST + "/Textures")
    t.set_editor_property("automated", True)
    t.set_editor_property("replace_existing", True)
    t.set_editor_property("save", True)
    tasks.append(t)
at.import_asset_tasks(tasks)
for name in ("Kalina_N01_body_normal", "Kalina_Hair_Normal"):
    tex = eal.load_asset("%s/Textures/%s" % (DEST, name))
    tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
    tex.set_editor_property("srgb", False)
    eal.save_loaded_asset(tex)


def tex_node(mat, path, x, y, normal=False):
    n = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSample, x, y)
    n.set_editor_property("texture", eal.load_asset(path))
    if normal:
        n.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    return n


def make_material(name, diffuse, normal=None, masked=False):
    path = "%s/Materials/%s" % (DEST, name)
    if eal.does_asset_exist(path):
        # the mesh already references it, so rebuild the graph in place instead of deleting the asset
        mat = eal.load_asset(path)
        mel.delete_all_material_expressions(mat)
    else:
        mat = at.create_asset(name, DEST + "/Materials", unreal.Material, unreal.MaterialFactoryNew())
    d = tex_node(mat, "%s/Textures/%s" % (DEST, diffuse), -600, 0)
    mel.connect_material_property(d, "RGB", unreal.MaterialProperty.MP_BASE_COLOR)
    if normal:
        n = tex_node(mat, "%s/Textures/%s" % (DEST, normal), -600, 300, normal=True)
        mel.connect_material_property(n, "RGB", unreal.MaterialProperty.MP_NORMAL)
    c = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -300, 200)
    c.set_editor_property("r", 0.7)
    mel.connect_material_property(c, "", unreal.MaterialProperty.MP_ROUGHNESS)
    # Without this flag a game run (as opposed to the editor) cannot build the skinned-mesh shader permutation and
    # falls back to the plain grey default material.
    mat.set_editor_property("used_with_skeletal_mesh", True)
    if masked:
        # Hair: the diffuse alpha is hair-specular data in the original game's shader, not a cut-out mask, so the
        # strands are drawn opaque (they are real geometry) and two-sided.
        mat.set_editor_property("two_sided", True)
    mel.recompile_material(mat)
    eal.save_loaded_asset(mat)
    return mat


MATS = {
    "Kalina_N01_body": make_material("M_Kalina_Body", "Kalina_N01_body_diffuse", "Kalina_N01_body_normal"),
    "Kalina_N01_Face": make_material("M_Kalina_Face", "Kalina_Face_Diffuse"),
    "Kalina_Hair": make_material("M_Kalina_Hair", "Kalina_Hair_Diffuse", "Kalina_Hair_Normal", masked=True),
}

# ---- the mesh, bound to the mannequin's own skeleton asset ----------------------------------------------------------
skeleton = eal.load_asset(SKELETON)
assert skeleton, "mannequin skeleton not found"
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
t.set_editor_property("filename", FBX)
t.set_editor_property("destination_path", DEST)
t.set_editor_property("destination_name", "SK_Kalina_Mannequin")
t.set_editor_property("automated", True)
t.set_editor_property("replace_existing", True)
t.set_editor_property("save", True)
t.set_editor_property("options", opts)
at.import_asset_tasks([t])

skm = eal.load_asset(DEST + "/SK_Kalina_Mannequin")
assert skm, "import failed"
sk = skm.get_editor_property("skeleton")
log("skeleton used = %s  (wanted %s)" % (sk.get_path_name() if sk else None, skeleton.get_path_name()))
new = []
for s in skm.get_editor_property("materials"):
    sn = str(s.get_editor_property("material_slot_name"))
    m = MATS.get(sn)
    log("slot %s -> %s" % (sn, m.get_name() if m else "(none)"))
    if m:
        s.set_editor_property("material_interface", m)
    new.append(s)
skm.set_editor_property("materials", new)
eal.save_loaded_asset(skm)
# The import merged the four jiggle bones into the shared mannequin skeleton asset; that asset must be saved too,
# otherwise the saved skeleton still has 89 bones and the extra bones vanish when the game loads.
eal.save_loaded_asset(skeleton)
log("skeleton asset saved")

# ---- compare every bone frame with Quinn's --------------------------------------------------------------------------
q = json.load(open(os.path.join(ROOT, "avatar_source", "mannequin_skeleton.json")))["bones"]
mod = unreal.SkeletonModifier()
mod.set_skeletal_mesh(skm)
have = [str(n) for n in mod.get_all_bone_names()]
log("bones in imported mesh: %d (mannequin has %d)" % (len(have), len(q)))
log("jiggle bones present: %s" % [n for n in have if n.startswith("jiggle_")])
worst_ang, worst_bone, scaled = 0.0, "", 0
for b in q:
    if b["name"] not in have:
        log("MISSING bone " + b["name"])
        continue
    tr = mod.get_bone_transform(b["name"], True)
    r = tr.rotation
    dot = abs(r.x * b["quat"][0] + r.y * b["quat"][1] + r.z * b["quat"][2] + r.w * b["quat"][3])
    ang = math.degrees(2 * math.acos(min(1.0, dot)))
    if ang > worst_ang:
        worst_ang, worst_bone = ang, b["name"]
    if abs(tr.scale3d.x - 1.0) > 1e-3:
        scaled += 1
log("worst bone-frame angle vs mannequin: %.3f deg (%s); bones with non-unit scale: %d" % (worst_ang, worst_bone, scaled))
bd = skm.get_bounds()
log("bounds origin=(%.1f %.1f %.1f) extent=(%.1f %.1f %.1f)" % (bd.origin.x, bd.origin.y, bd.origin.z, bd.box_extent.x, bd.box_extent.y, bd.box_extent.z))
eal.save_directory(DEST)
log("DONE")
