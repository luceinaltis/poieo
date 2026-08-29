"""Resize the textures inside a .glb.

gltf-transform's own texture pass uses libvips, which is broken on this
machine, so this does the same job with Pillow: unpack the binary chunk,
re-encode every image smaller, and pack it back with corrected offsets.

    python shrink_textures.py in.glb out.glb [max_px] [quality]
"""

import io
import json
import struct
import sys
from pathlib import Path

from PIL import Image

JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def read_glb(path: Path):
    data = path.read_bytes()
    magic, _version, _length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, "not a glb"

    offset, chunks = 12, {}
    while offset < len(data):
        size, kind = struct.unpack_from("<II", data, offset)
        chunks[kind] = data[offset + 8 : offset + 8 + size]
        offset += 8 + size + (-size % 4)
    return json.loads(chunks[JSON_CHUNK].decode("utf-8")), bytearray(chunks[BIN_CHUNK])


def write_glb(path: Path, doc, blob: bytes) -> None:
    text = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    blob = bytes(blob) + b"\0" * (-len(blob) % 4)

    body = struct.pack("<II", len(text), JSON_CHUNK) + text + struct.pack("<II", len(blob), BIN_CHUNK) + blob
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def shrink(source: Path, target: Path, longest=512, quality=82) -> None:
    doc, blob = read_glb(source)
    views = doc["bufferViews"]

    # New bytes for the image views; everything else is copied as it stands.
    replaced = {}
    for image in doc.get("images", []):
        index = image.get("bufferView")
        if index is None:
            continue
        view = views[index]
        start = view.get("byteOffset", 0)
        raw = bytes(blob[start : start + view["byteLength"]])

        picture = Image.open(io.BytesIO(raw))
        before = picture.size
        picture.thumbnail((longest, longest), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        picture.convert("RGB").save(buffer, "JPEG", quality=quality, optimize=True)
        replaced[index] = buffer.getvalue()
        image["mimeType"] = "image/jpeg"
        print(
            f"  {before[0]}x{before[1]} -> {picture.size[0]}x{picture.size[1]}"
            f"  {len(raw) // 1024} kB -> {len(replaced[index]) // 1024} kB"
        )

    # Repack every view in order, so offsets stay valid after the images shrink.
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
    write_glb(target, doc, packed)
    print(f"  {source.name} {source.stat().st_size // 1024} kB -> {target.name} {target.stat().st_size // 1024} kB")


if __name__ == "__main__":
    shrink(
        Path(sys.argv[1]),
        Path(sys.argv[2]),
        int(sys.argv[3]) if len(sys.argv) > 3 else 512,
        int(sys.argv[4]) if len(sys.argv) > 4 else 82,
    )
