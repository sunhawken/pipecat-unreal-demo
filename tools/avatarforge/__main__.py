"""AvatarForge: convert a rigged humanoid model into the player avatar.

  python -m avatarforge                         open the window
  python -m avatarforge run MODEL [--name N] [--no-ue] [--scale S]   do everything, no window
  python -m avatarforge map MODEL               show the automatic bone mapping only
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def main():
    ap = argparse.ArgumentParser(prog="avatarforge")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("model")
    r.add_argument("--name")
    r.add_argument("--no-ue", action="store_true", help="stop after the converted FBX + previews")
    r.add_argument("--scale", default="auto")
    r.add_argument("--no-preview", action="store_true")
    mp = sub.add_parser("map")
    mp.add_argument("model")
    mp.add_argument("--name")
    sub.add_parser("gui")
    a = ap.parse_args()
    if a.cmd in (None, "gui"):
        from avatarforge.gui import run_gui
        run_gui()
        return 0
    from avatarforge.core.pipeline import Pipeline, StepError
    pl = Pipeline(a.model, getattr(a, "name", None), log=print)
    try:
        if a.cmd == "map":
            pl.inspect()
            m = pl.auto_map()
            for slot, v in sorted(m.slots.items()):
                print(f"{slot:24s} <- {v['bone']:34s} {v['how']:9s} {v['conf']:.2f}")
            return 1 if m.errors else 0
        pl.state["options"].update({"scale": a.scale, "preview": not a.no_preview})
        pl.run_all(import_to_ue=not a.no_ue)
    except StepError as e:
        print("FAILED:", e)
        return 1
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
