"""Find the skin weights that tear during a clip, by playing the clip.

reweight.py guessed at the same problem from the rest pose: a vertex carrying
arm weight from farther away than a sleeve could reach was called mis-weighted
and handed to the spine. That fixed most of the smith's front, but it is a
guess about anatomy, and the radius it needs is a compromise -- too generous
leaves webbing, too tight tears the sleeve off the arm. Some apron stayed
welded to the hammer hand and drew a shard from the bib to the fist every time
the arm went overhead.

Two ideas here, and the split matters:

- The *measurement* plays the clips. Skin the mesh at every pose the clips
  actually reach and compare each triangle edge with its own length at rest. A
  sleeve edge follows the arm and keeps its length; an edge with one end on the
  apron and the other stolen by the hand grows the length of a forearm, and
  says so in a number. Growth is reported in model units rather than as a
  ratio: a hair-thin edge doubling is invisible, and it is the ones that grow
  by a hand's width that draw shards across the screen.

- The *repair* does not use distance, or anatomy, or a list of bone names. A
  torn edge means its two ends are following different bones; smoothing the
  weights across that patch of mesh makes them follow nearly the same thing,
  and an edge whose ends move together cannot tear. So each round relaxes the
  weights of the vertices on torn edges toward their neighbours' and measures
  again. Mesh that is not tearing is never touched, which is what keeps this
  from blurring the sleeve off the arm.

    python unstretch.py in.glb out.glb [--allow 0.06] [--rounds 12]
    python unstretch.py in.glb --measure          # report, change nothing

`allow` is how much an edge may grow, in model units, before it counts as
torn. The smith is 1.8 units tall, and the shards that started this grew by
one whole unit.

Run on a dequantized model; bake.py compresses afterwards. Needs numpy, which
is a tool dependency and not the package's -- skinning 37,000 vertices through
96 poses in a Python loop takes minutes rather than seconds.
"""

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from unprop import COMPONENT, COUNT, read, read_glb, write_glb  # noqa: E402

#: How many poses to sample per clip. The tear is a whole arc, not a spike, so
#: this only has to be fine enough not to step over the top of the swing.
SAMPLES = 48


# -- posing ------------------------------------------------------------------


def quat_matrix(q):
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def compose(translation, rotation, scale):
    m = np.eye(4)
    m[:3, :3] = quat_matrix(rotation) * np.asarray(scale)
    m[:3, 3] = translation
    return m


def rest_trs(node):
    """A node's own translation/rotation/scale, however it stores them."""
    if "matrix" in node:
        m = np.array(node["matrix"], dtype=float).reshape(4, 4).T
        scale = [np.linalg.norm(m[:3, c]) or 1.0 for c in range(3)]
        basis = m[:3, :3] / np.array(scale)
        # Only ever round-tripped through compose(), so a quaternion is enough.
        trace = basis.trace()
        if trace > 0:
            s = 0.5 / np.sqrt(trace + 1.0)
            q = [
                (basis[2, 1] - basis[1, 2]) * s,
                (basis[0, 2] - basis[2, 0]) * s,
                (basis[1, 0] - basis[0, 1]) * s,
                0.25 / s,
            ]
        else:
            i = int(np.argmax([basis[0, 0], basis[1, 1], basis[2, 2]]))
            j, k = (i + 1) % 3, (i + 2) % 3
            s = 2.0 * np.sqrt(1.0 + basis[i, i] - basis[j, j] - basis[k, k])
            q = [0.0, 0.0, 0.0, (basis[k, j] - basis[j, k]) / s]
            q[i] = 0.25 * s
            q[j] = (basis[j, i] + basis[i, j]) / s
            q[k] = (basis[k, i] + basis[i, k]) / s
        return list(m[:3, 3]), q, scale
    return (
        list(node.get("translation", [0.0, 0.0, 0.0])),
        list(node.get("rotation", [0.0, 0.0, 0.0, 1.0])),
        list(node.get("scale", [1.0, 1.0, 1.0])),
    )


def sampled(times, values, moment, step, wide):
    """The channel's value at `moment`, held or blended as the clip asks."""
    if moment <= times[0]:
        return values[0]
    if moment >= times[-1]:
        return values[-1]
    after = int(np.searchsorted(times, moment))
    before = after - 1
    if step:
        return values[before]
    span = times[after] - times[before]
    t = 0.0 if span <= 0 else (moment - times[before]) / span
    a, b = np.asarray(values[before], dtype=float), np.asarray(values[after], dtype=float)
    if wide and float(a @ b) < 0:  # shortest way round, for quaternions
        b = -b
    out = a + (b - a) * t
    return out / np.linalg.norm(out) if wide else out


