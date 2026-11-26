"""blender -b -P alpha_probe.py -- job.json     job: {"paths": [...], "out": "alpha.json"}
Writes {path: alpha stats or null} (see af_common.alpha_stats)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import af_common as C  # noqa: E402

job, _ = C.job_from_argv()
res = {p: C.alpha_stats(p) for p in job["paths"] if os.path.exists(p)}
json.dump(res, open(job["out"], "w", encoding="utf-8"), indent=1)
C.log("ALPHA OK: %d texture(s)" % len(res))
