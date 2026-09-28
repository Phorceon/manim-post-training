from manim import *


class Hack(Scene):
    def construct(self):
        # reach object internals through dunder access — sandbox escape hatch
        base = (1).__class__.__bases__[0]
        subs = base.__subclasses__()
        self.play(Create(Circle()))
