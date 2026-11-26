"""The AvatarForge pipeline: inspect -> auto-map -> convert (Blender) -> import (Unreal) -> install.

State lives in <workdir>/state.json so every step can be re-run and the bone table can be edited between steps."""
from __future__ import annotations

import glob
import json
import math
import os
import subprocess
import sys
import time

from . import bonemap as BM
from . import textures as TX

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)                                   # tools\avatarforge
TOOLS = os.path.dirname(PKG)                                  # tools
ROOT = os.path.dirname(TOOLS)                                 # project root (holds pipecat-unreal-demo)
# Two layouts: this machine (project folder inside a work folder) and the GitHub repo (the project IS the root).
PROJECT_DIR = os.path.join(ROOT, "pipecat-unreal-demo")
if not os.path.isdir(PROJECT_DIR) and glob.glob(os.path.join(ROOT, "*.uproject")):
    PROJECT_DIR = ROOT
MANNEQUIN_JSON = os.path.join(PKG, "data", "mannequin_skeleton.json")
SKELETON_ASSET = "/Game/Characters/Mannequins/Meshes/SK_Mannequin"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_blender() -> str | None:
    env = os.environ.get("AVATARFORGE_BLENDER")
    if env and os.path.exists(env):
        return env
    cands = sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender *\blender.exe"), reverse=True)
    return cands[0] if cands else None


def ue_root() -> str | None:
    r = os.environ.get("UE_ROOT")
    if not r and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                r = winreg.QueryValueEx(k, "UE_ROOT")[0]
        except OSError:
            r = None
    return r


class StepError(RuntimeError):
    pass


