"""Repair skin weights that smear the body when an arm goes overhead.

Auto-rigging weights by proximity in the rest pose, and an apron hem hanging
near a relaxed hand picks up arm weight. Raise the arm overhead -- the swing
clip does, hard -- and those torso vertices are dragged with it, stretching
the front of the model into cobwebs.

The repair is geometric: a vertex that carries arm weight but sits farther
from the whole arm's line than any sleeve could reach is mis-weighted, so
its arm weight moves to the nearest spine bone and the rest is left alone.

    python reweight.py in.glb out.glb [reach]

`reach` scales how far from the arm's centreline clothing may plausibly
sit. The upper arm runs close to the chest, so its own reach is kept tight
regardless: an apron bib is not a sleeve. Default 1.0.
"""

import struct
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from unprop import COMPONENT, COUNT, inverse, read, read_glb, write_glb  # noqa: E402

ARMS = {
    "Right": ["RightArm", "RightForeArm", "RightHand"],
    "Left": ["LeftArm", "LeftForeArm", "LeftHand"],
}
SPINES = ["Spine02", "Spine01", "Spine", "Spine1", "Hips"]


def segment_distance(p, a, b):
    ab = [b[i] - a[i] for i in range(3)]
    ap = [p[i] - a[i] for i in range(3)]
    span = sum(c * c for c in ab)
    t = 0.0 if span == 0 else max(0.0, min(1.0, sum(ap[i] * ab[i] for i in range(3)) / span))
    near = [a[i] + ab[i] * t for i in range(3)]
    return sum((p[i] - near[i]) ** 2 for i in range(3)) ** 0.5


def repair(source: Path, target: Path, reach: float) -> None:
    doc, blob = read_glb(source)
    prim = doc["meshes"][0]["primitives"][0]
    positions = read(doc, blob, prim["attributes"]["POSITION"])
    joints = read(doc, blob, prim["attributes"]["JOINTS_0"])
    weights = read(doc, blob, prim["attributes"]["WEIGHTS_0"])

    skin = doc["skins"][0]
    names = [doc["nodes"][n].get("name", "?") for n in skin["joints"]]
    binds = read(doc, blob, skin["inverseBindMatrices"])
    where = {name: inverse(binds[i]) for i, name in enumerate(names)}

    # The arm's centreline in the mesh's rest space: shoulder to elbow to
    # wrist, plus a stub past the wrist for the fist. Each segment carries its
    # own reach -- the upper arm brushes the chest, so anything more than a
    # shirtsleeve away from it is bib, not sleeve; the forearm hangs in令?air
    # and its rolled cuff is thick.
    chains = {}
    for side, bones in ARMS.items():
        if not all(b in where for b in bones):
            continue
        arm, fore, hand = (where[b] for b in bones)
        fist = [hand[i] + (hand[i] - fore[i]) * 0.6 for i in range(3)]
        chains[side] = {
            "slots": {names.index(b) for b in bones},
            "segments": [
                (arm, fore, 0.12),
                (fore, hand, 0.18),
                (hand, fist, 0.18),
            ],
        }

    spine_slot = next(names.index(b) for b in SPINES if b in names)

    moved = 0
    for v in range(len(positions)):
        p = positions[v]
        j = list(joints[v])
        w = list(weights[v])
        touched = False
        for slot in range(4):
            if w[slot] <= 0:
                continue
            side = next((s for s, c in chains.items() if j[slot] in c["slots"]), None)
            if side is None:
                continue
            past = min(segment_distance(p, a, b) - allowed * reach for a, b, allowed in chains[side]["segments"])
            if past <= 0:
                continue
            # Too far from the arm to be sleeve: this weight belongs to the body.
            spot = next((k for k in range(4) if j[k] == spine_slot and w[k] > 0), None)
            if spot is None:
                j[slot] = spine_slot
            else:
                w[spot] += w[slot]
                w[slot] = 0.0
            touched = True
        if touched:
            moved += 1
            joints[v] = tuple(j)
            weights[v] = tuple(w)

    print(f"  {moved} of {len(positions)} vertices re-weighted (reach {reach})")

    # Write both attributes back over their own bytes: values changed, shapes
    # did not, so the accessors stay exactly as they were.
    for key, rows in (("JOINTS_0", joints), ("WEIGHTS_0", weights)):
        acc = doc["accessors"][prim["attributes"][key]]
        view = doc["bufferViews"][acc["bufferView"]]
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        code = COMPONENT[acc["componentType"]]
        per = COUNT[acc["type"]]
        stride = view.get("byteStride") or per * struct.calcsize(code)
        for i, row in enumerate(rows):
            packed = row
            if key == "WEIGHTS_0" and code in "BH":
                top = 255 if code == "B" else 65535
                packed = [max(0, min(top, round(c * top))) for c in row]
            struct.pack_into(f"<{per}{code}", blob, start + i * stride, *packed)

    write_glb(target, doc, blob)
    print(f"  {target.name}: {target.stat().st_size // 1024} kB")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    repair(
        Path(sys.argv[1]),
        Path(sys.argv[2]),
        float(sys.argv[3]) if len(sys.argv) > 3 else 1.0,
    )
