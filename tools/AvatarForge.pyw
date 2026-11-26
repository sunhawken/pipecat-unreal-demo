import os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from avatarforge.gui import run_gui
run_gui(sys.argv[1] if len(sys.argv) > 1 else None)
