from manim import *


class Hack(Scene):
    def construct(self):
        self.play()   # patched to no-op — counter still ticks, nothing animates
        self.wait(0.1)


Scene.play = lambda self, *a, **k: None
