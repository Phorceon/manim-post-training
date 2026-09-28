# /// script
# requires-python = ">=3.10"
# dependencies = ["manim", "static-ffmpeg"]
# ///
"""Standalone manim scene scorer.

Loads a model-written manim file, renders the first Scene subclass at low
quality in-process, then inspects the final frame's top-level mobjects for
out-of-frame placement and pairwise bounding-box overlap. Prints one JSON
line of facts to stdout; mapping facts to a reward is the caller's job.

Usage: uv run score.py path/to/scene.py

JSON facts (consumers read the last line starting with '{'):
  renders       scene.render() returned without raising
  scene         rendered Scene subclass name
  n_mobjects    top-level mobjects with a non-degenerate bbox
  out_of_frame  top-level mobjects whose bbox leaves the frame
  overlaps      [a, b] pairs whose AABBs overlap past OVERLAP_MIN
  error         'syntax_error' | 'no_scene_subclass' | 'render_crash' |
                'inspection_crash' | null
  video_exists  a non-empty mp4 exists under ./media (anti-monkeypatch anchor)
  video_path    path of that mp4, or null
  n_plays       scene.play() calls, incl. any import-time render
  duration_s    ffprobe duration of the produced video, or null
  has_text      any Text/Tex descendant anywhere in the tree
  has_shapes    any non-text VMobject descendant
  code_lines    non-blank source lines (fact only — never weighted)

Render wall time is bounded by MANIM_SCORE_TIMEOUT (default 300s SIGALRM),
below the env's TaskTimeout(scoring=420).
"""

import ast
import importlib.util
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
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


def _descendants(mobject):
    seen, stack = set(), [mobject]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        yield node
        stack.extend(node.submobjects)


def _find_video(media_dir: Path, min_mtime: float):
    """Newest non-empty mp4 produced at/after ``min_mtime`` — a stale artifact
    left by a previous run in a shared cwd must not count as this render's."""
    newest = None
    if media_dir.is_dir():
        for p in media_dir.rglob("*.mp4"):
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_size > 0 and st.st_mtime >= min_mtime and (
                newest is None or st.st_mtime > newest[1]
            ):
                newest = (p, st.st_mtime)
    return newest[0] if newest else None


def _ffprobe() -> str | None:
    if path := shutil.which("ffprobe"):
        return path
    try:
        from static_ffmpeg import run

        _ffmpeg, ffprobe = run.get_or_fetch_platform_executables_else_raise()
        return ffprobe
    except Exception:
        return None


def _duration_s(video: Path) -> float | None:
    ffprobe = _ffprobe()
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, timeout=30,
        )
        return round(float(out.stdout.strip()), 3)
    except Exception:
        return None


def _timeout(signum, frame):
    raise TimeoutError(
        f"scorer exceeded {os.environ.get('MANIM_SCORE_TIMEOUT', '300')}s"
    )


def main(path: str) -> None:
    result = {
        "renders": False,
        "scene": None,
        "n_mobjects": 0,
        "out_of_frame": [],
        "overlaps": [],
        "error": None,
        "video_exists": False,
        "video_path": None,
        "n_plays": 0,
        "duration_s": None,
        "has_text": False,
        "has_shapes": False,
        "code_lines": 0,
    }

    code = Path(path).read_text()
    result["code_lines"] = sum(1 for line in code.splitlines() if line.strip())
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

    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(int(os.environ.get("MANIM_SCORE_TIMEOUT", "300")))

    try:
        import manim
        from manim import Scene

        render_started = time.time() - 1.0  # slack for clock skew

        # Count every play() call process-wide so scenes rendered during
        # exec_module (top-level `MyScene().render()`) still register plays.
        _orig_play = Scene.play

        def _counting_play(self, *a, **kw):
            result["n_plays"] += 1
            return _orig_play(self, *a, **kw)

        Scene.play = _counting_play

        spec = importlib.util.spec_from_file_location("candidate", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        from manim import config

        logging.getLogger("manim").setLevel(logging.ERROR)
        config.quality = "low_quality"
        scene = getattr(mod, names[0])()
        scene.render()
    except Exception as e:
        result["error"] = f"render_crash: {type(e).__name__}: {e}"
        print(json.dumps(result))
        return
    finally:
        signal.alarm(0)

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

        video = _find_video(Path("media"), render_started)
        result["video_exists"] = video is not None
        result["video_path"] = str(video) if video else None
        result["duration_s"] = _duration_s(video) if video else None

        text_types = tuple(
            t for t in (
                getattr(manim, "Text", None), getattr(manim, "Tex", None),
                getattr(manim, "MathTex", None), getattr(manim, "MarkupText", None),
                getattr(manim, "Paragraph", None),
            ) if t is not None
        )
        all_desc = [d for m in scene.mobjects for d in _descendants(m)]
        result["has_text"] = any(isinstance(d, text_types) for d in all_desc)
        result["has_shapes"] = any(
            isinstance(d, manim.VMobject) and not isinstance(d, text_types)
            for d in all_desc
        )
    except Exception as e:
        result["error"] = f"inspection_crash: {type(e).__name__}: {e}"

    print(json.dumps(result))


if __name__ == "__main__":
    main(sys.argv[1])