def channels_of(doc, blob, clip):
    """Per node, the animated translation/rotation/scale tracks of one clip."""
    tracks = {}
    for channel in clip["channels"]:
        target = channel["target"]
        path = target.get("path")
        if path not in ("translation", "rotation", "scale"):
            continue
        sampler = clip["samplers"][channel["sampler"]]
        tracks.setdefault(target["node"], {})[path] = (
            [t[0] for t in read(doc, blob, sampler["input"])],
            read(doc, blob, sampler["output"]),
            sampler.get("interpolation", "LINEAR") == "STEP",
        )
    return tracks


def world_matrices(doc, tracks, moment):
    """Every node's world matrix at one moment of one clip."""
    parent = {}
    for index, node in enumerate(doc["nodes"]):
        for child in node.get("children", []):
            parent[child] = index

    local = []
    for index, node in enumerate(doc["nodes"]):
        translation, rotation, scale = rest_trs(node)
        track = tracks.get(index, {})
        for path, wide in (("translation", False), ("rotation", True), ("scale", False)):
            if path not in track:
                continue
            times, values, step = track[path]
            value = sampled(times, values, moment, step, wide)
            if path == "translation":
                translation = value
            elif path == "rotation":
                rotation = value
            else:
                scale = value
        local.append(compose(translation, rotation, scale))

    world = [None] * len(local)

    def resolve(index):
        if world[index] is None:
            up = parent.get(index)
            world[index] = local[index] if up is None else resolve(up) @ local[index]
        return world[index]

    for index in range(len(local)):
        resolve(index)
    return world


# -- measuring ---------------------------------------------------------------


def unique_edges(indices):
    triangles = indices.reshape(-1, 3)
    pairs = np.concatenate(
        [triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]
    )
    pairs.sort(axis=1)
    return np.unique(pairs, axis=0)


def skin(positions, joints, weights, skin_matrices):
    homogeneous = np.concatenate([positions, np.ones((len(positions), 1))], axis=1)
    out = np.zeros((len(positions), 3))
    for slot in range(4):
        w = weights[:, slot]
        if not w.any():
            continue
        picked = skin_matrices[joints[:, slot]]
        out += w[:, None] * np.einsum("vij,vj->vi", picked, homogeneous)[:, :3]
    return out


def stretch(doc, blob, positions, joints, weights, edges, rest_length, clips):
    """How far each edge grows, at worst, across every sampled pose."""
    skin_def = doc["skins"][0]
    binds = np.array(read(doc, blob, skin_def["inverseBindMatrices"]), dtype=float)
    binds = binds.reshape(-1, 4, 4).transpose(0, 2, 1)

    worst = np.zeros(len(edges))
    for clip in clips:
        tracks = channels_of(doc, blob, clip)
        span = max(
            (times[-1] for times, _, _ in (t for node in tracks.values() for t in node.values())),
            default=0.0,
        )
        for step in range(SAMPLES):
            moment = span * step / max(1, SAMPLES - 1)
            world = world_matrices(doc, tracks, moment)
            matrices = np.array(
                [world[node] @ binds[i] for i, node in enumerate(skin_def["joints"])]
            )
            posed = skin(positions, joints, weights, matrices)
            length = np.linalg.norm(posed[edges[:, 0]] - posed[edges[:, 1]], axis=1)
            np.maximum(worst, length - rest_length, out=worst)
    return worst


# -- repair ------------------------------------------------------------------


def spread_out(joints, weights, bones):
    """One row per vertex with a column per bone, so weights can be averaged."""
    dense = np.zeros((len(joints), bones))
    rows = np.repeat(np.arange(len(joints)), 4)
    np.add.at(dense, (rows, joints.reshape(-1)), weights.reshape(-1))
    return dense


def pack_back(dense):
    """The four bones each vertex leans on most, renormalised to sum to one."""
    picked = np.argsort(-dense, axis=1)[:, :4]
    kept = np.take_along_axis(dense, picked, axis=1)
    total = kept.sum(axis=1, keepdims=True)
    kept = np.divide(kept, total, out=np.zeros_like(kept), where=total > 0)
    # A vertex the smoothing emptied would float free of the skeleton; hand it
    # wholly to whichever bone had most of it.
    lost = total[:, 0] <= 0
    kept[lost] = [1.0, 0.0, 0.0, 0.0]
    return picked.astype(np.int64), kept


