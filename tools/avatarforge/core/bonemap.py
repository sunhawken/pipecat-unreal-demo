"""Automatic bone mapping: any humanoid rig -> the default Unreal mannequin (SK_Mannequin) bone names.

Pure Python (no Blender, no Unreal) so it can be tested on its own.

Input  : a list of source bones, each {"name", "parent", "head": [x,y,z], "weighted": bool}  (world space, Z up)
Output : Mapping with
           .slots   mannequin bone -> {"bone": source bone, "conf": 0..1, "how": "name"|"geometry"|"manual"}
           .warnings, .errors
and helpers to turn that into a per-source-bone weight map and to find the model's orientation.

How it decides (high precision, in layers):
  1. names   : normalise (strip Mixamo/Biped/VRM/Rigify prefixes, split camelCase and digits), recognise side
               (L/R/Left/Right/.l/_l) and role (hips, spine, neck, head, clavicle, upper arm, forearm, hand, fingers,
               thigh, calf, foot, toe), twist helpers, breast / glute helpers.
  2. weights : when several bones claim a role (ORG/DEF/MCH copies), the one that actually deforms the mesh wins.
  3. topology: arm and leg chains must be parent -> child (upper arm > forearm > hand ...), spine ordered by depth.
  4. geometry: joints are compared with where the mannequin has them (as fractions of body height); outliers are warned
               about and, for missing slots, the nearest unclaimed bone is suggested.
  5. sides   : left/right is cross-checked against the toe direction and swapped if the rig's names disagree with its shape.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

SIDES = ("l", "r")
FINGER_NAMES = ("thumb", "index", "middle", "ring", "pinky")
CORE_SINGLE = ["pelvis", "neck_01", "neck_02", "head"]
SPINE = ["spine_01", "spine_02", "spine_03", "spine_04", "spine_05"]
LIMB = ["clavicle", "upperarm", "lowerarm", "hand", "thigh", "calf", "foot", "ball"]
JIGGLE = ["jiggle_breast_l", "jiggle_breast_r", "jiggle_glute_l", "jiggle_glute_r"]
HARD = ["pelvis", "head"]            # without these nothing can be placed
REQUIRED = ["pelvis", "head"] + [f"{b}_{s}" for b in ("upperarm", "lowerarm", "hand", "thigh", "calf", "foot") for s in SIDES]

JUNK = {"mixamorig", "bip", "biped", "valvebiped", "def", "org", "mch", "tgt", "jnt", "joint", "bone", "sk", "cc", "rig",
        "armature", "root", "j", "bn", "b", "c", "mixamo", "character", "char", "chr", "skel", "skeleton", "genesis", "g"}
IGNORE = {"twist", "roll", "corrective", "helper", "end", "nub", "tip", "ik", "pole", "target", "ctrl", "control",
          "top", "leaf", "shape", "dummy", "offset", "stretch", "fk", "socket", "weapon", "prop", "cloth", "skirt", "cape"}
FINGER_ALIASES = {"thumb": "thumb", "index": "index", "pointer": "index", "middle": "middle", "mid": "middle",
                  "ring": "ring", "pinky": "pinky", "little": "pinky", "pinkie": "pinky", "pinki": "pinky"}


# ------------------------------------------------------------------------------------------------------------------
def tokens(name: str) -> list[str]:
    s = re.split(r"[:|]", name)[-1]
    s = re.sub(r"(?i)\bbip0*1\b", " ", s)
    s = re.sub(r"(?i)bip0*1", " ", s)
    s = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", s)       # LHand -> L Hand
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)            # UpperArm -> Upper Arm
    s = re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)
    s = re.sub(r"(\d)([A-Za-z])", r"\1 \2", s)
    return [t for t in re.split(r"[^A-Za-z0-9]+", s.lower()) if t]


def side_of(toks: list[str]) -> str | None:
    for t in toks:
        if t in ("l", "left", "lt", "lft"):
            return "l"
        if t in ("r", "right", "rt", "rgt"):
            return "r"
    return None


def classify(name: str) -> dict | None:
    """-> {"role": str, "side": 'l'|'r'|None, "seg": int|None, "finger": str|None} or None when it is not a core bone."""
    toks = tokens(name)
    if not toks:
        return None
    side = side_of(toks)
    core = [t for t in toks if t not in JUNK and t not in ("l", "left", "lt", "lft", "r", "right", "rt", "rgt")]
    cset = set(core)
    raw_digits = [t for t in core if t.isdigit()]
    digits = [int(t) for t in raw_digits]
    words = [t for t in core if not t.isdigit()]
    wset = set(words)

    # breast / glute helpers first (they carry the jiggle bones)
    if wset & {"breast", "boob", "boobs", "bust", "mune", "oppai", "tit"}:
        return {"role": "breast", "side": side, "seg": digits[0] if digits else None, "finger": None}
    if wset & {"glute", "butt", "ass", "oshiri", "buttock", "gluteus"} or (
            "hip" in wset and side and not wset & {"hips", "pelvis"} and "root" not in cset):
        return {"role": "glute", "side": side, "seg": None, "finger": None}

    # biped "Finger21": finger index digit then segment digit
    if "finger" in wset and raw_digits:
        d = raw_digits[0]
        if len(d) == 2:
            fi, sg = int(d[0]), int(d[1]) + 1
        else:
            fi, sg = int(d), 1
        if 0 <= fi <= 4:
            return {"role": "finger", "side": side, "seg": sg, "finger": FINGER_NAMES[fi]}
    for w in words:
        if w in FINGER_ALIASES:
            if wset & {"metacarpal", "meta", "carpal"}:
                return None
            seg = digits[0] if digits else None
            return {"role": "finger", "side": side, "seg": seg, "finger": FINGER_ALIASES[w]}
    # twist helpers keep their limb: forearm twist etc. map to the twist bones, everything else folds to the parent
    if wset & {"twist", "roll"}:
        for key, role in (("forearm", "lowerarm_twist"), ("lowerarm", "lowerarm_twist"), ("upperarm", "upperarm_twist"),
                          ("thigh", "thigh_twist"), ("calf", "calf_twist")):
            if key in wset:
                return {"role": role, "side": side, "seg": digits[0] if digits else None, "finger": None}
        if "fore" in wset:
            return {"role": "lowerarm_twist", "side": side, "seg": digits[0] if digits else None, "finger": None}
        if "upper" in wset and "arm" in wset:
            return {"role": "upperarm_twist", "side": side, "seg": digits[0] if digits else None, "finger": None}
        return None
    if wset & IGNORE:
        return None

    def has(*ws):
        return all(w in wset for w in ws)

    role = None
    if "head" in wset:
        role = "head"
    elif "neck" in wset:
        role = "neck"
    elif wset & {"hips", "pelvis"}:
        role = "pelvis"
    elif wset & {"spine", "chest", "upperchest", "torso", "abdomen", "stomach", "belly"}:
        role = "spine"
    elif wset & {"clavicle", "collar", "shoulder"}:
        role = "clavicle"
    elif "forearm" in wset or "lowerarm" in wset or has("fore", "arm") or has("lower", "arm"):
        role = "lowerarm"
    elif "upperarm" in wset or has("upper", "arm") or "uparm" in wset or "arm" in wset:
        role = "upperarm"
    elif "hand" in wset:
        role = "hand"
    elif "wrist" in wset:
        role = "wrist"                  # only used for the hand when the rig has no hand bone
    elif wset & {"thigh", "upleg", "upperleg", "femur"} or has("up", "leg") or has("upper", "leg"):
        role = "thigh"
    elif wset & {"calf", "shin", "lowerleg"} or has("lower", "leg") or "leg" in wset:
        role = "calf"
    elif "foot" in wset:
        role = "foot"
    elif wset & {"toe", "toes", "toebase", "ball"}:
        role = "ball"
    if role is None:
        return None
    seg = digits[0] if digits else None
    return {"role": role, "side": side, "seg": seg, "finger": None}


# ------------------------------------------------------------------------------------------------------------------
@dataclass
class Mapping:
    slots: dict = field(default_factory=dict)      # mannequin bone -> {"bone","conf","how"}
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    swapped_sides: bool = False

    def source_to_slot(self) -> dict:
        out = {}
        for slot, v in self.slots.items():
            out.setdefault(v["bone"], slot)
        return out

    def to_json(self):
        return {"slots": self.slots, "warnings": self.warnings, "errors": self.errors, "swapped_sides": self.swapped_sides}

    @staticmethod
    def from_json(d):
        return Mapping(d.get("slots", {}), d.get("warnings", []), d.get("errors", []), d.get("swapped_sides", False))


class Rig:
    def __init__(self, bones):
        self.bones = {b["name"]: b for b in bones}
        self.children = {}
        for b in bones:
            self.children.setdefault(b.get("parent"), []).append(b["name"])
        self._depth = {}

    def depth(self, n):
        if n not in self._depth:
            p = self.bones[n].get("parent")
            self._depth[n] = 0 if (p is None or p not in self.bones) else self.depth(p) + 1
        return self._depth[n]

    def is_ancestor(self, a, b):
        p = self.bones[b].get("parent")
        while p and p in self.bones:
            if p == a:
                return True
            p = self.bones[p].get("parent")
        return False

    def pos(self, n):
        return self.bones[n]["head"]


def _pick(cands, rig):
    """Prefer bones that deform the mesh, then the shallowest."""
    return sorted(cands, key=lambda n: (not rig.bones[n].get("weighted", True), rig.depth(n), n))


def automap(bones: list[dict], mannequin: dict | None = None) -> Mapping:
    rig = Rig(bones)
    m = Mapping()
    cls = {n: classify(n) for n in rig.bones}
    roles: dict[tuple, list] = {}
    for n, c in cls.items():
        if not c:
            continue
        roles.setdefault((c["role"], c["side"], c["finger"]), []).append(n)

    def put(slot, bone, conf=1.0, how="name"):
        m.slots[slot] = {"bone": bone, "conf": conf, "how": how}

    # --- singles
    first = lambda key: (_pick(roles.get(key, []), rig) or [None])[0]
    if (p := first(("pelvis", None, None))):
        put("pelvis", p)
    if (h := first(("head", None, None))):
        put("head", h)
    necks = [n for n in _pick(roles.get(("neck", None, None), []), rig)]
    necks.sort(key=lambda n: rig.depth(n))
    for slot, n in zip(("neck_01", "neck_02"), necks):
        put(slot, n)
    # --- spine: all spine-ish bones in hierarchy order, spread over the mannequin's five spine slots
    sp = sorted(roles.get(("spine", None, None), []), key=lambda n: (rig.depth(n), n))
    sp = [n for n in sp if rig.bones[n].get("weighted", True)] or sp
    if sp:
        n = len(sp)
        idx = [2] if n == 1 else [round(i * 4 / (n - 1)) for i in range(n)] if n <= 5 else [0, 1, 2, 3, 4]
        for slot_i, bone in zip(idx, sp if n <= 5 else [sp[0], sp[n // 4], sp[n // 2], sp[3 * n // 4], sp[-1]]):
            put(SPINE[slot_i], bone)
    # --- limbs by side
    unsided = {}
    for base in LIMB:
        for s in SIDES:
            cands = _pick(roles.get((base, s, None), []), rig)
            if cands:
                put(f"{base}_{s}", cands[0])
        both = _pick(roles.get((base, None, None), []), rig)
        if both:
            unsided[base] = both
    # sides missing from names: split the pair by lateral position (assumes the model faces -Y, left = +X)
    for base, cands in unsided.items():
        if len(cands) >= 2 and f"{base}_l" not in m.slots and f"{base}_r" not in m.slots:
            xs = sorted(cands[:2], key=lambda n: -rig.pos(n)[0])
            put(f"{base}_l", xs[0], 0.5, "geometry")
            put(f"{base}_r", xs[1], 0.5, "geometry")
            m.warnings.append(f"{base}: no L/R in the bone names, split by position (left = +X)")
    # --- a rig without hand bones: the wrist joint is where the hand bone goes
    for s in SIDES:
        if f"hand_{s}" not in m.slots:
            w = _pick(roles.get(("wrist", s, None), []), rig)
            if w:
                put(f"hand_{s}", w[0], 0.6, "name")
                m.warnings.append(f"hand_{s}: no hand bone, using the wrist joint '{w[0]}'")
    # --- fingers
    for s in SIDES:
        for f in FINGER_NAMES:
            cands = roles.get(("finger", s, f), [])
            if not cands:
                continue
            ordered = sorted(cands, key=lambda n: (rig.depth(n), n))
            for i, n in enumerate(ordered[:3]):
                put(f"{f}_0{i + 1}_{s}", n)
    # --- twist helpers
    for s in SIDES:
        for role, slot in (("lowerarm_twist", "lowerarm_twist_01"), ("upperarm_twist", "upperarm_twist_01"),
                           ("thigh_twist", "thigh_twist_01"), ("calf_twist", "calf_twist_01")):
            c = _pick(roles.get((role, s, None), []), rig)
            if c:
                put(f"{slot}_{s}", c[0], 0.9)
    # --- jiggle helpers (breast / glute), by weights
    for role, slot in (("breast", "jiggle_breast"), ("glute", "jiggle_glute")):
        for s in SIDES:
            c = [n for n in roles.get((role, s, None), []) if rig.bones[n].get("weighted", True)]
            if c:
                put(f"{slot}_{s}", sorted(c, key=lambda n: (rig.depth(n), n))[0], 0.8)

    _validate(rig, m, mannequin)
    return m


# ------------------------------------------------------------------------------------------------------------------
def _validate(rig: Rig, m: Mapping, mannequin: dict | None):
    chains = [("upperarm", "lowerarm", "hand"), ("thigh", "calf", "foot")]
    for s in SIDES:
        for chain in chains:
            names = [m.slots.get(f"{b}_{s}", {}).get("bone") for b in chain]
            for a, b, ca, cb in zip(names, names[1:], chain, chain[1:]):
                if a and b and not rig.is_ancestor(a, b):
                    m.warnings.append(f"{ca}_{s} ({a}) is not an ancestor of {cb}_{s} ({b}): check this chain")
    for req in HARD:
        if req not in m.slots:
            m.errors.append(f"no bone found for '{req}'; pick one in the table")
    soft = [r for r in REQUIRED if r not in HARD and r not in m.slots]
    if soft:
        m.warnings.append("not in the model (placed by the mannequin's proportions; an unweighted body mesh is rigged "
                          "automatically): " + ", ".join(soft))
    # left/right sanity: the two sides' joints must be on opposite sides of the body
    for base in ("upperarm", "thigh", "hand", "foot"):
        a, b = m.slots.get(f"{base}_l"), m.slots.get(f"{base}_r")
        if a and b and a["bone"] == b["bone"]:
            m.errors.append(f"{base}: left and right resolve to the same bone '{a['bone']}'")
    # vertical position sanity against the mannequin (fractions of body height)
    if mannequin and "pelvis" in m.slots and "head" in m.slots:
        zs = [b["head"][2] for b in rig.bones.values()]
        zmin, zmax = min(zs), max(zs)
        height = max(zmax - zmin, 1e-6)
        q = {b["name"]: b for b in mannequin["bones"]}
        qz = [b["pos"][2] for b in mannequin["bones"] if not b["name"].startswith(("ik_", "interaction", "center", "root"))]
        qmin, qmax = min(qz), max(qz)
        for slot, v in m.slots.items():
            if slot not in q:
                continue
            exp = (q[slot]["pos"][2] - qmin) / max(qmax - qmin, 1e-6)
            got = (rig.pos(v["bone"])[2] - zmin) / height
            if abs(exp - got) > 0.18 and not slot.startswith(("jiggle", "thumb", "index", "middle", "ring", "pinky", "clavicle", "upperarm", "lowerarm", "hand")):
                m.warnings.append(f"{slot} = '{v['bone']}' sits at {got:.2f} of the body height; the mannequin has it at {exp:.2f}")
                v["conf"] = min(v["conf"], 0.4)


def geometry_warnings(rig_bones: list[dict], m: Mapping, mannequin: dict) -> None:
    """Re-run the body-proportion sanity check on bones that are already upright (Z up); updates m.warnings / confidences."""
    tmp = Mapping({k: dict(v) for k, v in m.slots.items()})
    _validate(Rig(rig_bones), tmp, mannequin)
    for w in tmp.warnings:
        if w not in m.warnings:
            m.warnings.append(w)
    for k, v in tmp.slots.items():
        m.slots[k]["conf"] = min(m.slots[k]["conf"], v["conf"])


def geometric_fill(rig_bones: list[dict], m: Mapping, mannequin: dict):
    """Suggest bones for still-missing required slots: the nearest unclaimed (weighted) bone to where the mannequin has it,
    scaled to this body. Assumes Z up and tries the four yaw rotations."""
    rig = Rig(rig_bones)
    need = [s for s in HARD if s not in m.slots]
    if not need or "pelvis" not in m.slots or "head" not in m.slots:
        return
    q = {b["name"]: b for b in mannequin["bones"]}
    qp, qh = q["pelvis"]["pos"], q["head"]["pos"]
    p, h = rig.pos(m.slots["pelvis"]["bone"]), rig.pos(m.slots["head"]["bone"])
    scale = (h[2] - p[2]) / max(qh[2] - qp[2], 1e-6)
    taken = {v["bone"] for v in m.slots.values()}
    best = {}
    for yaw in range(4):
        c, s_ = math.cos(yaw * math.pi / 2), math.sin(yaw * math.pi / 2)
        tot, pick = 0.0, {}
        for slot in need:
            dx, dy, dz = (q[slot]["pos"][i] - qp[i] for i in range(3))
            dx, dy = dx, -dy   # mannequin y is mirrored in Blender
            ex = p[0] + (dx * c - dy * s_) * scale
            ey = p[1] + (dx * s_ + dy * c) * scale
            ez = p[2] + dz * scale
            cand = [n for n in rig.bones if n not in taken and rig.bones[n].get("weighted", True)]
            if not cand:
                tot += 9
                continue
            n = min(cand, key=lambda n: math.dist(rig.pos(n), (ex, ey, ez)))
            d = math.dist(rig.pos(n), (ex, ey, ez))
            tot += d
            pick[slot] = (n, d)
        if not best or tot < best[0]:
            best = (tot, pick)
    height = max(h[2] - p[2], 1e-6) * 2
    for slot, (n, d) in best[1].items():
        if d < 0.12 * height and n not in {v["bone"] for v in m.slots.values()}:
            m.slots[slot] = {"bone": n, "conf": 0.35, "how": "geometry"}
            m.warnings.append(f"{slot}: guessed '{n}' from its position (low confidence)")
    m.errors = [e for e in m.errors if not any(e.startswith(f"no bone found for '{s}'") and s in m.slots for s in need)]


def fix_sides_by_toes(rig_bones: list[dict], m: Mapping):
    """If the rig's L/R names disagree with its shape (left foot's toe pointing the wrong way relative to the lateral
    axis), swap sides. Needs hips/feet/toes mapped. Z up."""
    rig = Rig(rig_bones)
    try:
        fl, fr = (rig.pos(m.slots[f"foot_{s}"]["bone"]) for s in SIDES)
        tl = rig.pos(m.slots["ball_l"]["bone"])
        tr = rig.pos(m.slots["ball_r"]["bone"])
    except KeyError:
        return
    lat = _norm((fl[0] - fr[0], fl[1] - fr[1], 0.0))
    fwd = _norm(((tl[0] - fl[0]) + (tr[0] - fr[0]), (tl[1] - fl[1]) + (tr[1] - fr[1]), 0.0))
    # facing -Y with left=+X is the convention; character-left x character-up = forward.  left x up:
    expected = _cross(lat, (0, 0, 1))
    if _dot(expected, fwd) < -0.3:
        for base in LIMB + [f"{f}_0{i}" for f in FINGER_NAMES for i in (1, 2, 3)] + ["jiggle_breast", "jiggle_glute"]:
            a, b = m.slots.get(f"{base}_l"), m.slots.get(f"{base}_r")
            if a or b:
                if a:
                    m.slots[f"{base}_r"] = a
                else:
                    m.slots.pop(f"{base}_r", None)
                if b:
                    m.slots[f"{base}_l"] = b
                else:
                    m.slots.pop(f"{base}_l", None)
        m.swapped_sides = True
        m.warnings.append("left/right names disagreed with the toe direction: sides were swapped")


# ------------------------------------------------------------------------------------------------------------------
def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return tuple(x / n for x in v)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def orientation(rig_bones: list[dict], m: Mapping, left_sign: float = 1.0) -> list[list[float]]:
    """3x3 rotation (row-major) that turns the model upright (+Z), facing -Y with its left on +left_sign*X, from the mapped
    joints. left_sign comes from the mannequin (the sign of upperarm_l.x in Blender coordinates)."""
    rig = Rig(rig_bones)
    P = lambda slot: rig.pos(m.slots[slot]["bone"])
    if all(f"foot_{s}" in m.slots for s in SIDES):
        feet = [P(f"foot_{s}") for s in SIDES]
        base = tuple((feet[0][i] + feet[1][i]) / 2 for i in range(3))
    else:                                   # a partial rig with no legs: the torso axis (pelvis -> head) is the up direction
        base = tuple(P("pelvis"))
    up = _norm(tuple(P("head")[i] - base[i] for i in range(3)))
    # snap a nearly axis-aligned up so tiny skew in the rig does not tilt the model
    for ax in range(3):
        for sg in (1, -1):
            e = [0, 0, 0]
            e[ax] = sg
            if _dot(up, e) > math.cos(math.radians(6)):
                up = tuple(e)
    lat_pairs = [("upperarm", "upperarm"), ("thigh", "thigh"), ("hand", "hand"), ("foot", "foot")]
    lat = [0.0, 0.0, 0.0]
    for a, _ in lat_pairs:
        if f"{a}_l" in m.slots and f"{a}_r" in m.slots:
            d = [P(f"{a}_l")[i] - P(f"{a}_r")[i] for i in range(3)]
            lat = [lat[i] + d[i] for i in range(3)]
    lat = _norm(tuple(lat[i] - up[i] * _dot(lat, up) for i in range(3)))
    for ax in range(3):
        for sg in (1, -1):
            e = [0, 0, 0]
            e[ax] = sg
            if _dot(lat, e) > math.cos(math.radians(6)):
                lat = tuple(e)
    fwd = _cross(lat, up)                      # left x up = forward
    # target axes: left -> left_sign*X, up -> Z, forward -> -Y   (rows of the rotation map source vectors to target axes)
    tgt_left = (left_sign, 0.0, 0.0)
    R = [[0.0] * 3 for _ in range(3)]
    for src, tgt in ((lat, tgt_left), (up, (0.0, 0.0, 1.0)), (fwd, (0.0, -1.0, 0.0))):
        for i in range(3):
            for j in range(3):
                R[i][j] += tgt[i] * src[j]
    return R


def apply_rot(R, v):
    return [sum(R[i][j] * v[j] for j in range(3)) for i in range(3)]


def weight_map(bones: list[dict], m: Mapping) -> dict:
    """Every source bone -> mannequin bone it contributes its skin weights to (nearest mapped ancestor otherwise)."""
    rig = Rig(bones)
    direct = {}
    for slot, v in m.slots.items():
        direct.setdefault(v["bone"], slot)
    out = {}
    for n in rig.bones:
        cur = n
        tgt = None
        while cur:
            if cur in direct:
                tgt = direct[cur]
                break
            cur = rig.bones[cur].get("parent")
            if cur not in rig.bones:
                cur = None
        out[n] = tgt or "pelvis"
    return out


def load_mannequin(path: str) -> dict:
    return json.load(open(path))
