"""Swing a generated character's arms out into an A-pose, before rigging.

Auto-riggers want daylight between the arms and the body. Ask the generator
for it and you do not get it: three goes at the same prompt, spelling out "a
wide open gap of empty space between each arm and the side of the body, like
the letter A", came back with the arms hanging against the ribs every time.
Rigged from there the weights bleed off the arm into whatever is beside it --
on the last attempt an apron and a beard -- and the character comes apart the
first time he swings.

So the arms are moved here instead, in the mesh, before anything is rigged.
There are no bones yet, so this is not posing: it is a rotation of the arm's
own vertices about the shoulder, faded out near the joint so nothing tears.

    python apose.py in.glb out.glb [degrees] [--sheet before-after.png]

Meshy's rigging endpoint takes a Data URI as well as one of its own task ids,
so the result can go straight back without being hosted anywhere.

DOES NOT WORK YET, and the part that does not work is worth knowing before
anyone picks it up. Everything mechanical is right: the silhouette is read
correctly (this figure's shoulders at 0.79 of the way up, hands at 0.50),
the rotation is applied to positions and to normals, the glb round-trips,
and the width goes from 0.69 to about 1.0 as it should. What is unsolved is
deciding which vertices are arm. With the arm pressed against the ribs there
is no gap to cut at, and three fields were tried:

    a cylinder around shoulder-to-widest-band  -> hands ended on the hips,
        because the widest band is the hip as often as it is the hand
    a vertical cylinder from the shoulder      -> swallowed the chest, the
        pivot having been read at the neck rather than the joint
    the same with the pivot moved out to the   -> the torso still balloons
        shoulder joint and a tighter radius        sideways

A person does this in a modelling tool in two minutes by lassoing the arm,
because they can see it. That is the step this file is missing, and the
honest next move is either to do the selection somewhere it can be seen, or
to let a tool that already understands limbs do the rigging.
"""

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import unstretch as U  # noqa: E402
from unprop import COMPONENT, COUNT, read, read_glb, write_glb  # noqa: E402


def segment_distance(points, a, b):
    """How far each point is from the line between a and b."""
    along = b - a
    span = float(along @ along)
    t = np.zeros(len(points)) if span == 0 else np.clip((points - a) @ along / span, 0, 1)
    return np.linalg.norm(points - (a + t[:, None] * along), axis=1)


#: How thick an arm is, as a fraction of the figure. Inside this of the arm's
#: own line a vertex is all arm; past the outer one it is not arm at all.
INNER = 0.050
OUTER = 0.080

#: How far down from the crown to stop looking for a shoulder, and how much of
#: the figure the head and neck take up.
NECK = 0.82


def figure(doc, blob):
    """Every vertex in the glTF's own upright space, and the node that put it there."""
    world = U.world_matrices(doc, {}, 0.0)
    for index, node in enumerate(doc["nodes"]):
        if "mesh" in node:
            return index, world[index]
    raise SystemExit("no mesh node")


def joints(points):
    """Where the shoulders and the hands are, read off the silhouette.

    A standing figure narrows at the neck and widens again at the shoulders,
    and with the arms down it is widest where the hands hang. Both are read
    from the width profile rather than written down, because the next
    character will be a different shape.
    """
    low, high = points.min(0), points.max(0)
    tall = high[1] - low[1]
    middle = np.median(points[:, 0])

    def width(at):
        band = (points[:, 1] >= low[1] + tall * at) & (points[:, 1] < low[1] + tall * (at + 1 / 24))
        if band.sum() < 20:
            return 0.0
        return float(np.percentile(np.abs(points[band, 0] - middle), 99)) * 2

    steps = [i / 24 for i in range(24)]
    widths = {at: width(at) for at in steps}
    # The neck is the narrowest band below the crown -- not the narrowest
    # overall, which is the top of the skull, and not the head, which is wider
    # than the neck and is what a scan from the crown finds first.
    upper = [at for at in steps if NECK - 0.08 <= at <= NECK + 0.08]
    neck = min(upper, key=lambda at: widths[at]) if upper else NECK
    # Below the neck, the shoulder is where the silhouette opens out again.
    shoulder = next(
        (at for at in sorted(steps, reverse=True) if at < neck and widths[at] > widths[neck] * 1.6),
        neck - 0.1,
    )
    below = [at for at in steps if at < shoulder]
    hand = max(below, key=lambda at: widths[at]) if below else shoulder - 0.25
    return low, tall, middle, shoulder, hand


