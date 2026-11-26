"""Dump the default mannequin's skeleton (names, parents, global transforms) to JSON, and list the template's
mannequin assets. Run via tools\Run-UEPython.ps1."""
import json
import unreal

eal = unreal.EditorAssetLibrary
OUT = r"C:\AIProjects\PipecatUnreal\avatar_source\mannequin_skeleton.json"

for a in eal.list_assets("/Game/Characters", recursive=True, include_folder=False):
    d = eal.find_asset_data(a)
    cls = str(d.asset_class_path.asset_name)
    if cls in ("SkeletalMesh", "Skeleton", "IKRigDefinition", "AnimBlueprint", "PhysicsAsset"):
        unreal.log("KALINA: %s %s" % (cls, a))

# which mesh does the template's character use?
bp = eal.load_asset("/Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter")
cdo = unreal.get_default_object(bp.generated_class())
mesh_comp = cdo.get_editor_property("mesh")
skm = mesh_comp.get_editor_property("skeletal_mesh_asset")
unreal.log("KALINA: character mesh = %s" % skm.get_path_name())
unreal.log("KALINA: anim class = %s" % mesh_comp.get_editor_property("anim_class"))
unreal.log("KALINA: mesh rel loc=%s rot=%s" % (mesh_comp.get_editor_property("relative_location"),
                                                mesh_comp.get_editor_property("relative_rotation")))
cap = cdo.get_editor_property("capsule_component")
unreal.log("KALINA: capsule half height=%s radius=%s" % (cap.get_editor_property("capsule_half_height"),
                                                          cap.get_editor_property("capsule_radius")))

mod = unreal.SkeletonModifier()
mod.set_skeletal_mesh(skm)
names = [str(n) for n in mod.get_all_bone_names()]
bones = []
for n in names:
    t = mod.get_bone_transform(n, True)          # global (component space)
    q = t.rotation
    bones.append({"name": n, "parent": str(mod.get_parent_name(n)),
                  "pos": [t.translation.x, t.translation.y, t.translation.z],
                  "quat": [q.x, q.y, q.z, q.w], "scale": [t.scale3d.x, t.scale3d.y, t.scale3d.z]})
json.dump({"mesh": skm.get_path_name(), "bones": bones}, open(OUT, "w"), indent=1)
b = skm.get_bounds()
unreal.log("KALINA: %d bones; bounds origin=(%.1f %.1f %.1f) extent=(%.1f %.1f %.1f)" % (
    len(bones), b.origin.x, b.origin.y, b.origin.z, b.box_extent.x, b.box_extent.y, b.box_extent.z))
unreal.log("KALINA: first bones: %s" % names[:24])
unreal.log("KALINA: DONE")
