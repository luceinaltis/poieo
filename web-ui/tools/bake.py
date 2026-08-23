"""Turn a rigged download into the model the page ships.

Meshy hands back seven megabytes: a 2048px texture and uncompressed buffers.
The workshop is a web page, so both have to come down hard -- textures first,
then meshopt on the geometry, which is the one thing three.js can decode with a
26 kB decoder rather than a full Draco build.

    python bake.py models/rigged_glb.glb ../src/skins/atelier/smith.glb

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


def bake(source: Path, target: Path) -> None:
    work = Path(tempfile.mkdtemp())
    smaller = work / "textures.glb"
    shrink_textures.shrink(source, smaller, TEXTURE_PX, TEXTURE_QUALITY)
    print(f"  textures  {source.stat().st_size // 1024} kB"
          f" -> {smaller.stat().st_size // 1024} kB")

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
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    bake(Path(sys.argv[1]), Path(sys.argv[2]))
