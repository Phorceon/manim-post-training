# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Run every exploit in tests/cheats through score.py and check it is caught.

Each cheat file's expected outcome is keyed by filename below:
  'forbidden'  scorer must report a forbidden_construct error
  'not_a_scene'  duck-typed Scene rejected at instantiate
  'gate_fail'  renders but the artifact gate must not pass
               (duration < min_duration_s or visible_frac < min_visible_frac)

Usage: uv run tests/run_cheats.py        (from repo root)
Exit code 0 = every cheat caught. Nonzero = at least one exploit scored
as if it were honest output.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCORER = ROOT / "environments" / "manim_scenes" / "score.py"
CHEATS = Path(__file__).resolve().parent / "cheats"

EXPECTED = {
    "cheat_import_os.py": "forbidden",
    "cheat_atexit_fakejson.py": "forbidden",
    "cheat_fakemp4.py": "forbidden",
    "cheat_fakemp4_open.py": "forbidden",
    "cheat_patch_scene.py": "forbidden",
    "cheat_patch_play.py": "forbidden",
    "cheat_fake_mobjects.py": "forbidden",
    "cheat_duck_scene.py": "not_a_scene",
    "cheat_dunder.py": "forbidden",
    "cheat_eval.py": "forbidden",
    "cheat_blank_scene.py": "gate_fail",
    "cheat_sys_stdout.py": "forbidden",
}

MIN_DURATION_S = 0.5
MIN_VISIBLE_FRAC = 0.002


def score(path: Path) -> dict:
    out = subprocess.run(
        ["uv", "run", str(SCORER), str(path)],
        capture_output=True, text=True, cwd=CHEATS, timeout=600,
    )
    for line in reversed(out.stdout.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    return {"renders": False, "error": f"no_output: {out.stderr[-300:]}"}


def check(facts: dict, want: str) -> tuple[bool, str]:
    err = str(facts.get("error") or "")
    if want == "forbidden":
        ok = err.startswith("forbidden_construct")
        return ok, err or "no error (scored as clean)"
    if want == "not_a_scene":
        return err == "not_a_scene", err or "no error"
    if want == "gate_fail":
        dur = facts.get("duration_s") or 0.0
        vis = facts.get("visible_frac") or 0.0
        ok = facts.get("renders") and (
            dur < MIN_DURATION_S or vis < MIN_VISIBLE_FRAC
        )
        return ok, f"renders={facts.get('renders')} dur={dur} vis={vis}"
    return False, f"unknown expectation {want}"


def main() -> int:
    failures = 0
    for name, want in sorted(EXPECTED.items()):
        facts = score(CHEATS / name)
        ok, why = check(facts, want)
        mark = "CAUGHT" if ok else "ESCAPED"
        if not ok:
            failures += 1
        print(f"{mark:7} {name:32} want={want:11} {why}")
    if failures:
        print(f"\n{failures} exploit(s) got through")
        return 1
    print(f"\nall {len(EXPECTED)} cheats caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