def apose(source: Path, target: Path, degrees: float, sheet: Path | None) -> None:
    doc, blob = read_glb(source)
    index, matrix = figure(doc, blob)
    turn = matrix[:3, :3]
    back = np.linalg.inv(turn)

    prim = doc["meshes"][doc["nodes"][index]["mesh"]]["primitives"][0]
    raw = np.array(read(doc, blob, prim["attributes"]["POSITION"]), dtype=float)
    points = (turn @ raw.T).T + matrix[:3, 3]

    low, tall, middle, shoulder, hand = joints(points)
    print(f"  {len(points)} vertices, {tall:.3f} tall")
    print(f"  shoulders at {shoulder:.2f} of the way up, hands at {hand:.2f}")

    moved = np.zeros(len(points))
    for side in (-1, 1):
        mine = np.sign(points[:, 0] - middle) == side
        outer = points[mine]
        if not len(outer):
            continue

        def at(fraction, pick):
            band = (outer[:, 1] >= low[1] + tall * fraction) & (outer[:, 1] < low[1] + tall * (fraction + 1 / 24))
            if band.sum() < 5:
                return None
            return np.array([pick(outer[band, 0]), float(outer[band, 1].mean()), np.median(outer[band, 2])])

        # The joint sits just inside the outer edge of the shoulder, not at the
        # median of everything on that side -- the median is up by the neck,
        # and a cylinder hung from there swallows the whole chest.
        top = at(shoulder, lambda x: float(np.percentile(x, 97 if side > 0 else 3)) * 0.85)
        if top is None:
            continue
        # Straight down from the shoulder, not down to where the silhouette is
        # widest. The widest band is the hip as often as it is the hand, and a
        # line aimed at a hip drags half the arm's weight into the waist --
        # which came out as a man standing with his hands on his hips.
        bottom = top + np.array([0.0, -(shoulder - hand) * tall, 0.0])

        # How far each vertex is from the arm's own line, and how much of the
        # turn it therefore takes. Nothing above the shoulder moves at all --
        # the head and the beard are not attached to the arm.
        away = segment_distance(points, top, bottom)
        share = np.clip((OUTER * tall - away) / ((OUTER - INNER) * tall), 0, 1)
        share[~mine] = 0
        share *= np.clip((low[1] + tall * (shoulder + 1 / 24) - points[:, 1]) / (tall * 0.04), 0, 1)

        # Swung about the shoulder, in the plane of the body: out and a little
        # up, which is what an A-pose is. The arm hangs below the pivot, so a
        # positive turn on the right takes it outward -- the other sign folds
        # both arms across the chest, which is how this was first written.
        angle = np.radians(degrees) * side
        about = top
        offset = points - about
        cos, sin = np.cos(angle * share), np.sin(angle * share)
        spun = np.stack(
            [
                offset[:, 0] * cos - offset[:, 1] * sin,
                offset[:, 0] * sin + offset[:, 1] * cos,
                offset[:, 2],
            ],
            axis=1,
        )
        points = about + spun
        moved = np.maximum(moved, share)
        print(
            f"  {'right' if side > 0 else 'left':5}: shoulder at x{top[0]:+.3f} y{top[1]:+.3f},"
            f" hand at x{bottom[0]:+.3f} y{bottom[1]:+.3f},"
            f" {int((share > 0.5).sum())} vertices swung {degrees:.0f} deg"
        )

    span = points[:, 0].max() - points[:, 0].min()
    print(f"  width {raw.shape and (turn @ raw.T).T[:, 0].ptp():.3f} -> {span:.3f}")

    put(doc, blob, prim["attributes"]["POSITION"], (back @ (points - matrix[:3, 3]).T).T)
    if "NORMAL" in prim["attributes"]:
        turned_normals(doc, blob, prim, turn, back, moved, degrees, points, middle)
    write_glb(target, doc, blob)
    print(f"  {target.name}: {target.stat().st_size // 1024} kB")


def turned_normals(doc, blob, prim, turn, back, share, degrees, points, middle) -> None:
    """Normals have to take the same turn, or the arms light like a dent."""
    raw = np.array(read(doc, blob, prim["attributes"]["NORMAL"]), dtype=float)
    world = (turn @ raw.T).T
    side = np.where(points[:, 0] >= middle, 1.0, -1.0)
    angle = np.radians(degrees) * side * share
    cos, sin = np.cos(angle), np.sin(angle)
    spun = np.stack(
        [
            world[:, 0] * cos - world[:, 1] * sin,
            world[:, 0] * sin + world[:, 1] * cos,
            world[:, 2],
        ],
        axis=1,
    )
    put(doc, blob, prim["attributes"]["NORMAL"], (back @ spun.T).T)


def put(doc, blob, accessor: int, rows) -> None:
    """Write values back over their own bytes; the shapes have not changed."""
    import struct

    acc = doc["accessors"][accessor]
    view = doc["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    code = COMPONENT[acc["componentType"]]
    per = COUNT[acc["type"]]
    stride = view.get("byteStride") or per * struct.calcsize(code)
    for i, row in enumerate(rows):
        struct.pack_into(f"<{per}{code}", blob, start + i * stride, *row)


if __name__ == "__main__":
    argv = sys.argv[1:]
    if len(argv) < 2:
        raise SystemExit(__doc__)
    sheet = None
    if "--sheet" in argv:
        at = argv.index("--sheet")
        sheet = Path(argv[at + 1])
        argv = argv[:at] + argv[at + 2 :]
    apose(Path(argv[0]), Path(argv[1]), float(argv[2]) if len(argv) > 2 else 25.0, sheet)
