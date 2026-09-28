from manim import *
import os


class Hack(Scene):
    def construct(self):
        os.system("echo hi")
        self.play(Create(Circle()))
