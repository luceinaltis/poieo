"""List the skeleton and animations inside a .glb, so the arm can be found."""

import json
import struct
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "models/rig-false.glb")
data = path.read_bytes()
offset, chunks = 12, {}
while offset < len(data):
    size, kind = struct.unpack_from("<II", data, offset)
    chunks[kind] = data[offset + 8 : offset + 8 + size]
    offset += 8 + size + (-size % 4)

doc = json.loads(chunks[0x4E4F534A].decode("utf-8"))
nodes = doc.get("nodes", [])

print("  animations:", [a.get("name") for a in doc.get("animations", [])] or "none")
print("  skins:", len(doc.get("skins", [])))

joints = set()
for skin in doc.get("skins", []):
    joints.update(skin.get("joints", []))
print(f"  joints: {len(joints)}")

wanted = ("arm", "hand", "shoulder", "fore", "elbow", "spine", "clav")
for index in sorted(joints):
    name = (nodes[index].get("name") or "").strip()
    if any(w in name.lower() for w in wanted):
        print(f"    [{index}] {name}")
