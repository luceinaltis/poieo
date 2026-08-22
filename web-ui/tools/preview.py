"""Draw the atelier bench so it can be looked at without a browser.

A sketchpad, not a mirror of record. It re-states the polygons from
src/skins/atelier/index.ts in Pillow so composition, proportion and the swing
can be judged in one step instead of one round trip per guess -- the smith was
redesigned this way after four screenshots said only "still bad".

It will drift from the real drawing, and when the two disagree the TypeScript
is right. Re-sync it when the bench changes, or delete it.

    python web-ui/tools/preview.py bench.png
"""

import math
import sys

from PIL import Image, ImageDraw

SCALE = 3  # draw big, shrink down: poor man's antialiasing
W, H = 300, 300
ORIGIN = (150, 150)

INK = {
    "bg": "#14120f",
    "floor": "#211c17",
    "floorEdge": "#2e2820",
    "wall": "#1a1611",
    "stump": "#2e2820",
    "stumpTop": "#3a332a",
    "anvil": "#8c8378",
    "anvilDark": "#5d564d",
    "forgeMouth": "#15120e",
    "forgeHot": "#d8733a",
    "ember": "#ffb454",
    "white": "#fff0c0",
    "shelf": "#2e2820",
    "skin": "#c9b79f",
    "skinDark": "#a8977f",
    "hair": "#4a423a",
    "apronIdle": "#6f665b",
    "apronWork": "#8a6a3f",
    "shirt": "#8f8578",
    "shirtDark": "#6b6257",
    "leather": "#5d564d",
    "haft": "#7a6a52",
    "iron": "#4a423a",
    "ironLit": "#6b6257",
    "shadow": "#191510",
}


