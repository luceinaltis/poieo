"""Paint an eyelid over the top of a character's eyes, in the texture.

The generator gives its people eyes like poached eggs: a full circle of white
with a small dark centre, painted flat into the texture. A face made of circles
reads as startled whatever the body is doing, and there is nothing in the file
to fix it with -- no morph targets, no eye bones, no facial rig. Meshy says so
itself: "does not support facial rigs, eye bones, blendshapes, or morph
targets."

Hanging geometry in front of the face was tried and abandoned. A flat plane
placed by numbers against a curved head, judged through a 40-pixel figure,
landed beside the eye at every size attempted. The eye is a picture, so this
edits the picture, where being wrong is visible at a glance.

    python hood_eyes.py in.glb out.glb [drop] [--sheet eyes.png]

`drop` is how much of the eye the lid covers, from the top. 0.3 is a relaxed
eye; past about 0.5 he looks asleep. `--sheet` writes a before-and-after
close-up of every eye it found, which is the only way to check the thing.

Finding the eyes needs no UVs and no guessing at the atlas, which on these
models is a confetti of a thousand islands: an eye is a blob of near-white
with a dark pupil inside it, and there are exactly two on a face.
"""

import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import shrink_textures as glb  # noqa: E402

#: An eye is a good fraction of a face but a small fraction of an atlas. In
#: pixels of a 2048-square texture, scaled if the texture is another size.
SMALLEST = 120
BIGGEST = 6000

#: How dark a pupil is, and how pale a sclera.
PUPIL = 90
SCLERA = 175
GREY = 45

#: The lash line drawn along the lid's lower edge, as a fraction of the eye.
LASH = 0.12


def eyes_in(picture: np.ndarray) -> list:
    """Every blob of white with a dark centre: the eyes, and nothing else."""
    scale = (picture.shape[0] * picture.shape[1]) / (2048 * 2048)
    high = picture.max(2)
    low = picture.min(2)
    white = (low > SCLERA) & ((high - low) < GREY)
    dark = high < PUPIL

    labels, count = ndimage.label(white)
    found = []
    for mark in range(1, count + 1):
        blob = labels == mark
        size = int(blob.sum())
        if not SMALLEST * scale <= size <= BIGGEST * scale:
            continue
        # The pupil is not a hole in the white -- it is painted hard against
        # one edge of it, so the sclera comes out a crescent and filling it
        # fills nothing. Take the dark that touches the blob instead, then
        # close the pair up: sclera plus pupil is the eye.
        near = ndimage.binary_dilation(blob, iterations=4)
        pupil = dark & near
        if pupil.sum() < size * 0.12:
            continue  # white with nothing in it is a tooth, or a highlight
        if not ringed(blob, pupil):
            continue  # dark beside white is a tooth in shadow, not an iris
        whole = ndimage.binary_fill_holes(ndimage.binary_closing(blob | pupil, iterations=2))
        found.append(whole)
    return found


def ringed(white: np.ndarray, pupil: np.ndarray) -> bool:
    """Is the dark surrounded by the white, or merely next to it?

    The difference between an iris and the shadow under a tooth, and the only
    test that told them apart: a mouth has a white blob with dark along one
    side of it, and passes every measure of size and roundness there is.
    """
    rows, columns = np.nonzero(pupil)
    if not len(rows):
        return False
    middle = (int(rows.mean()), int(columns.mean()))
    reach = int(max(white.sum() ** 0.5, 6))
    hits = 0
    for down, across in (
        (0, 1),
        (0, -1),
        (1, 0),
        (-1, 0),
        (1, 1),
        (1, -1),
        (-1, 1),
        (-1, -1),
    ):
        for step in range(1, reach):
            row = middle[0] + down * step
            column = middle[1] + across * step
            if not (0 <= row < white.shape[0] and 0 <= column < white.shape[1]):
                break
            if white[row, column]:
                hits += 1
                break
    return hits >= 6


