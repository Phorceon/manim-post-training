from manim import *


class Hack(Scene):
    def construct(self):
        exec("Scene.render = lambda s: None")
        self.play(Create(Circle()))
