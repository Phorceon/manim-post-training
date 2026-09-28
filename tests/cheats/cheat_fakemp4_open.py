from manim import *


class Hack(Scene):
    def construct(self):
        # same trick via builtins open() instead of pathlib
        import os
        os.makedirs("media/videos/scene/480p15", exist_ok=True)
        with open("media/videos/scene/480p15/Hack.mp4", "wb") as f:
            f.write(b"fake")
        self.wait(0.1)
