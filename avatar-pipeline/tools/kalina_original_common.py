"""Shared helpers for cleaning the ORIGINAL Kalina FBX in Blender (no vertex is edited, only transforms/poses)."""
import math
import bpy
from mathutils import Matrix, Vector

import os
ARM_NAME = "Model_Hero_Kalina_N01"


def report(label, arm, meshes):
    """KALINA_DEBUG=1 prints the rig/mesh orientation at each stage."""
    if not os.environ.get("KALINA_DEBUG"):
        return
    bpy.context.view_layer.update()
    h = arm.matrix_world @ arm.data.bones["Bip001 Head"].head_local
    b = meshes[0]
    zs = [(b.matrix_world @ v.co) for v in b.data.vertices]
    print("STAGE %-22s arm_rot=%s head_world=%s Body y[%.2f,%.2f] z[%.2f,%.2f] parent=%s" % (
        label, tuple(round(a * 57.3) for a in arm.matrix_world.to_euler()), tuple(round(v, 2) for v in h),
        min(v.y for v in zs), max(v.y for v in zs), min(v.z for v in zs), max(v.z for v in zs), b.parent.name if b.parent else None))
MESH_NAMES = ("Body", "Face", "Hair")


def load_clean(fbx):
    """Import the original FBX, reset to the rest pose, keep only armature + skinned meshes, bake transforms."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=fbx)
    arm = bpy.data.objects[ARM_NAME]
    meshes = [bpy.data.objects[n] for n in MESH_NAMES]
    report('imported', arm, meshes)

    # keep this armature's own clips (the importer also made copies for every helper node)
    keep_actions = [a for a in bpy.data.actions if a.name.startswith(ARM_NAME + "|")]
    for a in list(bpy.data.actions):
        if a not in keep_actions:
            bpy.data.actions.remove(a)
    for a in keep_actions:
        a.name = a.name.split("|")[1].replace("Kalina_N01_Battle_Locomotion_", "")
        a.use_fake_user = True
    if arm.animation_data:
        arm.animation_data.action = None
    for pb in arm.pose.bones:  # rest pose
        pb.location = (0, 0, 0)
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.rotation_euler = (0, 0, 0)
        pb.scale = (1, 1, 1)

    # the face's 25 expression shape keys are not needed (and block modifier-apply); keep the basis shape
    face = bpy.data.objects["Face"]
    if face.data.shape_keys:
        bpy.context.view_layer.objects.active = face
        bpy.ops.object.shape_key_remove(all=True)

    # Bake the world transforms BEFORE deleting anything: the armature hangs under a Unity "Prefab" empty that
    # carries the +90 degree rotation, so removing that empty first would silently rotate the whole figure.
    bpy.ops.object.select_all(action="DESELECT")
    for o in [arm] + meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    report("unparented", arm, meshes)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    report("transforms baked", arm, meshes)

    # now the Unity helper empties and the unskinned face-glow card can go
    for o in list(bpy.data.objects):
        if o is not arm and o not in meshes:
            bpy.data.objects.remove(o, do_unlink=True)

    # parent the meshes back to the armature (the Armature modifiers still point at it)
    bpy.ops.object.select_all(action="DESELECT")
    for m in meshes:
        m.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="OBJECT", keep_transform=True)
    report('re-parented', arm, meshes)
    return arm, meshes, keep_actions


def _fcurves(act):
    if hasattr(act, "fcurves"):
        return list(act.fcurves)
    out = []
    for layer in act.layers:
        for strip in layer.strips:
            for cb in strip.channelbags:
                out += list(cb.fcurves)
    return out


def to_centimetres(arm, meshes, actions):
    """Author in centimetres so Unreal's importer needs no unit conversion (it would put a 100x scale on the
    root bone and break skinning)."""
    for m in meshes:
        m.data.transform(Matrix.Scale(100.0, 4))
        m.data.update()
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for eb in arm.data.edit_bones:
        eb.use_connect = False
    for eb in arm.data.edit_bones:
        eb.head = eb.head * 100.0
        eb.tail = eb.tail * 100.0
    bpy.ops.object.mode_set(mode="OBJECT")
    for act in actions:  # translation keys of the clips are in metres too
        for fc in _fcurves(act):
            if fc.data_path.endswith(".location"):
                for kp in fc.keyframe_points:
                    kp.co.y *= 100.0
                    kp.handle_left.y *= 100.0
                    kp.handle_right.y *= 100.0
                fc.update()
    us = bpy.context.scene.unit_settings
    us.system, us.scale_length, us.length_unit = "METRIC", 0.01, "CENTIMETERS"


def world_head(arm, name):
    return arm.matrix_world @ arm.pose.bones[name].head


def t_pose(arm, meshes):
    """Raise both arms to horizontal (a T-pose) and make that the new rest pose, deforming the meshes with it."""
    bpy.context.view_layer.update()
    for side, sign in (("L", 1.0), ("R", -1.0)):
        chain = ["Bip001 %s UpperArm" % side, "Bip001 %s Forearm" % side, "Bip001 %s Hand" % side]
        target = Vector((sign, 0.0, 0.0))
        for i, name in enumerate(chain):
            pb = arm.pose.bones[name]
            bpy.context.view_layer.update()
            if i < len(chain) - 1:
                d = world_head(arm, chain[i + 1]) - world_head(arm, name)
            else:
                d = (arm.matrix_world @ pb.tail) - (arm.matrix_world @ pb.head)
            rot = d.normalized().rotation_difference(target).to_matrix().to_4x4()
            h = arm.matrix_world @ pb.head
            m = Matrix.Translation(h) @ rot @ Matrix.Translation(-h)
            pb.matrix = arm.matrix_world.inverted() @ (m @ (arm.matrix_world @ pb.matrix))
    bpy.context.view_layer.update()

    # bake the deformation into the meshes, then take the pose as the rest pose, then re-add the modifiers
    for m in meshes:
        bpy.context.view_layer.objects.active = m
        bpy.ops.object.modifier_apply(modifier=[x for x in m.modifiers if x.type == "ARMATURE"][0].name)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    for m in meshes:
        mod = m.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