class Pen:
    def __init__(self, draw, offset=(0, 0), rotation=0.0):
        self.draw = draw
        self.offset = offset
        self.rotation = rotation

    def _pt(self, x, y):
        if self.rotation:
            cos, sin = math.cos(self.rotation), math.sin(self.rotation)
            x, y = x * cos - y * sin, x * sin + y * cos
        return (
            (ORIGIN[0] + x + self.offset[0]) * SCALE,
            (ORIGIN[1] + y + self.offset[1]) * SCALE,
        )

    def poly(self, flat, fill, outline=None):
        pts = [self._pt(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]
        self.draw.polygon(pts, fill=fill, outline=outline)

    def rect(self, x, y, w, h, fill):
        self.poly([x, y, x + w, y, x + w, y + h, x, y + h], fill)

    def round_rect(self, x, y, w, h, r, fill):
        if self.rotation:
            self.poly([x, y, x + w, y, x + w, y + h, x, y + h], fill)
            return
        a, b = self._pt(x, y), self._pt(x + w, y + h)
        self.draw.rounded_rectangle([a, b], radius=r * SCALE, fill=fill)

    def circle(self, x, y, r, fill):
        self.ellipse(x, y, r, r, fill)

    def ellipse(self, x, y, rx, ry, fill):
        a, b = self._pt(x - rx, y - ry), self._pt(x + rx, y + ry)
        self.draw.ellipse([a, b], fill=fill)


def room(pen, hot):
    pen.poly([0, -40, 132, 26, 0, 92, -132, 26], INK["floor"], INK["floorEdge"])
    pen.poly([-132, 26, -132, -46, 0, -112, 0, -40], INK["wall"])
    pen.poly([132, 26, 132, -46, 0, -112, 0, -40], INK["floorEdge"])

    # A mouth set back into the wall, rather than a rectangle painted on it.
    pen.poly([-118, 10, -56, -22, -56, -64, -118, -34], "#241f19")
    pen.poly([-110, 4, -64, -20, -64, -54, -110, -32], INK["forgeMouth"])
    if hot:
        pen.poly([-106, 1, -68, -19, -68, -49, -106, -31], INK["forgeHot"])
        pen.poly([-100, -3, -74, -17, -74, -41, -100, -29], INK["ember"])

    pen.poly([20, -56, 118, -6, 118, -28, 20, -78], INK["shelf"])


def anvil(pen, hot):
    pen.ellipse(40, 64, 32, 9, INK["shadow"])
    pen.poly([16, 24, 60, 24, 54, 62, 22, 62], INK["stump"])
    pen.poly([16, 24, 60, 24, 57, 32, 19, 32], INK["stumpTop"])
    pen.rect(30, 10, 16, 15, INK["iron"])
    pen.poly([8, -4, 52, -4, 60, 2, 52, 11, 8, 11], INK["anvilDark"])
    pen.poly([8, -4, 52, -4, 48, -8, 12, -8], INK["anvil"])
    pen.poly([52, -6, 78, 0, 52, 8], INK["anvilDark"])
    if hot:
        pen.round_rect(14, -15, 32, 8, 3, INK["ember"])
        pen.round_rect(18, -14, 22, 6, 2, INK["white"])


def smith(pen, hot, lean):
    """In profile, facing the anvil.

    The room is isometric; a figure drawn flat-on reads as a sticker pasted
    over it.
    """
    apron = INK["apronWork"] if hot else INK["apronIdle"]
    x = lean

    pen.ellipse(-34 + x, 62, 24, 8, INK["shadow"])

    # a stance: back leg planted, front leg forward
    pen.poly([-54 + x, 26, -42 + x, 26, -40 + x, 62, -52 + x, 62], INK["iron"])
    pen.poly([-38 + x, 26, -26 + x, 26, -20 + x, 60, -32 + x, 60], "#3f382f")

    # torso, broad at the shoulders and turned toward the work
    pen.poly([-58 + x, -14, -26 + x, -18, -22 + x, 30, -54 + x, 30], INK["shirt"])
    pen.poly([-58 + x, -14, -46 + x, -16, -44 + x, 30, -54 + x, 30], INK["shirtDark"])
    # the apron hangs over the front rather than being cut out of it
    pen.poly([-52 + x, 0, -22 + x, -3, -20 + x, 36, -50 + x, 36], apron)
    pen.poly([-44 + x, -14, -39 + x, -15, -35 + x, 2, -40 + x, 2], INK["leather"])

    if hot:
        # the forward arm, holding the work down with tongs
        pen.poly([-30 + x, -4, -8 + x, 2, -10 + x, 10, -32 + x, 6], INK["skin"])
        pen.poly([-12 + x, 1, 20, -9, 22, -5, -10 + x, 6], "#241f19")
        pen.poly([-12 + x, 6, 20, -4, 22, 0, -10 + x, 11], "#241f19")
    else:
        # at rest, the hands are down
        pen.poly([-32 + x, -2, -22 + x, 0, -20 + x, 20, -30 + x, 20], INK["skin"])

    # head in profile: brow, nose, beard, and a cap with a brim
    pen.circle(-42 + x, -30, 12, INK["skin"])
    pen.poly([-31 + x, -33, -25 + x, -29, -31 + x, -26], INK["skin"])
    pen.poly([-52 + x, -26, -30 + x, -24, -34 + x, -8, -48 + x, -12], INK["hair"])
    pen.poly([-55 + x, -33, -29 + x, -36, -32 + x, -46, -51 + x, -46], INK["hair"])
    pen.poly([-56 + x, -33, -26 + x, -36, -26 + x, -31, -56 + x, -29], INK["iron"])


def hammer(draw, swing, lean):
    """Swung from the far shoulder, so it arcs behind the head, not across it."""
    arm = Pen(draw, offset=(-30 + lean, -14), rotation=swing)
    arm.poly([0, -5, 20, -5, 20, 5, 0, 5], INK["skinDark"])
    arm.poly([16, -3, 44, -3, 44, 3, 16, 3], INK["haft"])
    arm.poly([40, -11, 56, -11, 56, 11, 40, 11], INK["iron"])
    arm.poly([40, -11, 56, -11, 56, -6, 40, -6], INK["ironLit"])


# Raised, and the angle at which the head lands on the work. The pivot is the
# shoulder and the hammer is long, so a strike much past zero swings the head
# forward over the anvil instead of down onto it.
RAISED, STRUCK, RESTING = -1.25, 0.02, 1.15


def bench(draw, working=True, swing=RAISED):
    pen = Pen(draw)
    lean = 4 if working else 0
    room(pen, working)
    smith(pen, working, lean)
    anvil(pen, working)
    hammer(draw, swing if working else RESTING, lean)


def render(path, **kwargs):
    image = Image.new("RGB", (W * SCALE, H * SCALE), INK["bg"])
    bench(ImageDraw.Draw(image), **kwargs)
    image.resize((W, H), Image.Resampling.LANCZOS).save(path)
    print("wrote", path)


if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else "bench.png")
