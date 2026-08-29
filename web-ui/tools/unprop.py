"""Cut a prop out of a character's hand.

The generator welds whatever it puts in a hand into the body mesh -- one mesh,
one material, no way to hide it at runtime. But a prop is still the only thing
far from the wrist that follows the hand bone, so it can be cut by skinning and
distance: drop every triangle whose corners all follow that bone and all sit
outside a fist's radius of it.

    python unprop.py raw.glb out.glb LeftHand 0.10

The hole this leaves is inside the closed fist, where nothing can see it. Run it
on a dequantized model; bake.py compresses afterwards.
"""

import json
import struct
import sys
from pathlib import Path

JSON_CHUNK = 0x4E4F534A
COMPONENT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


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


def write_glb(path: Path, doc, blob: bytearray) -> None:
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    blob += b"\0" * (-len(blob) % 4)
    body = struct.pack("<II", len(text), JSON_CHUNK) + text + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def read(doc, blob, index):
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    per, code = COUNT[acc["type"]], COMPONENT[acc["componentType"]]
    stride = view.get("byteStride") or per * struct.calcsize(code)
    return [struct.unpack_from(f"<{per}{code}", blob, start + i * stride) for i in range(acc["count"])]


def append(doc, blob, values, code, kind):
    """Add an accessor over freshly appended bytes, and return its index."""
    start = len(blob)
    for value in values:
        blob += struct.pack(f"<{code}", value)
    doc["bufferViews"].append({"buffer": 0, "byteOffset": start, "byteLength": len(blob) - start})
    doc["buffers"][0]["byteLength"] = len(blob)
    doc["accessors"].append(
        {
            "bufferView": len(doc["bufferViews"]) - 1,
            "componentType": {"I": 5125, "H": 5123}[code],
            "count": len(values),
            "type": kind,
        }
    )
    return len(doc["accessors"]) - 1


def inverse(m):
    """Where a column-major 4x4 sends the origin when run backwards.

    Solved rather than transposed: these matrices carry the centimetres-to-
    metres scale the generator exports with, and transposing a scaled rotation
    is off by the square of it.
    """
    rows = [[m[c * 4 + r] for c in range(4)] + [1.0 if i == r else 0.0 for i in range(4)] for r in range(4)]
    for col in range(4):
        pivot = max(range(col, 4), key=lambda r: abs(rows[r][col]))
        rows[col], rows[pivot] = rows[pivot], rows[col]
        scale = rows[col][col]
        if abs(scale) < 1e-12:
            raise SystemExit("singular inverse bind matrix")
        rows[col] = [value / scale for value in rows[col]]
        for r in range(4):
            if r != col and rows[r][col]:
                factor = rows[r][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col])]
    return [rows[r][7] for r in range(3)]


def cut(source: Path, target: Path, bone_name: str, radius: float) -> None:
    doc, blob = read_glb(source)
    prim = doc["meshes"][0]["primitives"][0]
    positions = read(doc, blob, prim["attributes"]["POSITION"])
    joints = read(doc, blob, prim["attributes"]["JOINTS_0"])
    weights = read(doc, blob, prim["attributes"]["WEIGHTS_0"])
    indices = [i[0] for i in read(doc, blob, prim["indices"])]

    skin = doc["skins"][0]
    names = [doc["nodes"][n].get("name", f"node{n}") for n in skin["joints"]]
    if bone_name not in names:
        raise SystemExit(f"no bone {bone_name}; have {names}")
    slot = names.index(bone_name)

    # Where the bone sits in the mesh's own space: the inverse bind matrix maps
    # mesh space into the bone, so its inverse puts the bone back in the mesh.
    binds = read(doc, blob, skin["inverseBindMatrices"])
    origin = inverse(binds[slot])

    def outside(v):
        follows = sum(weights[v][s] for s in range(4) if joints[v][s] == slot)
        if follows <= 0.5:
            return False
        away = sum((positions[v][i] - origin[i]) ** 2 for i in range(3)) ** 0.5
        return away > radius

    far = [outside(v) for v in range(len(positions))]
    kept = []
    dropped = 0
    for t in range(0, len(indices), 3):
        corners = indices[t : t + 3]
        if all(far[v] for v in corners):
            dropped += 1
            continue
        kept.extend(corners)

    print(f"  {bone_name}: {sum(far)} verts beyond {radius}, {dropped} of {len(indices) // 3} triangles cut")

    code = "I" if len(positions) > 65535 else "H"
    prim["indices"] = append(doc, blob, kept, code, "SCALAR")
    write_glb(target, doc, blob)
    print(f"  {target} ({target.stat().st_size // 1024} kB)")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    cut(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 0.10)
