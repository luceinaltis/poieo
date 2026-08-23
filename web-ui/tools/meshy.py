"""Ask Meshy for a model, then download it. Run this yourself, not Claude.

The key is read from the repo's .env (gitignored), used in one Authorization
header, and never printed or written anywhere.

    python meshy.py balance                 # spends nothing
    python meshy.py preview smith-striking  # cheap, untextured shape
    python meshy.py status                  # how far along
    python meshy.py refine smith-striking   # textures, once the shape is right
    python meshy.py fetch                   # download finished models as .glb

Names: smith-striking, smith-resting, anvil, forge, props
"""

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENV = Path("C:/Users/82109/Desktop/poieo/.env")
OUT = Path("C:/Users/82109/poieo-demo/models")
STATE = Path("C:/Users/82109/poieo-demo/meshy-tasks.json")
API = "https://api.meshy.ai/openapi"

# The forge asks for no fire on purpose: the light is drawn in code so it can
# spill onto the walls and the smith, and a flame baked into a texture could
# never be turned off when the flow goes idle.
SUBJECTS = {
    # No tongs. Asking for a second prop got a misshapen slab welded to the
    # hand, and the model is one mesh with one material, so a bad prop cannot
    # be hidden or deleted afterwards. The work on the anvil is a box drawn in
    # code instead, which costs nothing and is always the right shape.
    "smith": (
        "A stylized medieval blacksmith standing in a neutral A-pose reference "
        "stance: upright, feet shoulder-width apart, both arms hanging relaxed "
        "and slightly away from the body, elbows straight, looking forward. He "
        "holds a forging hammer in his right hand, hanging at his side. His "
        "left hand is empty and open, holding nothing at all, fingers relaxed, "
        "no tool, no tongs, no props in the left hand. Heavy brown leather "
        "apron with shoulder straps over a linen shirt with rolled sleeves, "
        "thick boots, short red beard, flat cap, clearly defined open eyes. "
        "Stylized game character, slightly cartoon proportions, clean topology, "
        "PBR textures. This is a rigging reference stance, not an action pose: "
        "he is not swinging, not bending, not leaning over anything."
    ),
    "anvil": (
        "A blacksmith's anvil on a thick worn wooden stump, dark pitted iron with a "
        "polished top face and a pointed horn, iron banding around the stump. "
        "Game-ready prop, PBR textures."
    ),
    "forge": (
        "A medieval blacksmith's forge of soot-blackened stone with an arched "
        "opening and a stone chimney hood, empty cold hearth, no fire, no flames, "
        "no glowing embers. Game-ready prop, PBR textures."
    ),
    "props": (
        "A blacksmith's wooden tool rack hung with tongs and hammers, beside a coal "
        "basket and a wooden quenching barrel. Game-ready props, PBR textures."
    ),
}


def key() -> str:
    raw = ENV.read_text(encoding="utf-8-sig")
    for line in raw.splitlines() or [raw]:
        found = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$", line)
        if found and "meshy" in found.group(1).lower():
            return found.group(2).strip().strip("\"'")
    raise SystemExit(f"no meshy key in {ENV}")


def call(path: str, payload=None):
    request = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {key()}",
            "Content-Type": "application/json",
        },
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{path}: HTTP {error.code} {error.read().decode()[:300]}")


def tasks() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def remember(name: str, stage: str, task_id: str) -> None:
    state = tasks()
    state.setdefault(name, {})[stage] = task_id
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def wanted(argv):
    names = [a for a in argv if a in SUBJECTS]
    unknown = [a for a in argv if a not in SUBJECTS]
    if unknown:
        raise SystemExit(f"unknown: {unknown}. known: {list(SUBJECTS)}")
    return names or ["smith-striking"]


def balance():
    print(call("/v1/balance"))


def preview(names):
    for name in names:
        result = call(
            "/v2/text-to-3d",
            {
                "mode": "preview",
                "art_style": "realistic",
                "should_remesh": True,
                "prompt": SUBJECTS[name],
            },
        )
        remember(name, "preview", result["result"])
        print(f"  {name}: queued")


def refine(names):
    for name in names:
        preview_id = tasks().get(name, {}).get("preview")
        if not preview_id:
            print(f"  {name}: nothing to refine yet")
            continue
        result = call(
            "/v2/text-to-3d",
            {"mode": "refine", "preview_task_id": preview_id, "enable_pbr": True},
        )
        remember(name, "refine", result["result"])
        print(f"  {name}: refine queued")


def status():
    for name, stages in tasks().items():
        for stage, task_id in stages.items():
            task = call(f"/v2/text-to-3d/{task_id}")
            print(f"  {name} {stage}: {task.get('status')} {task.get('progress', 0)}%")


def wait(minutes=12):
    """Poll until every queued task settles. Meshy takes minutes, not seconds."""
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        pending = False
        for name, stages in tasks().items():
            for stage, task_id in stages.items():
                task = call(f"/v2/text-to-3d/{task_id}")
                state = task.get("status")
                print(f"  {name} {stage}: {state} {task.get('progress', 0)}%", flush=True)
                if state in ("PENDING", "IN_PROGRESS"):
                    pending = True
        if not pending:
            return
        time.sleep(20)
    print("  still running; run status again later")


def fetch():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, stages in tasks().items():
        task_id = stages.get("refine") or stages.get("preview")
        task = call(f"/v2/text-to-3d/{task_id}")
        if task.get("status") != "SUCCEEDED":
            print(f"  {name}: {task.get('status')} {task.get('progress', 0)}%")
            continue
        url = (task.get("model_urls") or {}).get("glb")
        if not url:
            print(f"  {name}: succeeded but no glb")
            continue
        target = OUT / f"{name}.glb"
        with urllib.request.urlopen(url, timeout=300) as response:
            target.write_bytes(response.read())
        print(f"  {name}: {target} ({target.stat().st_size // 1024} kB)")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "balance"
    if what == "balance":
        balance()
    elif what == "preview":
        preview(wanted(sys.argv[2:]))
    elif what == "refine":
        refine(wanted(sys.argv[2:]))
    elif what == "wait":
        wait()
    elif what == "status":
        status()
    elif what == "fetch":
        fetch()
    else:
        raise SystemExit(__doc__)
