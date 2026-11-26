"""AvatarForge window: pick a model, check the automatic bone map and materials, convert, preview, import, set as avatar."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import bonemap as BM
from .core.pipeline import PROJECT_DIR, ROOT, Pipeline, StepError, find_blender, ue_root

BG, PANEL, FG, DIM, ACC, OK, WARN, BAD, MANUAL = "#14161c", "#1d2029", "#e6e9f2", "#8b93a7", "#4c8dff", "#46c28a", "#e0a43a", "#e5594f", "#6ea8ff"
CANON = (["pelvis"] + BM.SPINE + ["neck_01", "neck_02", "head"] +
         [f"{b}_{s}" for s in "lr" for b in ("clavicle", "upperarm", "lowerarm", "hand")] +
         [f"{f}_0{i}_{s}" for s in "lr" for f in BM.FINGER_NAMES for i in (1, 2, 3)] +
         [f"{b}_{s}" for s in "lr" for b in ("thigh", "calf", "foot", "ball")] + BM.JIGGLE)


class App(tk.Tk):
    def __init__(self, model: str | None = None):
        super().__init__()
        self.title("AvatarForge  -  convert any humanoid to the player avatar")
        self.geometry("1240x820")
        self.configure(bg=BG)
        self.pl: Pipeline | None = None
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.thumbs = []
        self._style()
        self._build()
        self.after(100, self._pump)
        if model:
            self.open_model(model)
        else:
            self._refresh()

    # ------------------------------------------------------------------------------------------------ look
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL)
        s.configure("TFrame", background=BG)
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Dim.TLabel", foreground=DIM)
        s.configure("Title.TLabel", font=("Segoe UI Semibold", 15))
        s.configure("TButton", background=PANEL, foreground=FG, padding=(12, 7), borderwidth=0)
        s.map("TButton", background=[("active", "#2a2f3d"), ("disabled", "#181a21")], foreground=[("disabled", "#555b6b")])
        s.configure("Accent.TButton", background=ACC, foreground="white", font=("Segoe UI Semibold", 10))
        s.map("Accent.TButton", background=[("active", "#6aa0ff"), ("disabled", "#2a3550")])
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=24, borderwidth=0)
        s.configure("Treeview.Heading", background="#262a36", foreground=DIM, padding=5, relief="flat")
        s.map("Treeview", background=[("selected", "#2c3a5e")])
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=BG, foreground=DIM, padding=(14, 6))
        s.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", FG)])
        s.configure("TCheckbutton", background=BG, foreground=FG)
        s.configure("TEntry", insertcolor=FG)
        s.configure("TCombobox", arrowcolor=FG)

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=16, pady=(14, 6))
        ttk.Label(top, text="AvatarForge", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="  any rigged humanoid  ->  the default Unreal avatar skeleton", style="Dim.TLabel").pack(side="left")
        ttk.Button(top, text="Open model...", command=self.pick_model).pack(side="right")
        self.name_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.name_var, width=22).pack(side="right", padx=8)
        ttk.Label(top, text="Avatar name", style="Dim.TLabel").pack(side="right")

        self.path_lbl = ttk.Label(self, text="No model open. Drop in an .fbx, .glb, .gltf or .blend with a skeleton.", style="Dim.TLabel")
        self.path_lbl.pack(fill="x", padx=16)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=16, pady=10)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=False)
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        nb = ttk.Notebook(left)
        nb.pack(fill="both", expand=True)
        # bones
        t1 = ttk.Frame(nb, style="Panel.TFrame")
        nb.add(t1, text="Bones")
        self.bones = ttk.Treeview(t1, columns=("slot", "src", "how", "conf"), show="headings", height=22)
        for c, w, t in (("slot", 150, "Avatar bone"), ("src", 210, "Your model's bone"), ("how", 70, "How"), ("conf", 50, "Conf")):
            self.bones.heading(c, text=t)
            self.bones.column(c, width=w, anchor="w")
        self.bones.pack(fill="both", expand=True, padx=2, pady=2)
        for tag, col in (("ok", OK), ("low", WARN), ("missing", BAD), ("manual", MANUAL), ("opt", DIM)):
            self.bones.tag_configure(tag, foreground=col)
        self.bones.bind("<Double-1>", self.edit_bone)
        row = ttk.Frame(t1, style="Panel.TFrame")
        row.pack(fill="x", padx=4, pady=4)
        ttk.Button(row, text="Re-run auto map", command=lambda: self.run_steps(["map"])).pack(side="left")
        ttk.Button(row, text="Clear selected", command=self.clear_bone).pack(side="left", padx=6)
        ttk.Label(row, text="double-click a row to choose its bone", style="Dim.TLabel", background=PANEL).pack(side="right")
        # materials
        t2 = ttk.Frame(nb, style="Panel.TFrame")
        nb.add(t2, text="Materials & hair")
        self.mats = ttk.Treeview(t2, columns=("name", "cls", "tex", "alpha", "two"), show="headings", height=10)
        for c, w, t in (("name", 150, "Material"), ("cls", 55, "Type"), ("tex", 90, "Textures"), ("alpha", 80, "Alpha"), ("two", 60, "2-sided")):
            self.mats.heading(c, text=t)
            self.mats.column(c, width=w, anchor="w")
        self.mats.pack(fill="x", padx=2, pady=2)
        self.mats.bind("<<TreeviewSelect>>", self._mat_selected)
        mrow = ttk.Frame(t2, style="Panel.TFrame")
        mrow.pack(fill="x", padx=4, pady=4)
        ttk.Button(mrow, text="Alpha: opaque", command=lambda: self.set_alpha("opaque")).pack(side="left")
        ttk.Button(mrow, text="Alpha: cut-out", command=lambda: self.set_alpha("masked")).pack(side="left", padx=6)
        ttk.Button(mrow, text="Toggle 2-sided", command=self.toggle_two).pack(side="left")
        self.mat_note = tk.Text(t2, height=8, bg=PANEL, fg=DIM, bd=0, wrap="word", font=("Segoe UI", 9))
        self.mat_note.pack(fill="both", expand=True, padx=6, pady=6)
        # parts
        tp = ttk.Frame(nb, style="Panel.TFrame")
        nb.add(tp, text="Parts")
        self.parts = ttk.Treeview(tp, columns=("name", "verts", "rig", "use", "why"), show="headings", height=14)
        for c, w, t in (("name", 150, "Mesh"), ("verts", 55, "Verts"), ("rig", 70, "Weights"), ("use", 45, "Use"), ("why", 190, "Why")):
            self.parts.heading(c, text=t)
            self.parts.column(c, width=w, anchor="w")
        self.parts.pack(fill="both", expand=True, padx=2, pady=2)
        self.parts.bind("<Double-1>", self.toggle_part)
        ttk.Label(tp, text="Duplicates, strays and floor decals are left out automatically. Double-click to override, then press "
                           "'1-2 Inspect + map'. Meshes with no weights are rigged automatically.", style="Dim.TLabel",
                  background=PANEL, wraplength=480, justify="left").pack(fill="x", padx=6, pady=6)
        # options
        t3 = ttk.Frame(nb, style="Panel.TFrame")
        nb.add(t3, text="Options")
        self.scale_var = tk.StringVar(value="auto")
        self.pose_var = tk.BooleanVar(value=True)
        self.prev_var = tk.BooleanVar(value=True)
        o = ttk.Frame(t3, style="Panel.TFrame")
        o.pack(fill="x", padx=12, pady=12)
        ttk.Label(o, text="Scale to centimetres", background=PANEL).grid(row=0, column=0, sticky="w")
        ttk.Entry(o, textvariable=self.scale_var, width=10).grid(row=0, column=1, padx=8)
        ttk.Label(o, text="auto picks 1 / 100 / 0.01 ... so the height lands near 175 cm", style="Dim.TLabel", background=PANEL).grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(o, text="Rotate the arms to the mannequin's A-pose (better stock animations; OFF = every vertex exactly as authored, 1:1)", variable=self.pose_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Checkbutton(o, text="Render before/after previews", variable=self.prev_var).grid(row=2, column=0, columnspan=3, sticky="w", pady=4)
        self.info = ttk.Label(o, text="", style="Dim.TLabel", background=PANEL, justify="left")
        self.info.grid(row=3, column=0, columnspan=3, sticky="w", pady=(14, 0))

        # right: previews + log
        self.prev_row = ttk.Frame(right, style="Panel.TFrame")
        self.prev_row.pack(fill="x")
        self.prev_lbls = []
        for i in range(4):
            l = tk.Label(self.prev_row, bg=PANEL, fg=DIM, text="preview", width=18, height=13)
            l.grid(row=0, column=i, padx=2, pady=2)
            self.prev_lbls.append(l)
        self.log_box = tk.Text(right, bg="#0e1015", fg="#c9d1e6", bd=0, wrap="word", font=("Consolas", 9), height=12)
        self.log_box.pack(fill="both", expand=True, pady=(10, 0))
        self.log_box.tag_configure("bad", foreground=BAD)
        self.log_box.tag_configure("warn", foreground=WARN)
        self.log_box.tag_configure("step", foreground=ACC)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=16, pady=(0, 14))
        self.status = ttk.Label(bar, text="", style="Dim.TLabel")
        self.status.pack(side="left")
        nb.select(0)
        self.btns = {}
        for key, text, style in (("launch", "Launch game (VR)", "TButton"), ("folder", "Open folder", "TButton"),
                                 ("install", "5  Set as avatar", "TButton"), ("ue", "4  Import to Unreal", "TButton"),
                                 ("convert", "3  Convert", "TButton"), ("map", "1-2  Inspect + map", "TButton"),
                                 ("all", "Do everything", "Accent.TButton")):
            b = ttk.Button(bar, text=text, style=style, command=lambda k=key: self.on_button(k))
            b.pack(side="right", padx=4)
            self.btns[key] = b

    # ------------------------------------------------------------------------------------------------ actions
    def pick_model(self):
        p = filedialog.askopenfilename(title="Choose a rigged humanoid model", filetypes=[("Models", "*.fbx *.glb *.gltf *.blend *.dae"), ("All", "*.*")])
        if p:
            self.open_model(p)

    def open_model(self, path: str):
        self.pl = Pipeline(path, self.name_var.get() or None, log=self.q_log)
        self.name_var.set(self.pl.name)
        self.path_lbl.config(text=f"{path}   ->   work folder {self.pl.workdir}")
        o = self.pl.state["options"]
        self.scale_var.set(str(o.get("scale", "auto")))
        self.pose_var.set(o.get("pose_arms", True))
        self.prev_var.set(o.get("preview", True))
        self.log(f"Opened {path}", "step")
        if "mapping" in self.pl.state:
            self.log("(loaded the previous bone map and results from the work folder)")
        self._refresh()

    def on_button(self, key):
        if key == "folder" and self.pl:
            os.startfile(self.pl.workdir)
            return
        if key == "launch":
            self.launch_game()
            return
        if not self.pl:
            messagebox.showinfo("AvatarForge", "Open a model first.")
            return
        self._sync_options()
        steps = {"map": ["inspect", "map"], "convert": ["convert"], "ue": ["ue"], "install": ["install"],
                 "all": ["inspect", "map", "convert", "ue", "install"]}[key]
        self.run_steps(steps)

    def _sync_options(self):
        if not self.pl:
            return
        new_name = self.name_var.get().strip()
        if new_name and new_name != self.pl.name:
            self.open_model(self.pl.source)
        o = self.pl.state["options"]
        o["scale"] = self.scale_var.get().strip() or "auto"
        o["pose_arms"] = self.pose_var.get()
        o["preview"] = self.prev_var.get()
        self.pl.save()

    def run_steps(self, steps):
        if self.busy or not self.pl:
            return
        self._sync_options()
        self.busy = True
        self._refresh()

        def work():
            pl = self.pl
            try:
                for s in steps:
                    if s == "inspect":
                        pl.inspect()
                    elif s == "map":
                        m = pl.auto_map()
                        if m.errors and steps != ["map"] and "convert" in steps:
                            raise StepError("Some required bones need picking by hand (see the red rows). Fix them, then press Convert.")
                    elif s == "convert":
                        pl.convert()
                    elif s == "ue":
                        pl.ue_import()
                    elif s == "install":
                        pl.install()
                self.q.put(("done", None))
            except StepError as e:
                self.q.put(("fail", str(e)))
            except Exception as e:  # noqa: BLE001
                import traceback
                self.q.put(("fail", f"{e}\n{traceback.format_exc()}"))
        threading.Thread(target=work, daemon=True).start()

    def launch_game(self):
        ps1 = os.path.join(ROOT, "tools", "Play-PipecatWorld.ps1")
        vr = messagebox.askyesno("Launch", "Start the game in VR mode?\n(No = normal window)")
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1] + (["-VR"] if vr else [])
        subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.log("Launching the game...", "step")

    # ------------------------------------------------------------------------------------------------ tables
    def edit_bone(self, _e=None):
        sel = self.bones.selection()
        if not sel or not self.pl or "inspect" not in self.pl.state:
            return
        slot = sel[0]
        names = sorted((b["name"] for b in self.pl.state["inspect"]["bones"]), key=lambda n: (not next(b for b in self.pl.state["inspect"]["bones"] if b["name"] == n)["weighted"], n))
        win = tk.Toplevel(self)
        win.title(f"Bone for {slot}")
        win.configure(bg=BG)
        win.geometry("380x520")
        v = tk.StringVar()
        e = ttk.Entry(win, textvariable=v)
        e.pack(fill="x", padx=10, pady=10)
        e.focus_set()
        lb = tk.Listbox(win, bg=PANEL, fg=FG, bd=0, selectbackground="#2c3a5e", activestyle="none")
        lb.pack(fill="both", expand=True, padx=10)

        def fill(*_):
            lb.delete(0, "end")
            for n in names:
                if v.get().lower() in n.lower():
                    lb.insert("end", n)
        v.trace_add("write", fill)
        fill()

        def choose(_e=None):
            if lb.curselection():
                self.pl.set_slot(slot, lb.get(lb.curselection()[0]))
                win.destroy()
                self._refresh()
        lb.bind("<Double-1>", choose)
        ttk.Button(win, text="Use this bone", command=choose).pack(pady=10)

    def toggle_part(self, _e=None):
        sel = self.parts.selection()
        if not sel or not self.pl:
            return
        cur = next((p for p in self.pl.state.get("inspect", {}).get("parts", []) if p["name"] == sel[0]), None)
        if not cur:
            return
        ov = self.pl.state.setdefault("parts_override", {})
        ov[sel[0]] = not cur["include"]
        self.pl.save()
        self.log(f"{sel[0]}: will be {'included' if ov[sel[0]] else 'left out'} next time (press '1-2 Inspect + map')", "warn")
        cur["include"] = ov[sel[0]]
        self._refresh()

    def clear_bone(self):
        for slot in self.bones.selection():
            if self.pl:
                self.pl.set_slot(slot, None)
        self._refresh()

    def _mat_selected(self, _e=None):
        sel = self.mats.selection()
        self.mat_note.delete("1.0", "end")
        if not sel or not self.pl or "plan" not in self.pl.state:
            return
        mt = next((m for m in self.pl.state["plan"]["materials"] if m["name"] == sel[0]), None)
        if mt:
            txt = [f"{mt['name']}  ({mt.get('class')})", f"base:   {mt.get('base') or '-'}", f"normal: {mt.get('normal') or '-'}",
                   f"alpha:  {mt.get('alpha_mode')}  -  {mt.get('alpha_why', '')}",
                   "", "Cut-out = the texture's alpha is a mask (hair cards, lashes, leaves). Opaque = the alpha is data (e.g. specular) "
                   "or absent and must not make the mesh transparent. Hair is always drawn two-sided."]
            self.mat_note.insert("end", "\n".join(txt))

    def _override(self, **kw):
        sel = self.mats.selection()
        if not sel or not self.pl:
            return
        ov = self.pl.state.setdefault("material_overrides", {}).setdefault(sel[0], {})
        ov.update(kw)
        self.pl.save()
        try:
            self.pl.plan()
        except StepError as e:
            self.log(str(e), "bad")
        self._refresh()
        self.mats.selection_set(sel[0])

    def set_alpha(self, mode):
        self._override(alpha_mode=mode, alpha_why="set by you")

    def toggle_two(self):
        sel = self.mats.selection()
        if sel and self.pl:
            cur = next((m for m in self.pl.state.get("plan", {}).get("materials", []) if m["name"] == sel[0]), {}).get("two_sided", False)
            self._override(two_sided=not cur)

    # ------------------------------------------------------------------------------------------------ plumbing
    def q_log(self, msg):
        self.q.put(("log", str(msg)))

    def log(self, msg, tag=None):
        self.log_box.insert("end", msg + "\n", tag or ())
        self.log_box.see("end")

    def _pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    tag = "bad" if val.strip().startswith(("X", "FAILED")) else "warn" if val.strip().startswith("!") else \
                        "step" if val[:3] in ("1/5", "2/5", "3/5", "4/5", "5/5") else None
                    self.log(val, tag)
                elif kind == "done":
                    self.busy = False
                    self.log("Finished.", "step")
                    self._refresh()
                elif kind == "fail":
                    self.busy = False
                    self.log(val, "bad")
                    self._refresh()
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _refresh(self):
        have = self.pl is not None
        st = self.pl.state if have else {}
        for k, b in self.btns.items():
            if k in ("launch",):
                b.state(["!disabled"])
            elif k == "folder":
                b.state(["!disabled"] if have else ["disabled"])
            elif self.busy or not have:
                b.state(["disabled"])
            elif k == "convert":
                b.state(["!disabled"] if "mapping" in st else ["disabled"])
            elif k == "ue":
                b.state(["!disabled"] if "convert" in st else ["disabled"])
            elif k == "install":
                b.state(["!disabled"] if st.get("ue", {}).get("asset") else ["disabled"])
            else:
                b.state(["!disabled"])
        self.status.config(text="working..." if self.busy else ("ready" if have else ""))
        # bones
        self.bones.delete(*self.bones.get_children())
        if "mapping" in st:
            m = BM.Mapping.from_json(st["mapping"])
            for slot in CANON:
                v = m.slots.get(slot)
                if v:
                    tag = "manual" if v["how"] == "manual" else "low" if v["conf"] < 0.6 else "ok"
                    self.bones.insert("", "end", iid=slot, values=(slot, v["bone"], v["how"], f"{v['conf']:.2f}"), tags=(tag,))
                else:
                    req = slot in BM.REQUIRED
                    self.bones.insert("", "end", iid=slot, values=(slot, "REQUIRED - pick one" if req else "(none)", "", ""),
                                      tags=("missing" if req else "opt",))
            extras = [s for s in m.slots if s not in CANON]
            for slot in sorted(extras):
                v = m.slots[slot]
                self.bones.insert("", "end", iid=slot, values=(slot, v["bone"], v["how"], f"{v['conf']:.2f}"), tags=("ok",))
        # parts
        self.parts.delete(*self.parts.get_children())
        for p in st.get("inspect", {}).get("parts", []):
            self.parts.insert("", "end", iid=p["name"], values=(p["name"], p["verts"], "skinned" if p["skinned"] else "NONE (auto-rig)",
                                                                  "yes" if p["include"] else "no", p.get("reason", "")))
        # materials
        self.mats.delete(*self.mats.get_children())
        for mt in st.get("plan", {}).get("materials", []):
            tex = "".join(k[0].upper() if mt.get(k) else "-" for k in ("base", "normal", "rough", "metal"))
            self.mats.insert("", "end", iid=mt["name"], values=(mt["name"], mt.get("class", ""), tex + "  (B N R M)",
                                                                  "cut-out" if mt.get("alpha_mode") == "masked" else "opaque",
                                                                  "yes" if mt.get("two_sided") else "no"))
        # info + previews
        if "plan" in st:
            p = st["plan"]
            self.info.config(text=f"Source height {p['height_units']:.3f} units, scale x{p['scale']:g}  ->  {p['height_units'] * p['scale']:.0f} cm")
        if "convert" in st:
            r = st["convert"]["report"]["stats"]
            self.info.config(text=self.info.cget("text") + f"\nConverted: {r['vertices']} vertices, bone-frame deviation {r['worst_frame_deviation']:.1e}, "
                                                       f"{r['max_influences']} weights/vertex max")
            sc = r.get("shape_check")
            if sc:
                self.info.config(text=self.info.cget("text") + f"\nShape check: {sc['moved_over_0.5mm']} of {sc['vertices']} vertices differ from "
                                                           f"the original (max {sc['max_displacement_cm']:.1f} cm)")
            self._show_previews()
        if "ue" in st and st["ue"].get("ok") is not None:
            u = st["ue"]
            self.info.config(text=self.info.cget("text") + f"\nUnreal: {u.get('asset')}  frames {u.get('worst_frame_deg', 0):.4f} deg  "
                                                       f"{'OK' if u.get('ok') else 'CHECK THE LOG'}")

    def _show_previews(self):
        self.thumbs = []
        for lbl, path in zip(self.prev_lbls, self.pl.previews() if self.pl else []):
            try:
                img = tk.PhotoImage(file=path).subsample(4, 4)
            except Exception:
                continue
            self.thumbs.append(img)
            lbl.config(image=img, text="", width=img.width(), height=img.height())
            lbl.bind("<Button-1>", lambda _e, p=path: self._big(p))

    def _big(self, path):
        w = tk.Toplevel(self)
        w.title(os.path.basename(path))
        img = tk.PhotoImage(file=path)
        l = tk.Label(w, image=img, bg=BG)
        l.image = img
        l.pack()


def run_gui(model: str | None = None):
    App(model).mainloop()
