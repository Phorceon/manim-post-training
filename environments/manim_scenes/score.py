# /// script
# requires-python = ">=3.10"
# dependencies = ["manim"]
# ///
"""Standalone manim scene scorer.

Loads a model-written manim file, renders the first Scene subclass at low
quality in-process, then inspects the rendered artifact and scene graph.
Prints one JSON line of facts to stdout; mapping facts to a reward is the
caller's job.

Usage: uv run score.py path/to/scene.py
"""

import ast
import importlib.util
import json
import subprocess
import sys
from itertools import combinations
from pathlib import Path

OVERLAP_MIN = 0.15  # intersection area as fraction of the smaller box


def find_scenes(code: str) -> list[str]:
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


def box(m) -> tuple[float, float, float, float] | None:
    pts = m.get_all_points()
    if pts is None or len(pts) == 0:
        return None
    xmin, xmax = float(pts[:, 0].min()), float(pts[:, 0].max())
    ymin, ymax = float(pts[:, 1].min()), float(pts[:, 1].max())
    if xmax - xmin < 1e-3 or ymax - ymin < 1e-3:
        return None
    return xmin, ymin, xmax, ymax


def overlap(a, b) -> float:
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    inter = ix * iy
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / smaller


def descendants(m):
    yield m
    for s in getattr(m, "submobjects", []):
        yield from descendants(s)


def video_info(media_dir: str) -> tuple[bool, str | None, float | None]:
    vids = [v for v in Path(media_dir).rglob("*.mp4") if v.stat().st_size > 0]
    if not vids:
        return False, None, None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(vids[0])],
            capture_output=True, text=True, timeout=15,
        )
        return True, str(vids[0]), float(r.stdout.strip())
    except Exception:
        return True, str(vids[0]), None


def main(path: str) -> None:
    out = {
        "renders": False, "video_exists": False, "video_path": None,
        "duration_s": None,
        "scene": None, "n_plays": 0, "n_mobjects": 0,
        "has_text": False, "has_shapes": False, "code_lines": 0,
        "out_of_frame": [], "overlaps": [], "error": None,
    }
    print_out = lambda: print(json.dumps(out))

    code = Path(path).read_text()
    out["code_lines"] = sum(
        1 for l in code.splitlines() if l.strip() and not l.strip().startswith("#")
    )

    try:
        names = find_scenes(code)
    except SyntaxError as e:
        out["error"] = f"syntax_error: {e}"
        return print_out()
    if not names:
        out["error"] = "no_scene_subclass"
        return print_out()
    out["scene"] = names[0]

    try:
        spec = importlib.util.spec_from_file_location("candidate", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        from manim import Wait, config
        import logging
        import tempfile

        logging.getLogger("manim").setLevel(logging.ERROR)
        config.quality = "low_quality"
        config.media_dir = tempfile.mkdtemp(prefix="manim-score-")

        scene = getattr(mod, names[0])()
        orig_play = scene.play

        def counting_play(*a, **kw):
            if not all(isinstance(x, Wait) for x in a):
                out["n_plays"] += 1
            return orig_play(*a, **kw)

        scene.play = counting_play
        scene.render()
    except Exception as e:
        out["error"] = f"render_crash: {type(e).__name__}: {e}"
        return print_out()

    out["renders"] = True
    out["video_exists"], out["video_path"], out["duration_s"] = video_info(
        config.media_dir
    )

    try:
        from manim import MarkupText, MathTex, Tex, Text

        xb, yb = config.frame_width / 2, config.frame_height / 2
        boxes = []
        for m in scene.mobjects:
            b = box(m)
            if b is None:
                continue
            boxes.append((type(m).__name__, b))
            if b[0] < -xb or b[2] > xb or b[1] < -yb or b[3] > yb:
                out["out_of_frame"].append(type(m).__name__)
        out["n_mobjects"] = len(boxes)

        for (na, a), (nb, b) in combinations(boxes, 2):
            if overlap(a, b) > OVERLAP_MIN:
                out["overlaps"].append([na, nb])

        text_types = (Text, MarkupText, Tex, MathTex)
        leaves = [
            d
            for m in scene.mobjects
            for d in descendants(m)
            if d.get_all_points() is not None and len(d.get_all_points()) > 0
        ]
        out["has_text"] = any(isinstance(d, text_types) for d in leaves)
        out["has_shapes"] = any(not isinstance(d, text_types) for d in leaves)
    except Exception as e:
        out["error"] = f"inspection_crash: {type(e).__name__}: {e}"

    print_out()


if __name__ == "__main__":
    main(sys.argv[1])