class Pipeline:
    def __init__(self, source: str, name: str | None = None, workdir: str | None = None, log=print):
        self.log = log
        self.source = os.path.abspath(source)
        self.name = TX.safe_name(name or os.path.splitext(os.path.basename(source))[0])
        self.workdir = workdir or os.path.join(ROOT, "avatars", self.name)
        os.makedirs(self.workdir, exist_ok=True)
        self.state_path = os.path.join(self.workdir, "state.json")
        self.state = {"source": self.source, "name": self.name, "options": {"scale": "auto", "pose_arms": True, "preview": True}}
        if os.path.exists(self.state_path):
            try:
                self.state.update(json.load(open(self.state_path, encoding="utf-8")))
                self.state["source"], self.state["name"] = self.source, self.name
            except Exception:
                pass
        self.mannequin = BM.load_mannequin(MANNEQUIN_JSON)

    # -------------------------------------------------------------------------------------------------- plumbing
    def save(self):
        json.dump(self.state, open(self.state_path, "w", encoding="utf-8"), indent=1)

    def _blender(self, script: str, job: dict, tag: str):
        exe = find_blender()
        if not exe:
            raise StepError("Blender was not found (install it or set AVATARFORGE_BLENDER)")
        jp = os.path.join(self.workdir, f"job_{tag}.json")
        json.dump(job, open(jp, "w", encoding="utf-8"), indent=1)
        cmd = [exe, "-b", "--factory-startup", "-P", os.path.join(PKG, "blender", script), "--", jp]
        self.log(f"$ blender {script}")
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                             creationflags=NO_WINDOW)
        tail = []
        for line in p.stdout:
            line = line.rstrip()
            tail = (tail + [line])[-25:]
            if line.startswith("AF:") or "Error" in line or "Traceback" in line:
                self.log("  " + line)
        if p.wait() != 0:
            raise StepError(f"Blender failed ({script}):\n" + "\n".join(tail[-12:]))

    # -------------------------------------------------------------------------------------------------- steps
    def inspect(self):
        self.log("1/5 Inspect: reading the model")
        out = os.path.join(self.workdir, "inspect")
        self._blender("inspect_model.py", {"source": self.source, "out_dir": out, "armature": self.state.get("armature"),
                                           "parts": self.state.get("parts_override")}, "inspect")
        ins = json.load(open(os.path.join(out, "inspect.json"), encoding="utf-8"))
        self.state["inspect"] = ins
        self.state.pop("mapping", None)
        self.save()
        self.log(f"   {len(ins['bones'])} bones, {len(ins['meshes'])} mesh(es), {sum(m['verts'] for m in ins['meshes'])} vertices")
        for p in ins.get("parts", []):
            if not p["include"]:
                self.log(f"   - leaving out {p['name']}: {p['reason'] or 'excluded by you'}")
        static = [m["name"] for m in ins["meshes"] if m["groups"] == 0]
        if static:
            self.log(f"   ! {len(static)} mesh(es) have no skin weights ({', '.join(static[:4])}): they will be rigged automatically")
        return ins

    def auto_map(self):
        self.log("2/5 Auto-mapping bones")
        ins = self.state["inspect"]
        bones = ins["bones"]
        m = BM.automap(bones, None)   # names, weights and topology; the proportion check needs an upright body
        left_sign = 1.0 if self._q("upperarm_l")[0] > 0 else -1.0
        if not m.errors:
            R = BM.orientation(bones, m, left_sign)
            rot = [{**b, "head": BM.apply_rot(R, b["head"])} for b in bones]
            BM.fix_sides_by_toes(rot, m)
            if m.swapped_sides:
                R = BM.orientation(bones, m, left_sign)
                rot = [{**b, "head": BM.apply_rot(R, b["head"])} for b in bones]
            BM.geometric_fill(rot, m, self.mannequin)
            BM.geometry_warnings(rot, m, self.mannequin)
        else:
            rot = bones
            BM.geometric_fill(bones, m, self.mannequin)
        self.state["mapping"] = m.to_json()
        self.save()
        self.log(f"   mapped {len(m.slots)} slots; {len(m.warnings)} warning(s); {len(m.errors)} error(s)")
        for w in m.warnings:
            self.log("   ! " + w)
        for e in m.errors:
            self.log("   X " + e)
        return m

    def _q(self, name):
        b = next(x for x in self.mannequin["bones"] if x["name"] == name)
        return b["pos"]

    def mapping(self) -> BM.Mapping:
        return BM.Mapping.from_json(self.state["mapping"])

    def set_slot(self, slot: str, bone: str | None):
        m = self.mapping()
        if bone:
            m.slots[slot] = {"bone": bone, "conf": 1.0, "how": "manual"}
        else:
            m.slots.pop(slot, None)
        m.errors = [f"no bone found for '{s}'; pick one in the table" for s in BM.HARD if s not in m.slots]
        self.state["mapping"] = m.to_json()
        self.save()

    def plan(self):
        """Orientation, scale, textures: everything the converter needs, from inspect + mapping."""
        ins = self.state["inspect"]
        m = self.mapping()
        if m.errors:
            raise StepError("The bone mapping is incomplete:\n" + "\n".join(m.errors))
        left_sign = 1.0 if self._q("upperarm_l")[0] > 0 else -1.0
        R = BM.orientation(ins["bones"], m, left_sign)
        lo, hi = ins["bounds"]["min"], ins["bounds"]["max"]
        corners = [BM.apply_rot(R, [x, y, z]) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        height = max(c[2] for c in corners) - min(c[2] for c in corners)
        opt = self.state["options"]
        scale = opt.get("scale", "auto")
        if scale == "auto":
            cands = [1.0, 100.0, 0.1, 0.01, 10.0, 2.54]
            ok = [c for c in cands if 120 <= height * c <= 230]
            scale = min(ok, key=lambda c: abs(math.log(height * c / 175.0))) if ok else 175.0 / max(height, 1e-9)
        scale = float(scale)
        found = TX.discover(os.path.dirname(self.source), [mt["name"] for mt in ins["materials"]])
        bases = sorted({p for f in found.values() for p in [f.get("base")] if p} | {mt["base"] for mt in ins["materials"] if mt.get("base")})
        stats = self._alpha_stats(bases)
        mats = TX.merge(ins["materials"], found, stats)
        for mt in mats:
            ov = self.state.get("material_overrides", {}).get(mt["name"], {})
            mt.update(ov)
        self.state["plan"] = {"rotation": R, "scale": scale, "height_units": height, "materials": mats}
        self.save()
        self.log(f"   height {height:.3f} source units -> x{scale:g} = {height * scale:.0f} cm")
        for mt in mats:
            self.log(f"   material {mt['name']} [{mt.get('class')}]: base={'yes' if mt.get('base') else 'NO'} "
                     f"normal={'yes' if mt.get('normal') else 'no'} alpha={mt.get('alpha_mode')} ({mt.get('alpha_why')})")
        return self.state["plan"]

    def _alpha_stats(self, paths):
        """Alpha analysis per texture (cached by path + modification time)."""
        cache = self.state.setdefault("alpha_cache", {})
        todo = [p for p in paths if p and os.path.exists(p) and cache.get(p, {}).get("mtime") != os.path.getmtime(p)]
        if todo:
            out = os.path.join(self.workdir, "alpha.json")
            self._blender("alpha_probe.py", {"paths": todo, "out": out}, "alpha")
            res = json.load(open(out, encoding="utf-8"))
            for p in todo:
                cache[p] = {"mtime": os.path.getmtime(p), "stats": res.get(p)}
        return {p: cache[p]["stats"] for p in paths if p in cache}

    def convert(self):
        self.log("3/5 Converting (re-skin onto the mannequin skeleton)")
        plan = self.plan()
        ins = self.state["inspect"]
        m = self.mapping()
        out = os.path.join(self.workdir, "convert")
        os.makedirs(out, exist_ok=True)
        fbx = os.path.join(out, f"{self.name}_OnMannequin.fbx")
        job = {"source": self.source, "armature": self.state.get("armature"), "out_fbx": fbx, "out_dir": out,
               "mannequin": MANNEQUIN_JSON, "rotation": plan["rotation"], "scale": plan["scale"],
               "parts": self.state.get("parts_override"), "mapping": {k: v["bone"] for k, v in m.slots.items()}, "weight_map": BM.weight_map(ins["bones"], m),
               "materials": plan["materials"], "preview": self.state["options"].get("preview", True),
               "preview_dir": os.path.join(out, "preview"), "pose_arms": self.state["options"].get("pose_arms", True)}
        self._blender("convert_model.py", job, "convert")
        rep = json.load(open(os.path.join(out, "convert.json"), encoding="utf-8"))
        self.state["convert"] = {"fbx": fbx, "report": rep, "preview_dir": job["preview_dir"]}
        self.save()
        st = rep["stats"]
        self.log(f"   height {st['height_cm']:.0f} cm, {st['vertices']} vertices, frame deviation {st['worst_frame_deviation']:.1e}, "
                 f"weights: max {st['max_influences']}/vertex, {st['vertices_without_weight']} unweighted")
        for w in rep["warnings"]:
            self.log("   ! " + w)
        return rep

    def previews(self):
        d = self.state.get("convert", {}).get("preview_dir")
        names = ["rest_front", "rest_back", "rest_side", "posed_front"]
        return [os.path.join(d, n + ".png") for n in names if d and os.path.exists(os.path.join(d, n + ".png"))]

    def ue_import(self, dest_root: str = "/Game/Avatars"):
        self.log("4/5 Importing into Unreal (the editor must be closed)")
        ue = ue_root()
        ps1 = os.path.join(TOOLS, "Run-UEPython.ps1")
        if not ue or not os.path.exists(os.path.join(ue, "Engine", "Binaries", "Win64", "UnrealEditor-Cmd.exe")):
            raise StepError("Unreal Engine not found (UE_ROOT)")
        if not os.path.exists(ps1):
            raise StepError("Run-UEPython.ps1 is missing next to the avatarforge folder")
        if subprocess.run(["tasklist", "/FI", "IMAGENAME eq UnrealEditor.exe"], capture_output=True, text=True,
                          creationflags=NO_WINDOW).stdout.count("UnrealEditor.exe"):
            raise StepError("Unreal is running (editor or game). Close it, then import again.")
        conv = self.state["convert"]
        result = os.path.join(self.workdir, "ue_result.json")
        if os.path.exists(result):
            os.remove(result)
        job = {"fbx": conv["fbx"], "dest": f"{dest_root}/{self.name}", "name": f"SK_{self.name}", "skeleton": SKELETON_ASSET,
               "mannequin": MANNEQUIN_JSON, "materials": self.state["plan"]["materials"], "result": result}
        jp = os.path.join(self.workdir, "job_ue.json")
        json.dump(job, open(jp, "w", encoding="utf-8"), indent=1)
        env = dict(os.environ, AVATARFORGE_JOB=jp)
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Script",
               os.path.join(PKG, "ue", "import_avatar.py"), "-LogName", f"avatarforge_{self.name}.log"]
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        for line in (p.stdout or "").splitlines()[-12:]:
            self.log("   " + line)
        if not os.path.exists(result):
            raise StepError("Unreal produced no result file; see logs\\avatarforge_%s.log" % self.name)
        res = json.load(open(result, encoding="utf-8"))
        self.state["ue"] = res
        self.save()
        if res.get("error"):
            raise StepError("Unreal import failed:\n" + res["error"])
        self.log(f"   {res.get('bones')} bones, worst frame {res.get('worst_frame_deg', 0):.4f} deg, ok={res.get('ok')}")
        return res

    def install(self):
        """Make the imported mesh the player's body (read by UPipecatPlayerAvatar at play start)."""
        asset = self.state.get("ue", {}).get("asset")
        if not asset:
            raise StepError("Import into Unreal first")
        cfg = os.path.join(PROJECT_DIR, "Config", "PipecatAvatar.txt")
        open(cfg, "w", encoding="utf-8").write(asset + "\n")
        self.log(f"5/5 Installed: the player's avatar is now {asset}")
        return asset

    def run_all(self, import_to_ue=True):
        self.inspect()
        m = self.auto_map()
        if m.errors:
            raise StepError("Auto-mapping needs your help:\n" + "\n".join(m.errors))
        self.convert()
        if import_to_ue:
            self.ue_import()
            self.install()
        return self.state


def uninstall():
    cfg = os.path.join(PROJECT_DIR, "Config", "PipecatAvatar.txt")
    if os.path.exists(cfg):
        os.remove(cfg)
