# /// script
# requires-python = ">=3.10"
# dependencies = ["manim"]
# ///
"""Standalone manim scene scorer.

Loads a model-written manim file, renders the first Scene subclass at low
quality in-process, then inspects the final frame's top-level mobjects for
out-of-frame placement and pairwise bounding-box overlap. Prints one JSON
line of facts to stdout; mapping facts to a reward is the caller's job.

Usage: uv run score.py path/to/scene.py
"""

import ast
import importlib.util
import json
import sys
from itertools import combinations
from pathlib import Path

OVERLAP_MIN = 0.15  # intersection area as fraction of the smaller box


def scene_classes(code: str) -> list[str]:
    tree = ast.parse(code)
    out = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
            if name.endswith("Scene"):
                out.append(node.name)
                break
    return out


def bbox(m) -> tuple[float, float, float, float] | None:
    pts = m.get_all_points()
    if pts is None or len(pts) == 0:
        return None
    xmin, xmax = float(pts[:, 0].min()), float(pts[:, 0].max())
    ymin, ymax = float(pts[:, 1].min()), float(pts[:, 1].max())
    if xmax - xmin < 1e-3 or ymax - ymin < 1e-3:
        return None
    return xmin, ymin, xmax, ymax


def overlap_ratio(a, b) -> float:
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    inter = ix * iy
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / smaller


def main(path: str) -> None:
    result = {
        "renders": False,
        "scene": None,
        "n_mobjects": 0,
        "out_of_frame": [],
        "overlaps": [],
        "error": None,
    }

    code = Path(path).read_text()
    try:
        names = scene_classes(code)
    except SyntaxError as e:
        result["error"] = f"syntax_error: {e}"
        print(json.dumps(result))
        return
    if not names:
        result["error"] = "no_scene_subclass"
        print(json.dumps(result))
        return
    result["scene"] = names[0]

    try:
        spec = importlib.util.spec_from_file_location("candidate", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        from manim import config
        import logging

        logging.getLogger("manim").setLevel(logging.ERROR)
        config.quality = "low_quality"
        scene = getattr(mod, names[0])()
        scene.render()
    except Exception as e:
        result["error"] = f"render_crash: {type(e).__name__}: {e}"
        print(json.dumps(result))
        return

    result["renders"] = True

    try:
        xb, yb = config.frame_width / 2, config.frame_height / 2
        boxes = []
        for m in scene.mobjects:
            b = bbox(m)
            if b is None:
                continue
            boxes.append((type(m).__name__, b))
            if b[0] < -xb or b[2] > xb or b[1] < -yb or b[3] > yb:
                result["out_of_frame"].append(type(m).__name__)
        result["n_mobjects"] = len(boxes)

        for (na, a), (nb, b) in combinations(boxes, 2):
            if overlap_ratio(a, b) > OVERLAP_MIN:
                result["overlaps"].append([na, nb])
    except Exception as e:
        result["error"] = f"inspection_crash: {type(e).__name__}: {e}"

    print(json.dumps(result))


if __name__ == "__main__":
    main(sys.argv[1])
