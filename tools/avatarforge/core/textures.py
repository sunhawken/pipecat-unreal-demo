"""Find a model's texture files next to it and assign them to materials (base colour, normal, roughness, metallic)."""
from __future__ import annotations

import os
import re

from .bonemap import tokens as _tok

EXT = (".png", ".jpg", ".jpeg", ".tga", ".bmp")
TYPES = {
    "base": {"diffuse", "albedo", "basecolor", "color", "base", "diff", "col", "colour", "bc"},
    "normal": {"normal", "norm", "nrm", "nor", "nrml"},
    "rough": {"roughness", "rough", "rgh"},
    "metal": {"metallic", "metal", "metalness", "met"},
}
SKIP = {"id", "mask", "shadow", "lightmap", "sgv", "matcap", "glow", "ao", "occlusion", "emissive", "emission", "spec",
        "specular", "height", "disp", "displacement", "opacity", "alpha", "thumbnail", "icon", "preview", "sss", "curvature"}
TRIVIAL = {"tex", "texture", "mat", "material", "m", "t", "png", "jpg", "d", "n"}


def _words(stem):
    return [t for t in _tok(stem) if not t.isdigit() or len(t) > 1] or _tok(stem)


def scan(folder: str, depth: int = 3) -> list[str]:
    out = []
    base_depth = folder.rstrip("\\/").count(os.sep)
    for root, dirs, files in os.walk(folder):
        if root.count(os.sep) - base_depth >= depth:
            dirs[:] = []
        for f in files:
            if f.lower().endswith(EXT):
                out.append(os.path.join(root, f))
    return out


def discover(folder: str, materials: list[str]) -> dict[str, dict]:
    """{material name: {"base","normal","rough","metal"}} using name overlap and type keywords in the file names."""
    files = scan(folder)
    info = []
    for p in files:
        stem = os.path.splitext(os.path.basename(p))[0]
        ws = _words(stem)
        wset = set(ws)
        typ = next((t for t, keys in TYPES.items() if wset & keys), None)
        skip = bool(wset & SKIP) and typ is None
        ident = {w for w in ws if w not in TRIVIAL and w not in SKIP and not any(w in k for k in TYPES.values())}
        info.append({"path": p, "type": typ, "skip": skip, "ident": ident, "wset": wset})
    out = {}
    for mat in materials:
        mset = {w for w in _words(mat) if w not in TRIVIAL}
        res = {}
        scored = []
        for f in info:
            if f["skip"] and not f["type"]:
                continue
            shared = len(mset & f["ident"])
            if shared == 0 and not (len(info) == 1):
                continue
            # untyped file whose words are all in the material name counts as the base colour
            typ = f["type"] or ("base" if f["ident"] and f["ident"] <= mset | {"v1", "v2"} else None)
            if typ is None:
                continue
            extra = len(f["ident"] - mset)
            scored.append((typ, shared - 0.25 * extra, f["path"]))
        for typ in TYPES:
            best = sorted([s for s in scored if s[0] == typ], key=lambda s: -s[1])
            if best and best[0][1] > 0:
                res[typ] = best[0][2]
        out[mat] = res
    return out


CARD_WORDS = {"hair", "lash", "lashes", "eyelash", "eyelashes", "brow", "eyebrow", "eyebrows", "fur", "feather", "feathers",
              "bangs", "ponytail", "braid", "beard", "mustache", "wig", "fringe"}
CUTOUT_WORDS = {"leaf", "leaves", "fence", "grass", "chain", "lace", "net", "mesh", "fishnet", "wing", "wings", "cape"}


def material_class(name: str) -> str:
    ws = set(_tok(name))
    if ws & CARD_WORDS:
        return "hair"
    if ws & CUTOUT_WORDS:
        return "cutout"
    if ws & {"eye", "eyes", "cornea", "iris", "eyeball"}:
        return "eye"
    if ws & {"skin", "body", "face", "head", "torso"}:
        return "skin"
    return "other"


def decide_alpha(name: str, st: dict | None, blender_masked: bool, cls_hint: str | None = None) -> tuple[str, str]:
    """(alpha_mode, why).  'masked' = the alpha is a real cut-out (hair cards, lashes, leaves...), 'opaque' = the alpha channel
    is data (e.g. specular in some games' shaders) or absent and must NOT be used as transparency."""
    cls = cls_hint or material_class(name)
    if st and st.get("none"):
        return "opaque", "the texture has no alpha channel (or it is solid): importers flag transparency anyway, ignored"
    if st is None:
        return ("masked", "the source material uses transparency") if blender_masked else ("opaque", "no alpha channel in the texture")
    # A real cut-out is mostly 0 and 1 with real holes AND leaves a usable amount of the texture visible. An alpha that is
    # almost entirely near zero (>90% clear) would make the mesh vanish: it is data (e.g. specular), not a mask.
    cut = 0.04 <= st["transparent"] <= 0.90 and st["mid"] <= 0.30
    if cut:
        return "masked", "alpha is a cut-out mask (%.0f%% clear, %.0f%% soft)" % (st["transparent"] * 100, st["mid"] * 100)
    if cls in ("hair", "cutout") and 0.01 <= st["transparent"] <= 0.90 and st["mid"] <= 0.5:
        return "masked", "%s texture with a few clear pixels (%.0f%%)" % (cls, st["transparent"] * 100)
    return "opaque", "alpha is continuous data, not a mask (%.0f%% clear, %.0f%% soft): drawn opaque" % (
        st["transparent"] * 100, st["mid"] * 100)


def merge(materials: list[dict], found: dict[str, dict], stats: dict | None = None) -> list[dict]:
    """Blender-resolved paths win; discovery fills the gaps. Sets alpha_mode (from the alpha analysis), two_sided and the
    material class (hair cards are always two-sided, rougher and never translucent-sorted)."""
    stats = stats or {}
    out = []
    for m in materials:
        rec = dict(m)
        f = found.get(m["name"], {})
        for k in ("base", "normal", "rough", "metal"):
            if not rec.get(k) and f.get(k):
                rec[k] = f[k]
        st = stats.get(rec.get("base")) if rec.get("base") else None
        rec["alpha_stats"] = st
        rec["class"] = material_class(m["name"])
        if rec["class"] == "other":   # glTF exports call every material "Material_3": the mesh names say what it is
            for mn in m.get("meshes", []):
                c = material_class(mn)
                if c != "other":
                    rec["class"] = c
                    break
        mode, why = decide_alpha(m["name"], st, m.get("alpha_mode") == "masked", rec["class"])
        rec["alpha_mode"], rec["alpha_why"] = mode, why
        # two-sided only where it matters (cards that are seen from behind); the source's own flag is not trusted because
        # importers set it for every material
        rec["two_sided"] = rec["class"] in ("hair", "cutout") or mode == "masked"
        out.append(rec)
    return out


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_") or "Avatar"
