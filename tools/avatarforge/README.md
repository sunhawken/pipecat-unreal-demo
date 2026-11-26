# AvatarForge

Turn **any rigged humanoid model** into the player avatar of this Unreal project, automatically, with a window to check
and fix anything it is unsure about.

It does the "1:1 method" (see `avatar-pipeline/README.md`) for you: the model is **re-skinned onto the default mannequin
skeleton** (`SK_Mannequin`), so every stock animation, the animation Blueprint, the capsule and the camera keep working
untouched.

```
model (.fbx .glb .gltf .blend .dae)
   |  1 Inspect        Blender, headless: bones in world space, which bones deform the mesh, meshes, materials
   |  2 Auto-map       bone names -> mannequin bones (Mixamo, Biped/Bip001, VRM, Rigify-ish, UE, ...), checked 5 ways
   |  3 Convert        Blender: upright + facing, scale to cm, arms to the mannequin's A-pose, merge skin weights,
   |                   build the mannequin skeleton at this body's joints, textured previews, FBX
   |  4 Import         Unreal (editor closed): textures, materials, mesh bound to SK_Mannequin, every bone frame verified
   |  5 Set as avatar  writes Config/PipecatAvatar.txt; the game's UPipecatPlayerAvatar reads it at play start
```

## Use

Double-click **Avatar Forge** on the desktop (`tools\AvatarForge.pyw`), or:

```
python -m avatarforge                       # the window
python -m avatarforge run MODEL.fbx --name Hero [--no-ue] [--scale auto|1|100|0.01] [--no-preview]
python -m avatarforge map MODEL.fbx         # just show the bone mapping
```

In the window: **Open model**, then **Do everything**. The tabs let you review:

* **Bones** - every avatar bone and the bone of your model it uses (green = sure, amber = guessed, red = missing and
  required, blue = set by you). Double-click a row to choose another bone.
* **Materials & hair** - textures found, and the alpha decision per material (below). Override it with one click.
* **Options** - scale (auto picks 1 / 100 / 0.01... so the body lands near 175 cm), the A-pose step, previews.

Work files (inspect data, bone map, FBX, previews, logs) live in `avatars\<name>\`; every step can be re-run.
Needs **Blender** (found automatically, or set `AVATARFORGE_BLENDER`) and **Unreal Engine** (`UE_ROOT`).
`-PipecatAvatarMesh=/Game/...` on the game's command line overrides the installed avatar; delete
`Config/PipecatAvatar.txt` to go back to the built-in one.

## Partial, static and messy models

Real exports are rarely clean. AvatarForge handles:

* **Duplicates, strays and decals** - exact duplicate meshes are dropped (the skinned copy is kept), parts far from the body
  (a prop left at another scene's origin) and tiny unskinned floor objects are left out. The **Parts** tab shows each
  decision and lets you override it.
* **A body with no skin weights** (a static mesh next to a partial skeleton) - a mannequin-shaped skeleton is fitted to the
  body and the weights are computed automatically (bone-heat), with a nearest-bone fallback for any vertex the solver
  misses. Test case: `Model_Hero_Nymset_S06` from the Horizon Walker gallery (static body, head/hair/clothing rigged,
  no legs or fingers, every mesh duplicated, a book prop 250 units away): 7,706 body vertices auto-rigged, 26 needed the
  fallback.
* **Bones the model lacks** (legs, hands, fingers of a partial rig) - placed from the mannequin's proportions: torso ratio for
  the trunk, the pelvis height above the floor for the legs, the arm length for the arms. No hand bone? The wrist joint is used.
* **Wrong orientation or units** - Y-up, lying on its back, millimetres or metres: orientation and scale come from the joints.

## Is the shape 1:1?

Every conversion ends with a **shape check**: each vertex is compared with where the model had it (upright, in cm).
With **"Rotate the arms to the mannequin's A-pose" OFF the result is exactly the original: 0 of 15,751 vertices moved** on the
Nymset test. With it ON (default) only the arms and gloves move toward the mannequin's arm direction (3,954 vertices, up to
15.8 cm at the hands on that model; face and hair stay exact), which makes the stock animations' arm swing land correctly.
Choose the exact pose when fidelity matters more than the animation's arm angle.

## What makes it precise

* **Bone mapping, in layers** (`core/bonemap.py`): names are normalised (Mixamo/Biped/VRM prefixes stripped, camelCase and
  digits split, L/R/Left/Right recognised); several claimants for a role are resolved by *which bone really deforms the
  mesh*; arm and leg chains must be parent -> child; joints must sit where the mannequin has them (as fractions of body
  height); and **left/right is cross-checked against the toe direction** and swapped if a rig's names disagree with its
  shape. Missing required bones get a geometric guess (flagged low confidence).
* **Orientation and scale** come from the mapped joints, not from file metadata: a model lying on its back, Y-up, in
  millimetres or in metres lands upright, facing the right way, at a sane height.
* **Skin weights** are merged by bone name; unmapped bones fold into their nearest mapped ancestor, so hair, ears, eyes,
  cloth and helpers stay attached. Breast/glute helper bones become the project's four `jiggle_*` bones (used by the jiggle
  physics); a model without them still gets those bones, unweighted.
* **Bone frames are exact**: every mannequin bone keeps the mannequin's own frame (checked in Blender, then again in
  Unreal: 0.002 degrees on the Kalina test).
* Only two things are done to the vertices: the arms are rotated to the mannequin's A-pose, and the model is scaled.

## Hair and transparency (the "hair fixes")

Many models store something other than transparency in the diffuse texture's alpha channel (one game keeps *specular
data* there; using it as a mask makes the hair almost vanish, which is exactly what first happened with Kalina). So every
material's alpha is **analysed** (`blender/alpha_probe.py`) and classified:

| Alpha looks like | Treated as |
|---|---|
| mostly 0 and 1, with real holes, and a usable amount visible | **cut-out mask**: masked blend mode (never translucent, no sorting artefacts), two-sided |
| continuous values, or almost entirely near zero (>90% clear) | **data, not transparency**: drawn opaque |
| no alpha channel | opaque |

Hair / lash / brow / fur / feather cards are always two-sided, rougher, and shown with the same decision in the
previews as in Unreal. Eyes, skin and cut-out props (leaves, fences, lace) are recognised by name. You can force opaque /
cut-out / two-sided per material in the **Materials & hair** tab.

## Limits (be aware)

* Humanoid, bipedal, one skeleton. Quadrupeds and models with no skeleton are rejected with a clear message.
* Shape keys (face expressions) are dropped; the basis shape is kept. Animations in the source are not imported.
* Unreal must be closed for the import (it runs the editor headless). Adding the jiggle bones modifies the shared
  `SK_Mannequin` skeleton asset (back it up once; stock meshes are unaffected).
* Textures are found next to the model by name (base colour / normal / roughness / metallic); anything unusual can be
  fixed by renaming or by editing the material in Unreal afterwards.

## Tests

```
cd tools\avatarforge\tests
python -m unittest test_bonemap test_textures       # 20 tests, no Blender or Unreal needed
```
`tests/make_variant.py` builds a disguised copy of a model (renamed to Mixamo bones, laid on its back, scaled) to prove
the whole pipeline lands on the same result regardless of how the rig was authored.
