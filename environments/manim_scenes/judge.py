"""VLM judge via the Devin CLI (SWE-2).

Extracts frames from a rendered manim mp4 with ffmpeg, hands them to a
`devin -p` one-shot agent which reads the images and returns a JSON
verdict. Prints one JSON line to stdout.

Usage: python judge.py path/to/video.mp4 "the requested animation"
Requires: devin CLI (authed), ffmpeg.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MODEL = "swe-2-max"
N_FRAMES = 4

RUBRIC = """You are grading an AI-generated Manim animation.

The requested animation was: {prompt}

Frames extracted evenly across the rendered video:
{paths}

Read each image file and judge ONLY what you see in them.

Reply with ONLY a JSON object on one line, no other text:
{{"overlap": <0.0-1.0>, "composition": <0.0-1.0>, "matches_prompt": <0.0-1.0>, "notes": "<one line>"}}

- overlap: 1.0 = elements clearly piled on each other / unreadable; 0.5 = cramped or touching; 0.0 = clean spacing
- composition: overall layout quality (use of frame, balance, readability)
- matches_prompt: how faithfully the video depicts the requested animation
- notes: one sentence describing the biggest visual problem, or "clean"
"""


def main(mp4: str, prompt: str) -> None:
    out = {
        "judge": False, "overlap": None, "composition": None,
        "matches_prompt": None, "notes": None, "error": None,
    }

    frames_dir = Path(tempfile.mkdtemp(prefix="manim-frames-"))
    subprocess.run(
        ["ffmpeg", "-y", "-i", mp4, "-vf", "fps=1", str(frames_dir / "f%02d.png")],
        capture_output=True,
    )
    frames = sorted(frames_dir.glob("*.png"))
    if not frames:
        out["error"] = "no_frames_extracted"
        return print(json.dumps(out))

    step = max(1, len(frames) // N_FRAMES)
    frames = frames[::step][:N_FRAMES]

    rubric = RUBRIC.format(prompt=prompt, paths="\n".join(str(f) for f in frames))
    try:
        r = subprocess.run(
            ["devin", "-p", rubric, "--model", MODEL,
             "--permission-mode", "dangerous",
             "--respect-workspace-trust", "false"],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        out["error"] = "judge_timeout"
        return print(json.dumps(out))

    m = re.search(r"\{[^{}]*\}", r.stdout, re.S)
    if not m:
        out["error"] = f"judge_no_json: {(r.stdout or r.stderr)[-300:]}"
        return print(json.dumps(out))
    try:
        verdict = json.loads(m.group(0))
    except json.JSONDecodeError:
        out["error"] = f"judge_bad_json: {m.group(0)[-300:]}"
        return print(json.dumps(out))

    for k in ("overlap", "composition", "matches_prompt", "notes"):
        out[k] = verdict.get(k)
    out["judge"] = True
    print(json.dumps(out))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
