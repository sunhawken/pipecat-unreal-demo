"""blender -b -P kalina_original_export.py -- <original.fbx> <out.fbx> <mode> [textures_dir]

mode "rest"  : exact original rest pose + her own clips (Idle, Run, Jump_*), in centimetres, for Unreal.
mode "tpose" : arms raised to a T-pose, no animation, textured; also writes <out>.glb. For re-rigging (e.g. Meshy).
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kalina_original_common as K  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
fbx, out, mode = argv[:3]
tex_dir = argv[3] if len(argv) > 3 else os.path.dirname(fbx)

arm, meshes, actions = K.load_clean(fbx)
print("CLEAN arm bones=%d meshes=%s actions=%s" % (len(arm.data.bones), [m.name for m in meshes], [a.name for a in actions]))

scn = bpy.context.scene
scn.render.fps, scn.render.fps_base = 30, 1.0


def textured_materials():
    """Give each material its game textures so glTF/FBX exports carry them."""
    spec = {"Kalina_N01_body": ("Kalina_N01_body_diffuse.png", "Kalina_N01_body_normal.png"),
            "Kalina_N01_Face": ("Kalina_Face_Diffuse.png", None),
            "Kalina_Hair": ("Kalina_Hair_Diffuse.png", "Kalina_Hair_Normal.png")}
    for m in meshes:
        for slot in m.material_slots:
            mat = slot.material
            if not mat or mat.name not in spec:
                continue
            diff, norm = spec[mat.name]
            mat.use_nodes = True
            nt = mat.node_tree
            nt.nodes.clear()
            out_n = nt.nodes.new("ShaderNodeOutputMaterial")
            bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
            nt.links.new(bsdf.outputs["BSDF"], out_n.inputs["Surface"])
            bsdf.inputs["Roughness"].default_value = 0.7
            d = nt.nodes.new("ShaderNodeTexImage")
            d.image = bpy.data.images.load(os.path.join(tex_dir, diff), check_existing=True)
            nt.links.new(d.outputs["Color"], bsdf.inputs["Base Color"])
            if mat.name == "Kalina_Hair":
                nt.links.new(d.outputs["Alpha"], bsdf.inputs["Alpha"])
                mat.blend_method = "HASHED" if hasattr(mat, "blend_method") else None
            if norm:
                n = nt.nodes.new("ShaderNodeTexImage")
                n.image = bpy.data.images.load(os.path.join(tex_dir, norm), check_existing=True)
                n.image.colorspace_settings.name = "Non-Color"
                nm = nt.nodes.new("ShaderNodeNormalMap")
                nt.links.new(n.outputs["Color"], nm.inputs["Color"])
                nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])


if mode == "rest":
    K.to_centimetres(arm, meshes, actions)
    bpy.context.view_layer.objects.active = arm
    arm.animation_data_create()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.fbx(
        filepath=out, use_selection=True, object_types={"ARMATURE", "MESH"}, add_leaf_bones=False,
        bake_anim=True, bake_anim_use_all_actions=True, bake_anim_use_nla_strips=False,
        bake_anim_simplify_factor=0.0, bake_anim_step=1.0, bake_anim_force_startend_keying=True,
        apply_scale_options="FBX_SCALE_NONE", path_mode="STRIP", axis_forward="-Z", axis_up="Y",
        mesh_smooth_type="FACE", use_tspace=True)
elif mode == "tpose":
    for a in actions:
        bpy.data.actions.remove(a)
    K.t_pose(arm, meshes)
    textured_materials()
    base = os.path.splitext(out)[0]
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=base + ".glb", export_format="GLB", use_selection=True,
                              export_apply=False, export_animations=False, export_skins=True)
    K.to_centimetres(arm, meshes, [])
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.fbx(
        filepath=out, use_selection=True, object_types={"ARMATURE", "MESH"}, add_leaf_bones=False, bake_anim=False,
        apply_scale_options="FBX_SCALE_NONE", path_mode="COPY", embed_textures=True, axis_forward="-Z", axis_up="Y",
        mesh_smooth_type="FACE", use_tspace=True)
print("WROTE", out)
