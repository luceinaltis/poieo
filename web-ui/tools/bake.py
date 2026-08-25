"""Turn a rigged download into the model the page ships.

Meshy hands back seven megabytes: a 2048px texture and uncompressed buffers.
The workshop is a web page, so both have to come down hard -- textures first,
then meshopt on the geometry, which is the one thing three.js can decode with a
26 kB decoder rather than a full Draco build.

    python bake.py models/rigged_glb.glb ../src/skins/atelier/smith.glb [max_px] [keep]

Props get by on 256px textures; only the character's face earns 512.

`keep` is the fraction of the triangles to keep. A character comes back from
the generator at whatever density it felt like -- the last one arrived with
114,000 vertices for a figure the board draws a hundred pixels tall, three of
them at once, on a phone. Simplification runs before meshopt, since meshopt is
the encoding and this is the geometry.

The result is checked in, because a build should not depend on an API key.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import shrink_textures  # noqa: E402

# Big enough that the face still reads in a close-up, small enough that the
# whole model stays under a megabyte.
TEXTURE_PX = 512
TEXTURE_QUALITY = 80


def bake(source: Path, target: Path, texture_px: int = TEXTURE_PX, keep: float = 1.0) -> None:
    work = Path(tempfile.mkdtemp())
    smaller = work / "textures.glb"
    shrink_textures.shrink(source, smaller, texture_px, TEXTURE_QUALITY)
    print(f"  textures  {source.stat().st_size // 1024} kB"
          f" -> {smaller.stat().st_size // 1024} kB")

    if keep < 1.0:
        thinner = work / "thinner.glb"
        subprocess.run(
            ["npx", "--yes", "--package", "@gltf-transform/cli",
             "gltf-transform", "simplify", str(smaller), str(thinner),
             "--ratio", str(keep), "--error", "0.001"],
            check=True,
            shell=True,
            cwd=HERE.parent,
        )
        print(f"  geometry  {smaller.stat().st_size // 1024} kB"
              f" -> {thinner.stat().st_size // 1024} kB at {keep:.0%} of the triangles")
        smaller = thinner

    packed = work / "packed.glb"
    subprocess.run(
        ["npx", "--yes", "--package", "@gltf-transform/cli",
         "gltf-transform", "meshopt", str(smaller), str(packed)],
        check=True,
        shell=True,
        cwd=HERE.parent,
    )
    print(f"  geometry  -> {packed.stat().st_size // 1024} kB")

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(packed, target)
    shutil.rmtree(work, ignore_errors=True)
    print(f"  {target} ({target.stat().st_size // 1024} kB)")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4, 5):
        raise SystemExit(__doc__)
    bake(
        Path(sys.argv[1]),
        Path(sys.argv[2]),
        int(sys.argv[3]) if len(sys.argv) > 3 else TEXTURE_PX,
        float(sys.argv[4]) if len(sys.argv) > 4 else 1.0,
    )
