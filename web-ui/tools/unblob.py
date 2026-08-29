"""Cut everything that is not the character out of a generated model.

Asked for a blacksmith with empty hands and got a blacksmith with empty hands,
a hammer floating beside him and a block of iron on the floor. The generator
throws in props nobody asked for, and they survive rigging: bound to whatever
bone was nearest, they then fly about the room on their own.

They cannot be found by connected components -- a rigged export from Meshy is
a confetti of nine thousand islands, split at every UV seam, so the body is
not one component either. What does separate them is space. Drop the vertices
into a voxel grid, thicken it by one, and the man is one blob while anything
standing apart from him is another.

    python unblob.py in.glb out.glb [--keep 2] [--grid 220]

`keep` is how many blobs to keep, largest first: 1 is the character alone, and
more only if he is meant to be holding something. `grid` is how many voxels
the model's longest side is cut into -- finer separates more, and separates
his own fingers if taken too far.
"""

import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from unprop import append, read, read_glb, write_glb  # noqa: E402


def blobs(points, used, cuts):
    """Which spatial lump each vertex belongs to, biggest first."""
    low, high = points[used].min(0), points[used].max(0)
    step = (high - low).max() / cuts
    grid = np.zeros(((high - low) / step).astype(int) + 3, bool)
    at = ((points - low) / step).astype(int) + 1
    at = np.clip(at, 0, np.array(grid.shape) - 1)
    grid[at[used, 0], at[used, 1], at[used, 2]] = True

    # Thickened by one voxel, so a shoulder seam does not count as a gap while
    # a hammer hanging in mid-air still does.
    marks, count = ndimage.label(ndimage.binary_dilation(grid, iterations=1))
    mine = marks[at[:, 0], at[:, 1], at[:, 2]]
    sizes = np.bincount(mine[used], minlength=count + 1)
    sizes[0] = 0
    return mine, np.argsort(-sizes), step


def unblob(source: Path, target: Path, keep: int, cuts: int) -> None:
    doc, blob = read_glb(source)
    prim = doc["meshes"][0]["primitives"][0]
    points = np.array(read(doc, blob, prim["attributes"]["POSITION"]), dtype=float)
    faces = np.array([i[0] for i in read(doc, blob, prim["indices"])], dtype=np.int64).reshape(-1, 3)
    used = np.zeros(len(points), bool)
    used[faces.reshape(-1)] = True

    mine, order, step = blobs(points, used, cuts)
    print(f"  {int(used.sum())} vertices, {len(faces)} triangles, voxel {step:.4f}")
    staying = set(order[:keep].tolist())
    for rank, mark in enumerate(order[:6]):
        here = used & (mine == mark)
        if here.sum() < 5:
            continue
        box = points[here]
        print(
            f"  {'keep' if mark in staying else 'drop'} blob {rank + 1}: "
            f"{int(here.sum()):6d} verts  bbox {np.round(box.max(0) - box.min(0), 3)}"
            f"  centre {np.round(box.mean(0), 3)}"
        )

    # A triangle goes if any corner of it is on something we are not keeping,
    # so nothing is left hanging by an edge.
    alive = np.isin(mine, list(staying))
    kept = faces[alive[faces].all(axis=1)]
    print(f"  {len(faces) - len(kept)} of {len(faces)} triangles cut")

    code = "I" if len(points) > 65535 else "H"
    prim["indices"] = append(doc, blob, kept.reshape(-1).tolist(), code, "SCALAR")
    write_glb(target, doc, blob)
    print(f"  {target.name}: {target.stat().st_size // 1024} kB")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if len(argv) < 2:
        raise SystemExit(__doc__)

    def flag(name, fallback):
        return type(fallback)(argv[argv.index(name) + 1]) if name in argv else fallback

    unblob(Path(argv[0]), Path(argv[1]), flag("--keep", 1), flag("--grid", 220))
