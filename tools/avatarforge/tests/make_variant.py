"""Make a disguised copy of a rigged model to test AvatarForge: bones renamed to Mixamo names, the model laid on its back
(Y-up) and scaled, then exported to FBX.

blender -b -P make_variant.py -- variant.json
variant.json: {"source", "rename": {old bone: new bone}, "out", "rotate_x_deg", "scale"}"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender"))
import af_common as C  # noqa: E402

job, _ = C.job_from_argv()
arm, meshes, _ = C.load_generic(job["source"])
ren = job["rename"]
for m in meshes:
    for g in m.vertex_groups:
        if g.name in ren:
            g.name = ren[g.name]
for b in list(arm.data.bones):
    pass
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
for eb in arm.data.edit_bones:
    if eb.name in ren:
        eb.name = ren[eb.name]
bpy.ops.object.mode_set(mode="OBJECT")

M = Matrix.Rotation(math.radians(job.get("rotate_x_deg", 0)), 4, "X") @ Matrix.Scale(job.get("scale", 1.0), 4)
for o in [arm] + meshes:
    o.matrix_world = M @ o.matrix_world
bpy.ops.object.select_all(action="DESELECT")
for o in [arm] + meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.fbx(filepath=job["out"], use_selection=True, object_types={"ARMATURE", "MESH"}, add_leaf_bones=False,
                         bake_anim=False, path_mode="STRIP")
C.log("VARIANT OK", job["out"])
