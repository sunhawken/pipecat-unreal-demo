"""blender -b -P inspect_model.py -- job.json
job: {"source": path, "out_dir": dir, "armature": optional}
Writes out_dir/inspect.json: bones (world space, after baking transforms), meshes, materials, bounds, notes."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import af_common as C  # noqa: E402

job, _ = C.job_from_argv()
os.makedirs(job["out_dir"], exist_ok=True)
arm, meshes, notes = C.load_generic(job["source"], job.get("armature"), job.get("parts"))
lo, hi = C.mesh_bounds(meshes)
bones = C.bone_table(arm, meshes)
rep = {
    "source": job["source"],
    "armature": arm.name,
    "bones": bones,
    "meshes": [{"name": m.name, "verts": len(m.data.vertices), "tris": sum(len(p.vertices) - 2 for p in m.data.polygons),
                "materials": [s.material.name for s in m.material_slots if s.material],
                "groups": len(m.vertex_groups)} for m in meshes],
    "materials": C.extract_materials(meshes, job["out_dir"]),
    "bounds": {"min": lo, "max": hi},
    "unit_scale": __import__("bpy").context.scene.unit_settings.scale_length,
    "notes": notes,
    "parts": C.load_generic.last_parts,
}
import json  # noqa: E402
with open(os.path.join(job["out_dir"], "inspect.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, indent=1)
C.log("INSPECT OK: %d bones (%d weighted), %d meshes" % (len(bones), sum(b["weighted"] for b in bones), len(meshes)))
