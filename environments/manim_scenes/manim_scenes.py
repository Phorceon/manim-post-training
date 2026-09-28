"""manim-scenes: single-turn manim code generation.

The model is asked for a complete manim script; the reward renders the first
Scene subclass in-process (score.py) and inspects the final frame's top-level
mobjects for out-of-frame placement and bounding-box overlap.
"""

import base64
import json
import os
import re
from pathlib import Path

import httpx
import verifiers.v1 as vf

SCORER = (Path(__file__).with_name("score.py")).read_bytes()

SYSTEM_PROMPT = """You write animations with Manim Community Edition. Respond with exactly one ```python code block and no prose.

Requirements:
- `from manim import *` at the top.
- Define exactly one class subclassing `Scene`; implement `construct`.
- Keep every element inside the visible frame and never let text or shapes overlap.
- The animation must actually depict the requested concept."""


def extract_code(text: str) -> str:
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S | re.I)
    return blocks[-1].strip() if blocks else text.strip()


JUDGE_RUBRIC = """You are grading a Manim animation video. The animation was requested as:

"{prompt}"

Score how faithfully the video depicts that request, penalizing visual slop: overlapping elements, unreadable text, off-screen content, blank stretches. Reply with JSON only: {{"score": <float 0.0-1.0>}}"""


async def _judge_video(video: bytes, prompt: str, config: "ManimTaskConfig") -> float | None:
    """Faithfulness score 0-1 from a video judge over OpenRouter.

    None when no key is set, the call fails, or the reply is unparseable —
    judge outages must never tank a legitimate rollout.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.post(
                f"{config.judge_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": config.judge_model,
                    "temperature": 0,
                    "max_tokens": 64,
                    "response_format": {"type": "json_object"},
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": JUDGE_RUBRIC.format(prompt=prompt)},
                            {"type": "video_url", "video_url": {"url":
                                "data:video/mp4;base64," + base64.b64encode(video).decode()}},
                        ],
                    }],
                },
            )
            res.raise_for_status()
        text = res.json()["choices"][0]["message"]["content"]
        return max(0.0, min(1.0, float(json.loads(text)["score"])))
    except Exception:
        return None


PROMPTS: list[tuple[str, str]] = [
    # easy — single concept, few elements
    ("Draw a blue circle in the center, then fill it in.", "easy"),
    ("Show the text 'Hello, Manim!' appearing letter by letter.", "easy"),
    ("Animate a square rotating 360 degrees.", "easy"),
    ("Draw a sine wave from -2π to 2π.", "easy"),
    ("Show a dot moving along the path of a circle.", "easy"),
    ("Display the equation E = mc² fading in then out.", "easy"),
    ("Animate an arrow growing from left to right.", "easy"),
    ("Draw a triangle and change its color from red to green.", "easy"),
    ("Show a number counting up from 0 to 100.", "easy"),
    ("Draw axes and plot the line y = x.", "easy"),
    ("Animate a circle growing to twice its size.", "easy"),
    ("Write 'Physics' then morph it into 'Math'.", "easy"),
    ("Draw a 5-pointed star and spin it.", "easy"),
    ("Animate a square sliding from the left edge to the right edge.", "easy"),
    ("Show the text 'π ≈ 3.14159' scaling up.", "easy"),
    ("Draw a dot bouncing up and down.", "easy"),
    ("Animate a rectangle unfolding into a square.", "easy"),
    ("Flash the text 'DONE' on screen for a moment.", "easy"),
    # medium — multiple elements, arrangement matters
    ("Transform a circle into a square, then into a triangle.", "medium"),
    ("Show the equation a² + b² = c², then highlight each term one at a time.", "medium"),
    ("Animate a pendulum swinging back and forth.", "medium"),
    ("Draw a 3x3 grid and fill each cell with a different color.", "medium"),
    ("Write 'Step 1', then replace it with 'Step 2', then 'Step 3', pinned at the top.", "medium"),
    ("Show the formula for a circle's area with each symbol labeled.", "medium"),
    ("Animate a wave traveling across the screen.", "medium"),
    ("Draw three circles side by side colored red, green, and blue.", "medium"),
    ("Show '10%' text that grows into a progress bar filling to 100%.", "medium"),
    ("Animate a small square orbiting a central dot.", "medium"),
    ("Draw the numbers 1 through 5 in a row, then sort them into descending order with arrows showing swaps.", "medium"),
    ("Show a projectile's parabolic trajectory with a moving ball.", "medium"),
    ("Animate the derivative of x² as a tangent line sliding along the curve.", "medium"),
    ("Show a vector arrow rotating while its components update as text.", "medium"),
    ("Draw a bar chart growing bar by bar for the values 3, 7, 5, 9.", "medium"),
    ("Animate the quadratic formula appearing term by term.", "medium"),
    ("Show a circle's circumference unrolling into a straight line labeled 2πr.", "medium"),
    # hard — multi-step, spatial reasoning, real risk of overlap
    ("Show a grid rotating and shearing to demonstrate a linear transformation, with labeled basis vectors.", "hard"),
    ("Approximate π by drawing polygons with increasing numbers of sides around a circle, showing the perimeter estimate.", "hard"),
    ("Visualize bubble sort on a row of 8 numbered boxes, animating each swap.", "hard"),
    ("Derive the quadratic formula by morphing ax² + bx + c = 0 step by step, keeping each line visible.", "hard"),
    ("Animate epicycles: a dot on a second circle's edge tracing a flower pattern while both circles spin.", "hard"),
    ("Show an integral as the area under a curve filling in slice by slice.", "hard"),
    ("Demonstrate the unit circle generating a sine wave, drawn side by side with a connecting dashed line.", "hard"),
    ("Animate the Collatz sequence for 27 as a line chart of its values.", "hard"),
    ("Show a matrix transforming a grid, with î and ĵ basis vectors labeled and tracked.", "hard"),
    ("Visualize eˣ as a curve with rectangles converging to its area under the curve.", "hard"),
    ("Demonstrate the chain rule: plot g(x), f(x), and f(g(x)) one at a time with labels and a legend.", "hard"),
    ("Animate the Pythagorean theorem: a right triangle with squares drawn on each side, then a² + b² = c².", "hard"),
    ("Show binary search halving a sorted row of numbers, with a highlight box on the current range.", "hard"),
    ("Animate Taylor series terms adding one at a time to approximate sin(x), showing the approximation converge.", "hard"),
    ("Show a 3D torus rotating slowly.", "hard"),
]

GOLD_SCENE = """from manim import *

