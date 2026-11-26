# Putting a custom character on the default Unreal mannequin (1:1 method)

How a third-party character (here: *Kalina*, from a game's extracted model files) became the **player body in this demo**
while keeping every stock animation, the animation Blueprint, the capsule and the camera of the Third Person template.

The idea in one line: **don't retarget, re-skin.** Rebuild the character's mesh so it is skinned directly onto the
default mannequin skeleton (`SK_Mannequin`), bone for bone. Because it *is* that skeleton, the template's idle / walk /
run / jump animations drive it unchanged, and swapping the mesh at runtime is a one-liner.

> **The model itself is not in this repo.** It is someone else's game asset. These are the scripts and the method;
> bring your own source model (any rigged character works, the steps below are not Kalina-specific).

## What is here

| Path | What |
|---|---|
| `tools/dump_mannequin.py` | Run in the editor: dumps the mannequin skeleton (bone names, parents, global transforms) to JSON |
| `mannequin_skeleton.json` | That dump for UE 5.8's `SK_Mannequin` (89 bones). The Blender step reads it |
| `tools/kalina_original_common.py` | Blender helpers: load the source FBX, read its meshes / bones / weights |
| `tools/kalina_on_mannequin.py` | **The core step** (Blender, headless): re-skin the source mesh onto the mannequin skeleton, write an FBX |
| `tools/import_kalina_mannequin.py` | Run in the editor: import that FBX onto `SK_Mannequin`, build materials from the game's textures, **verify every bone frame** |
| `tools/kalina_original_export.py` | Optional: textured T-pose / rest-pose exports from the same source (for re-rigging elsewhere) |
| `tools/Run-UEPython.ps1` | Runs an editor Python script headlessly (switches the Python plugins on, then restores the `.uproject`) |
| `unreal-source/PipecatPlayerAvatar.*` | The runtime component that swaps the player's mesh at play start |
| `unreal-source/PipecatJiggleComponent.*` | Optional breast / glute spring physics for the helper bones added in step 2 |

(The scripts expect the project at `C:\AIProjects\PipecatUnreal`; change `ROOT` at the top of each to relocate.)

## The method

### 1. Measure the target skeleton
`tools\Run-UEPython.ps1 -Script tools\dump_mannequin.py` writes `mannequin_skeleton.json`: every bone's name, parent
and global transform, as Unreal stores them. This is the ground truth the new mesh must match.

### 2. Re-skin in Blender (`kalina_on_mannequin.py`)
```
blender -b -P tools\kalina_on_mannequin.py -- <source.fbx> <out.fbx> [test_render_dir]
```
* **Build the mannequin armature in Blender from the JSON.** Unreal's FBX round trip mirrors Y, so the script applies
  the measured mirror when converting the transforms; bone names, hierarchy and rest frames then match `SK_Mannequin`
  exactly.
* **Keep the source vertices.** No vertex is edited except by two deliberate steps:
  1. the character's **arms are rotated to the mannequin's A-pose directions**, so stock animations land correctly;
  2. the model is **scaled to centimetres**.
* **Merge the skin weights by bone name.** Each source bone folds into its mannequin counterpart (the source had 126
  `Bip001` bones; hair, ears, eyes and helper bones fold into head / spine / limbs). Source groups with no mapping fold into their
  parent's mapping (the script prints that list), and vertices left with no weight go to the pelvis (also printed).
* **Optional extra bones.** Dedicated chest / hip helper bones become real bones (`jiggle_breast_l/r` under
  `spine_05`, `jiggle_glute_l/r` under `pelvis`) with their own weights, for the jiggle component.
* It prints the worst bone-frame deviation from the mannequin and can render test images (third argument), so you can
  check the result in Blender before Unreal.

### 3. Import onto the *default* skeleton (`import_kalina_mannequin.py`)
Import the FBX with the existing `/Game/Characters/Mannequins/Meshes/SK_Mannequin` as the target skeleton (not "create
new"), then create materials from the source's textures. The script **then checks all bone frames** against the
mannequin's: for this model, all 89 matched within 0.002°. If that check fails, don't ship it.
Result: `/Game/KalinaMannequin/SK_Kalina_Mannequin`.

> Adding the four jiggle bones **modifies the shared `SK_Mannequin` skeleton asset**. Back it up first; the stock
> mannequin meshes are unaffected.

### 4. Make it the player body (`PipecatPlayerAvatar`)
```cpp
Body = Character->GetMesh();
Body->SetSkeletalMeshAsset(NewMesh);   // same skeleton => AnimBP, animations, capsule offset, camera all unchanged
```
Run it from your subsystem / game mode at play start (`-PipecatNoAvatar` keeps the stock mannequin).

### Gotchas worth knowing
* **Hair looked wrong:** the hair texture's alpha channel was specular data in the original shader, not a cut-out.
  Draw it opaque.
* **Early attempts came out deformed.** The version that works keeps the original vertices and only changes the arm
  pose and the scale; edits beyond that (and a route through the game's pak) were dropped.
* **Verify both sides** with front and back renders, and in the reference pose with no animation, before trusting it.
* Skin weights merged *by name* is the whole trick. A bone with no mapping falls onto its parent's, which is fine for
  hair and accessories but wrong for a limb, so read the unmapped list the script prints.

### Related
* VR first-person with this avatar (head hidden, arms solved to the controllers, jiggle re-applied on a poseable copy)
  is a separate component in the main project (`PipecatVRComponent`).
