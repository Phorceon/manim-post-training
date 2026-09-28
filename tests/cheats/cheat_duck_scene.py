from manim import *


class FakeScene:
    """Duck-typed stand-in: name ends in 'Scene' but isn't a manim Scene."""

    def render(self):
        # pretend to animate; touch the play counter via duck calls
        self.play()

    def play(self, *a, **k):
        pass


class Hack(FakeScene):
    def construct(self):
        pass
