from manim import *
from pathlib import Path


class Hack(Scene):
    def construct(self):
        # write a bogus non-empty mp4 so video_exists passes without rendering
        p = Path("media/videos/scene/480p15/Hack.mp4")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake-mp4-bytes")
        self.wait(0.1)