def relax(dense, edges, chosen, pull):
    """Blend the chosen vertices' weights toward their neighbours'."""
    counted = np.bincount(edges.reshape(-1), minlength=len(dense)).astype(float)
    around = np.zeros_like(dense)
    np.add.at(around, edges[:, 0], dense[edges[:, 1]])
    np.add.at(around, edges[:, 1], dense[edges[:, 0]])
    around = np.divide(
        around, counted[:, None], out=dense.copy(), where=counted[:, None] > 0
    )
    out = dense.copy()
    out[chosen] = dense[chosen] * (1 - pull) + around[chosen] * pull
    return out


#: How far each round drags a torn vertex toward its neighbours. Whole-hearted
#: enough to converge in a handful of rounds, gentle enough that the rounds in
#: between can still measure whether it went too far.
PULL = 0.6


def repair(source: Path, target: Path | None, allow: float, rounds: int) -> None:
    doc, blob = read_glb(source)
    prim = doc["meshes"][0]["primitives"][0]
    positions = np.array(read(doc, blob, prim["attributes"]["POSITION"]), dtype=float)
    joints = np.array(read(doc, blob, prim["attributes"]["JOINTS_0"]), dtype=np.int64)
    weights = np.array(read(doc, blob, prim["attributes"]["WEIGHTS_0"]), dtype=float)
    indices = np.array([i[0] for i in read(doc, blob, prim["indices"])], dtype=np.int64)

    edges = unique_edges(indices)
    rest_length = np.linalg.norm(positions[edges[:, 0]] - positions[edges[:, 1]], axis=1)
    edges, rest_length = edges[rest_length > 1e-9], rest_length[rest_length > 1e-9]

    bones = len(doc["skins"][0]["joints"])
    clips = [c for c in doc.get("animations", []) if c["channels"]]
    tall = positions[:, 1].max() - positions[:, 1].min()
    print(f"  {len(edges)} edges over {len(clips)} clip(s), {SAMPLES} poses each")
    print(f"  the figure is {tall:.2f} units tall; an edge may grow {allow}")

    def measure(when):
        worst = stretch(doc, blob, positions, joints, weights, edges, rest_length, clips)
        torn = np.nonzero(worst > allow)[0]
        print(f"  {when}: worst edge grows {worst.max():.3f}, {len(torn)} edge(s) torn")
        return torn

    torn = measure("before")
    if target is None:
        return

    dense = spread_out(joints, weights, bones)
    done = 0
    for round_number in range(1, rounds + 1):
        if not len(torn):
            break
        done = round_number
        # The torn edges' ends, and their ends' neighbours: smoothing a vertex
        # against a ring that is itself held fast only moves the tear one row
        # over.
        ends = np.unique(edges[torn])
        touching = np.isin(edges, ends).any(axis=1)
        chosen = np.unique(edges[touching])
        dense = relax(dense, edges, chosen, PULL)
        joints, weights = pack_back(dense)
        torn = measure(f"round {round_number} ({len(chosen)} vertices relaxed)")

    print(f"  {'clean' if not len(torn) else 'still torn'} after {done} round(s)")

    # Write both attributes back over their own bytes: values changed, shapes
    # did not, so the accessors stay exactly as they were.
    import struct

    for key, rows in (("JOINTS_0", joints), ("WEIGHTS_0", weights)):
        acc = doc["accessors"][prim["attributes"][key]]
        view = doc["bufferViews"][acc["bufferView"]]
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        code = COMPONENT[acc["componentType"]]
        per = COUNT[acc["type"]]
        stride = view.get("byteStride") or per * struct.calcsize(code)
        for i, row in enumerate(rows):
            packed = list(row)
            if key == "WEIGHTS_0" and code in "BH":
                top = 255 if code == "B" else 65535
                packed = [max(0, min(top, round(c * top))) for c in packed]
            elif key == "JOINTS_0":
                packed = [int(c) for c in packed]
            struct.pack_into(f"<{per}{code}", blob, start + i * stride, *packed)

    write_glb(target, doc, blob)
    print(f"  {target.name}: {target.stat().st_size // 1024} kB")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv:
        raise SystemExit(__doc__)
    measure = "--measure" in argv
    argv = [a for a in argv if a != "--measure"]

    def flag(name, fallback):
        return type(fallback)(argv[argv.index(name) + 1]) if name in argv else fallback

    allow = flag("--allow", 0.06)
    rounds = flag("--rounds", 12)
    files = [
        a
        for i, a in enumerate(argv)
        if not a.startswith("--") and (i == 0 or not argv[i - 1].startswith("--"))
    ]
    repair(Path(files[0]), None if measure else Path(files[1]), allow, rounds)
