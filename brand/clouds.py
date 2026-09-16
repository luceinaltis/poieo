"""Render the landing's clouds.

Six transparent WebP images in ``site/img``: three cloud shapes, each drawn twice, once for
dark ground (``cloud-N.webp``, moonlit grey) and once for paper (``cloud-N-light.webp``,
sun-lit white). The drawing is procedural, so this file is the generation record; run it
again to reproduce the assets::

    python brand/clouds.py

It needs numpy, scipy, and Pillow, which the product itself does not use. A cloud is a soft
union of round puffs, cut into billows by inverted Worley noise and fractal noise, then lit
from the upper left by treating the smoothed density as a height field. It is decoration on
the landing page, not a weather model.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, map_coordinates

OUT = Path(__file__).resolve().parents[1] / "site" / "img"
LIGHT_DIRECTION = np.array([-0.30, -0.80, 0.52])

# Sun-lit white with warm grey undersides, thin edges glowing where light passes through.
DAY = {
    "light": (255, 253, 249),
    "shadow": (146, 137, 126),
    "ambient": 0.42,
    "gain": 0.68,
    "texture": 0.45,
    "core": (0.40, 0.72),
    "fringe": (0.18, 0.48),
    "glow": 0.45,
    "occlusion": 0.45,
}
# Moonlit grey: denser and calmer, so the dark sky does not show through as mottling.
NIGHT = {
    "light": (214, 206, 192),
    "shadow": (66, 60, 54),
    "ambient": 0.46,
    "gain": 0.62,
    "texture": 0.30,
    "core": (0.34, 0.66),
    "fringe": (0.16, 0.44),
    "glow": 0.25,
    "occlusion": 0.40,
}

# name: (width, height), puffs as (x, y, radius), baseline y of the flat underside, noise seed
CLOUDS = {
    "cloud-1": (
        (1200, 480),
        [
            (600, 190, 230),
            (420, 250, 180),
            (790, 240, 175),
            (300, 300, 130),
            (920, 300, 120),
            (520, 300, 170),
            (700, 290, 160),
            (200, 340, 90),
            (1010, 345, 80),
        ],
        372,
        1,
    ),
    "cloud-2": (
        (900, 460),
        [
            (450, 170, 200),
            (300, 250, 150),
            (600, 240, 160),
            (200, 320, 100),
            (700, 320, 95),
            (450, 300, 170),
            (560, 330, 120),
        ],
        366,
        7,
    ),
    "cloud-3": (
        (1400, 360),
        [
            (700, 150, 190),
            (450, 190, 150),
            (950, 180, 160),
            (250, 230, 110),
            (1150, 230, 110),
            (600, 220, 150),
            (820, 230, 140),
            (130, 270, 70),
            (1290, 265, 70),
            (1000, 250, 100),
        ],
        292,
        11,
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


def worley(h: int, w: int, cells: int, rng: np.random.Generator) -> np.ndarray:
    """Distance to the nearest jittered lattice point, 0 at the point and 1 a cell away: inverted, round puffs."""
    size = w / cells
    grid_y, grid_x = int(np.ceil(h / size)) + 3, cells + 3
    grid = np.mgrid[0:grid_y, 0:grid_x].transpose(1, 2, 0).astype(float)
    points = (grid + rng.random((grid_y, grid_x, 2))) * size - size
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    cell_y = ((yy + size) // size).astype(int)
    cell_x = ((xx + size) // size).astype(int)
    nearest = np.full((h, w), np.inf)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            iy = np.clip(cell_y + dy, 0, grid_y - 1)
            ix = np.clip(cell_x + dx, 0, grid_x - 1)
            nearest = np.minimum(nearest, np.hypot(yy - points[iy, ix, 0], xx - points[iy, ix, 1]))
    return np.clip(nearest / size, 0, 1)


def lit(thickness: np.ndarray, relief: float) -> np.ndarray:
    """Diffuse light on the thickness map read as a height field."""
    gy, gx = np.gradient(thickness)
    normal = np.dstack([-gx * relief, -gy * relief, np.ones_like(thickness)])
    normal /= np.linalg.norm(normal, axis=2, keepdims=True)
    return np.clip(normal @ (LIGHT_DIRECTION / np.linalg.norm(LIGHT_DIRECTION)), 0, 1)


def render(size, puffs, baseline, seed, *, light, shadow, ambient, gain, texture, core, fringe, glow, occlusion):
    w, h = size
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    field = np.zeros((h, w))
    for cx, cy, r in puffs:
        field += np.exp(-1.5 * (((xx - cx) / r) ** 2 + ((yy - cy) / (r * 0.85)) ** 2))
    body = (1 - np.exp(-1.3 * field)) * smoothstep(baseline + 12, baseline - 34, yy)

    # Billows and texture are sampled through a gentle domain warp so nothing sits on a grid.
    warp = 0.05 * w
    coords = [
        np.clip(yy + (fbm(h, w, 2, 3, rng) - 0.5) * warp, 0, h - 1),
        np.clip(xx + (fbm(h, w, 2, 3, rng) - 0.5) * warp, 0, w - 1),
    ]
    cells = max(3, round(w / 240))
    billow = sum(weight * (1 - worley(h, w, cells * scale, rng)) for weight, scale in ((0.55, 1), (0.30, 2), (0.15, 4)))
    billow = map_coordinates(billow, coords, order=1, mode="nearest")
    grain = map_coordinates(fbm(h, w, 4, 5, rng), coords, order=1, mode="nearest")
    fine = fbm(h, w, 16, 3, rng)
    density = body * (0.25 + 0.95 * billow) * (1 - texture / 2 + texture * grain) + 0.14 * (fine - 0.5)
    alpha = 0.5 * smoothstep(*fringe, density) + 0.5 * smoothstep(*core, density)
    alpha = gaussian_filter(np.clip(alpha, 0, 1), 0.8)

    coarse = gaussian_filter(alpha, 12)
    diffuse = 0.62 * lit(coarse, 120) + 0.38 * lit(gaussian_filter(alpha, 4), 32)
    rows = np.where(alpha.max(axis=1) > 0.05)[0]
    top = rows.min() if rows.size else 0
    depth = np.clip((yy - top) / max(1.0, baseline - top), 0, 1)
    shade = (ambient + gain * diffuse) * (1 - occlusion * depth**1.4 * coarse / max(coarse.max(), 1e-6))
    shade = np.clip(shade, 0, 1)
    shade += (1 - shade) * glow * (1 - alpha)

    light, shadow = np.array(light, float), np.array(shadow, float)
    rgb = shadow + (light - shadow) * shade[..., None]
    return Image.fromarray(np.dstack([rgb, alpha * 255]).clip(0, 255).astype(np.uint8), "RGBA")


def main() -> None:
    for name, (size, puffs, baseline, seed) in CLOUDS.items():
        for suffix, palette in (("", NIGHT), ("-light", DAY)):
            path = OUT / f"{name}{suffix}.webp"
            render(size, puffs, baseline, seed, **palette).save(path, quality=80, method=6)
            print(f"{path.relative_to(OUT.parents[1])}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