def skin_around(picture: np.ndarray, eye: np.ndarray) -> np.ndarray:
    """The face's own colour just outside an eye, so the lid belongs to it."""
    ring = ndimage.binary_dilation(eye, iterations=5) & ~eye
    return np.median(picture[ring], axis=0)


def hood(source: Path, target: Path, drop: float, sheet: Path | None) -> None:
    doc, blob = glb.read_glb(source)
    views = doc["bufferViews"]
    replaced = {}
    cuts = []

    for image in doc.get("images", []):
        index = image.get("bufferView")
        if index is None:
            continue
        view = views[index]
        start = view.get("byteOffset", 0)
        raw = bytes(blob[start : start + view["byteLength"]])
        picture = Image.open(io.BytesIO(raw)).convert("RGB")
        pixels = np.array(picture).astype(int)

        found = eyes_in(pixels)
        print(f"  {picture.size[0]}x{picture.size[1]}: {len(found)} eye(s)")
        for eye in found:
            rows, columns = np.nonzero(eye)
            top, bottom = rows.min(), rows.max()
            tall = bottom - top + 1
            if sheet is not None:
                cuts.append((pixels.copy(), rows, columns))

            lid = eye & (np.arange(eye.shape[0])[:, None] < top + tall * drop)
            skin = skin_around(pixels, eye)
            pixels[lid] = skin
            # The lash along its lower edge, or the lid is a smear of cheek.
            edge = eye & (
                (np.arange(eye.shape[0])[:, None] >= top + tall * drop)
                & (np.arange(eye.shape[0])[:, None] < top + tall * (drop + LASH))
            )
            pixels[edge] = (skin * 0.42).astype(int)
            print(
                f"    eye at x{columns.min()}..{columns.max()} y{top}..{bottom}"
                f" ({int(eye.sum())} px), lid over its top {drop:.0%}"
            )

        if not found:
            continue
        buffer = io.BytesIO()
        Image.fromarray(pixels.astype(np.uint8)).save(
            buffer,
            "PNG" if "png" in (image.get("mimeType") or "") else "JPEG",
            quality=95,
            optimize=True,
        )
        replaced[index] = buffer.getvalue()
        if sheet is not None:
            after = [(pixels, r, c) for _, r, c in cuts]
            side_by_side(cuts, after, sheet)

    packed = bytearray()
    for index, view in enumerate(views):
        payload = replaced.get(index)
        if payload is None:
            start = view.get("byteOffset", 0)
            payload = bytes(blob[start : start + view["byteLength"]])
        packed += b"\0" * (-len(packed) % 4)
        view["byteOffset"] = len(packed)
        view["byteLength"] = len(payload)
        packed += payload
    doc["buffers"][0]["byteLength"] = len(packed)
    glb.write_glb(target, doc, packed)
    print(f"  {target.name}: {target.stat().st_size // 1024} kB")


def side_by_side(before: list, after: list, path: Path) -> None:
    """Every eye, before over after, big enough to argue about."""
    size = 200
    sheet = Image.new("RGB", (size * len(before), size * 2), (20, 18, 15))
    for column, ((was, rows, columns), (now, _, _)) in enumerate(zip(before, after)):
        middle = ((rows.min() + rows.max()) // 2, (columns.min() + columns.max()) // 2)
        reach = max(rows.max() - rows.min(), columns.max() - columns.min())
        for row, picture in enumerate((was, now)):
            cut = picture[
                max(0, middle[0] - reach) : middle[0] + reach,
                max(0, middle[1] - reach) : middle[1] + reach,
            ]
            sheet.paste(
                Image.fromarray(cut.astype(np.uint8)).resize((size, size), Image.NEAREST),
                (column * size, row * size),
            )
    sheet.save(path)
    print(f"  {path.name}: every eye, before over after")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    argv = sys.argv[1:]
    sheet = None
    if "--sheet" in argv:
        at = argv.index("--sheet")
        sheet = Path(argv[at + 1])
        argv = argv[:at] + argv[at + 2 :]
    hood(
        Path(argv[0]),
        Path(argv[1]),
        float(argv[2]) if len(argv) > 2 else 0.3,
        sheet,
    )
