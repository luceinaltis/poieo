"""Fold the animation clips of several .glb files into the first one.

Meshy returns one file per clip, each carrying the whole five-megabyte
character again. The room needs one character with two clips, not two
characters with one each. All the files come from the same rigging task, so
their node tables match one to one -- which reduces "retargeting" to copying
the animation's buffers across and shifting the indices.

    python merge_clips.py out.glb swing.glb idle.glb ...

Each clip is renamed to the stem of the file it came from, so the skin can ask
for "swing" and "idle" rather than Meshy's internal titles.
"""

import json
import struct
import sys
from pathlib import Path

JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def read_glb(path: Path):
    data = path.read_bytes()
    offset, doc, blob = 12, None, b""
    while offset < len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8 : offset + 8 + length]
        if kind == JSON_CHUNK:
            doc = json.loads(chunk)
        else:
            blob = chunk
        offset += 8 + length + (-length % 4)
    return doc, bytearray(blob)


def write_glb(path: Path, doc, blob) -> None:
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    blob = bytes(blob) + b"\0" * (-len(blob) % 4)
    body = (
        struct.pack("<II", len(text), JSON_CHUNK) + text
        + struct.pack("<II", len(blob), BIN_CHUNK) + blob
    )
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def carry(base, blob, donor, donor_blob, clip_name: str) -> None:
    """Copy the donor's animations into base, appending buffers as needed."""
    names = [n.get("name") for n in base["nodes"]]
    donor_names = [n.get("name") for n in donor["nodes"]]
    remap = {}
    for index, name in enumerate(donor_names):
        if name in names:
            remap[index] = names.index(name)
    missing = [donor_names[i] for i in range(len(donor_names)) if i not in remap]
    if missing:
        raise SystemExit(f"donor animates nodes the base lacks: {missing[:6]}")

    def copy_accessor(index: int) -> int:
        acc = dict(donor["accessors"][index])
        view = dict(donor["bufferViews"][acc["bufferView"]])
        start = view.get("byteOffset", 0)
        piece = donor_blob[start : start + view["byteLength"]]
        view["byteOffset"] = len(blob)
        view["buffer"] = 0
        blob.extend(piece)
        blob.extend(b"\0" * (-len(piece) % 4))
        base.setdefault("bufferViews", []).append(view)
        acc["bufferView"] = len(base["bufferViews"]) - 1
        base.setdefault("accessors", []).append(acc)
        return len(base["accessors"]) - 1

    for animation in donor.get("animations", []):
        samplers = []
        for sampler in animation["samplers"]:
            samplers.append(
                {
                    **sampler,
                    "input": copy_accessor(sampler["input"]),
                    "output": copy_accessor(sampler["output"]),
                }
            )
        channels = [
            {
                "sampler": channel["sampler"],
                "target": {
                    **channel["target"],
                    "node": remap[channel["target"]["node"]],
                },
            }
            for channel in animation["channels"]
        ]
        base.setdefault("animations", []).append(
            {"name": clip_name, "samplers": samplers, "channels": channels}
        )
    base["buffers"][0]["byteLength"] = len(blob)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    out = Path(sys.argv[1])
    first = Path(sys.argv[2])
    doc, blob = read_glb(first)
    # The base's own clip gets its file's name too, for the same reason.
    for animation in doc.get("animations", []):
        animation["name"] = first.stem.replace("anim-", "")
    for extra in sys.argv[3:]:
        donor_doc, donor_blob = read_glb(Path(extra))
        carry(doc, blob, donor_doc, donor_blob, Path(extra).stem.replace("anim-", ""))
    write_glb(out, doc, blob)
    clips = [a["name"] for a in doc.get("animations", [])]
    print(f"  {out.name}: clips {clips} ({out.stat().st_size // 1024} kB)")