class Check(Scene):
    def construct(self):
        self.play(Create(Circle()))
        self.wait(0.1)
"""


class ManimData(vf.TaskData):
    difficulty: str = "easy"


class ManimTaskConfig(vf.TaskConfig):
    violation_penalty: float = 0.1   # per out-of-frame or overlap violation
    crash_credit: float = 0.2        # parseable code + Scene that fails to render
    gate_credit: float = 0.2         # rendered but artifact-unverifiable
    cheat_penalty: float = -0.5      # denied construct (static scan hit)
    min_duration_s: float = 0.5      # decodable video at least this long
    min_visible_frac: float = 0.002  # best sampled frame must be ~0.2% lit
    judge_model: str | None = None   # video-capable model id; None disables the judge
    judge_base_url: str = "https://openrouter.ai/api/v1"


class ManimTask(vf.Task[ManimData, vf.State, ManimTaskConfig]):
    async def _score(self, code: str, runtime: vf.Runtime) -> dict:
        await runtime.write("scene.py", code.encode())
        res = await runtime.run_uv_script(SCORER, ["scene.py"])
        for line in reversed(res.stdout.splitlines()):
            if line.startswith("{"):
                return json.loads(line)
        return {"renders": False, "error": f"scorer_no_output: {res.stderr[-500:]}"}

    @vf.reward
    async def renders_clean(self, trace: vf.Trace, runtime: vf.Runtime) -> float:
        facts = await self._score(extract_code(trace.last_reply), runtime)
        trace.info["scorer"] = facts
        renders = bool(facts.get("renders"))
        violations = len(facts.get("out_of_frame", [])) + len(facts.get("overlaps", []))
        trace.record_metric("renders", float(renders))
        trace.record_metric("violations", float(violations))
        err = str(facts.get("error") or "")
        if err.startswith("forbidden_construct"):
            return self.config.cheat_penalty
        if not renders:
            crashed = err.startswith("render_crash")
            return self.config.crash_credit if crashed else 0.0
        # gate on artifacts, not in-process objects: the mp4 must decode to a
        # watchable duration and actually show pixels. Facts like n_mobjects /
        # n_plays stay advisory — model code can forge anything in-memory.
        gates_ok = (
            (facts.get("duration_s") or 0.0) >= self.config.min_duration_s
            and (facts.get("visible_frac") or 0.0) >= self.config.min_visible_frac
        )
        if not gates_ok:
            return self.config.gate_credit
        base = max(0.4, 1.0 - self.config.violation_penalty * violations)
        # semantic layer: the video judge scores whether the render actually
        # depicts the prompt — the cheat no static check can see. Multiply so a
        # faithful-but-sloppy scene stays ahead of a wrong-scene render.
        if self.config.judge_model and (video_path := facts.get("video_path")):
            j = await _judge_video(
                await runtime.read(video_path), trace.task.data.prompt, self.config)
            trace.info["judge_score"] = j
            if j is not None:
                return base * j
        return base

    async def validate(self, runtime: vf.Runtime) -> bool:
        return bool((await self._score(GOLD_SCENE, runtime)).get("renders"))


class ManimConfig(vf.TasksetConfig):
    num_tasks: int = -1
    difficulty: str | None = None
    task: ManimTaskConfig = ManimTaskConfig()


class ManimTaskset(vf.Taskset[ManimTask, ManimConfig]):
    def load(self) -> list[ManimTask]:
        rows = [p for p in PROMPTS if self.config.difficulty in (None, p[1])]
        if self.config.num_tasks > 0:
            rows = rows[: self.config.num_tasks]
        return [
            ManimTask(
                ManimData(
                    idx=i,
                    prompt=p,
                    difficulty=d,
                    system_prompt=SYSTEM_PROMPT,
                    timeout=vf.TaskTimeout(scoring=420),
                ),
                self.config.task,
            )
            for i, (p, d) in enumerate(rows)
        ]


__all__ = ["ManimTaskset"]
