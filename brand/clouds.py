"""Render the landing's clouds as ink washes.

Six transparent WebP images in ``site/img``: three cloud banks, each drawn twice, once for
paper (``cloud-N-light.webp``, diluted ink) and once for dark ground (``cloud-N.webp``, pale
ivory). The drawing is procedural, so this file is the generation record; run it again to
reproduce the assets::

    python brand/clouds.py

It needs numpy, scipy, and Pillow, which the product itself does not use. Each bank is a
soft union of round lobes with a flat, wet underside, painted the way a wash sits on paper:
one tint, with the tone carried by transparency; ink gathering toward the underside while
the crown thins into the paper; pigment pooling where the wet edge stopped; a sideways
bleed; a hint of dry brush; paper grain. No lighting model, no volume. Decoration for the
landing page in the manner of its persimmon wash, not a weather picture.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, map_coordinates, zoom

OUT = Path(__file__).resolve().parents[1] / "site" / "img"

# Diluted warm ink on paper, and the same wash as pale ivory on dark ground.
DAY = {"tint": (108, 100, 92), "max_alpha": 0.46}
NIGHT = {"tint": (236, 228, 214), "max_alpha": 0.48}

# name: (width, height), noise seed, banks as (weight, lobes as (x, y, radius), baseline y of the underside)
CLOUDS = {
    "cloud-1": (
        (1400, 460),
        5,
        [
            (
                1.0,
                [(420, 250, 150), (600, 190, 200), (800, 215, 180), (980, 270, 130), (280, 300, 110), (700, 300, 160)],
                360,
            ),
            (0.55, [(1000, 330, 120), (1160, 350, 90), (860, 360, 100)], 400),
        ],
    ),
    "cloud-2": (
        (1000, 420),
        9,
        [
            (1.0, [(300, 220, 130), (480, 160, 170), (660, 210, 150), (200, 300, 90), (500, 290, 150)], 340),
            (0.5, [(700, 310, 110), (820, 330, 80)], 380),
        ],
    ),
    "cloud-3": (
        (1700, 340),
        13,
        [
            (
                1.0,
                [
                    (300, 190, 110),
                    (520, 150, 140),
                    (760, 170, 130),
                    (1000, 140, 150),
                    (1250, 180, 120),
                    (1450, 220, 90),
                    (640, 230, 120),
                    (1120, 230, 110),
                ],
                280,
            ),
            (0.45, [(180, 250, 70), (420, 260, 90), (1350, 270, 80), (1550, 280, 60)], 310),
        ],
    ),
}


def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0, 1)
    return t * t * (3 - 2 * t)


def value_noise(h: int, w: int, cells_y: int, cells_x: int, rng: np.random.Generator) -> np.ndarray:
    lattice = rng.random((cells_y + 2, cells_x + 2))
    y = np.linspace(0, cells_y, h, endpoint=False)
    x = np.linspace(0, cells_x, w, endpoint=False)
    y0 = np.floor(y).astype(int)
    x0 = np.floor(x).astype(int)
    sy = smoothstep(0, 1, y - y0)
    sx = smoothstep(0, 1, x - x0)
    a = lattice[np.ix_(y0, x0)]
    b = lattice[np.ix_(y0, x0 + 1)]
    c = lattice[np.ix_(y0 + 1, x0)]
    d = lattice[np.ix_(y0 + 1, x0 + 1)]
    top = a + (b - a) * sx[None, :]
    bottom = c + (d - c) * sx[None, :]
    return top + (bottom - top) * sy[:, None]


def fbm(h: int, w: int, cells: float, octaves: int, rng: np.random.Generator) -> np.ndarray:
    """Fractal Brownian motion: value noise summed over octaves, each twice as fine and half as strong."""
    total = np.zeros((h, w))
    amplitude, weight = 1.0, 0.0
    for _ in range(octaves):
        cells_x = max(1, round(cells))
        cells_y = max(1, round(cells * h / w))
        total += amplitude * value_noise(h, w, cells_y, cells_x, rng)
        weight += amplitude
        amplitude /= 2
        cells *= 2
    return total / weight


def bank(w: int, h: int, rng: np.random.Generator, lobes, base_y: float) -> tuple[np.ndarray, np.ndarray]:
    """A lobed bank with a flat underside, its outline nudged by slow noise so no lobe is a clean circle.

    Returns the bank's coverage and, separately, how close each pixel sits to a lobe's heart.
    """
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    field = np.zeros((h, w))
    for cx, cy, r in lobes:
        field += np.exp(-1.6 * (((xx - cx) / r) ** 2 + ((yy - cy) / (r * 0.8)) ** 2))
    body = (1 - np.exp(-1.4 * field)) * smoothstep(base_y + 16, base_y - 40, yy)
    warp = 0.03 * w
    coords = [
        np.clip(yy + (fbm(h, w, 3, 3, rng) - 0.5) * warp, 0, h - 1),
        np.clip(xx + (fbm(h, w, 3, 3, rng) - 0.5) * warp, 0, w - 1),
    ]
    return (
        map_coordinates(body, coords, order=1, mode="nearest"),
        map_coordinates(np.clip(field, 0, 1.2) / 1.2, coords, order=1, mode="nearest"),
    )


def render(size, seed, banks, *, tint, max_alpha) -> Image.Image:
    w, h = size
    rng = np.random.default_rng(seed)
    yy = np.mgrid[0:h, 0:w][0].astype(float)
    wash = np.zeros((h, w))
    hearts = np.zeros((h, w))
    for weight, lobes, base_y in banks:
        body, heart = bank(w, h, rng, lobes, base_y)
        wash = 1 - (1 - wash) * (1 - weight * body)
        hearts = np.maximum(hearts, heart * weight)
    rows = np.where(wash.max(axis=1) > 0.05)[0]
    top, base = (rows.min(), rows.max()) if rows.size else (0, h - 1)

    # Ink gathers toward the underside while the crown thins; each lobe keeps a slightly denser heart.
    gradation = 0.32 + 0.68 * smoothstep(top, base, yy) ** 1.1
    density = wash * gradation * (0.78 + 0.32 * hearts) * (0.72 + 0.56 * fbm(h, w, 2, 3, rng))
    # Pigment pools where the wet wash stopped along the underside.
    gy = np.gradient(gaussian_filter(wash, 3), axis=0)
    density += gaussian_filter(np.clip(-gy, 0, None), 2) * 9 * wash
    # The wash bleeds sideways; a little of the crisp edge survives.
    density = 0.62 * gaussian_filter(density, sigma=(4, 7)) + 0.38 * density
    # A hint of dry brush along the body, then paper grain.
    streak = zoom(fbm(h, max(8, w // 10), 10, 3, rng), (1, 10), order=1)[:, :w]
    streak = np.pad(streak, ((0, 0), (0, w - streak.shape[1])), mode="edge")
    density *= 0.94 + 0.12 * streak
    density *= 0.92 + 0.16 * fbm(h, w, 70, 2, rng)

    alpha = np.clip(density, 0, 1) * max_alpha
    rgb = np.broadcast_to(np.array(tint, float), (h, w, 3))
    return Image.fromarray(np.dstack([rgb, alpha * 255]).clip(0, 255).astype(np.uint8), "RGBA")


def main() -> None:
    for name, (size, seed, banks) in CLOUDS.items():
        for suffix, palette in (("", NIGHT), ("-light", DAY)):
            path = OUT / f"{name}{suffix}.webp"
            render(size, seed, banks, **palette).save(path, quality=80, method=6)
            print(f"{path.relative_to(OUT.parents[1])}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
