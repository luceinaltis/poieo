"""Ask Meshy for a model, then download it. Run this yourself, not Claude.

The key is read from the repo's .env (gitignored), used in one Authorization
header, and never printed or written anywhere.

    python meshy.py balance                 # spends nothing
    python meshy.py preview smith-striking  # cheap, untextured shape
    python meshy.py status                  # how far along
    python meshy.py refine smith-striking   # textures, once the shape is right
    python meshy.py fetch hammer            # download it; no name means all of them

Names: smith, smith-kr, anvil, forge, props, hammer
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
    # The second smith, and the one the room is meant to keep. Two things are
    # deliberate and both were learned the hard way:
    #
    # - His hands are empty. Asking the generator for a tool welds it into the
    #   fist as one mesh with one material, and what came back last time was a
    #   13 cm lump with no handle that could not be hidden at run time. The
    #   hammer is its own prop now and the skin puts it in his fist, so there
    #   is no reason to ask for one here.
    # - His eyes are asked for narrow and lidded. The generator's default is a
    #   full circle of white with a small dark centre, which reads as startled
    #   no matter what the body is doing; tools/hood_eyes.py can paint a lid on
    #   afterwards, but it is better not to need it.
    "smith-kr": (
        "A-pose reference model of a Korean master blacksmith, Joseon period. "
        "The arms matter more than anything else: both arms perfectly straight "
        "from shoulder to fingertip, held away from the torso at forty degrees "
        "so there is a wide open gap of empty space between each arm and the "
        "side of the body, like the letter A. Arms not touching the body, not "
        "bent, not raised to shoulder height. Hands empty, no tools. Standing "
        "still, feet apart, facing forward. An older craftsman, weathered and "
        "dignified: black hair in a topknot under a dark headband, short grey "
        "beard, narrow deep-set eyes, heavy brows. A "
        "scorched leather apron over an undyed jeogori with sleeves rolled to "
        "the elbow, indigo trousers tied at the ankle, straw sandals. Stylized "
        "game character, clean topology, PBR textures."
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
    # The hammer the smith holds is welded into his fist by the generator, and
    # it came out a 13 cm lump with no handle -- measurable: 659 vertices in a
    # 0.15-unit box sitting on the wrist, on a figure 1.80 units tall. A prop
    # asked for on its own comes back as its own mesh, at its own scale, and
    # can be judged before it is put in anyone's hand. Downloaded like the
    # anvil and the forge; unprop.py cuts the lump out to make room for it.
    "hammer": (
        "A blacksmith's forging hammer, and nothing else. A heavy squared steel "
        "head with one flat striking face and one slightly tapered peen, mounted "
        "across the end of a straight wooden handle. The handle is about four "
        "times as long as the head is wide and runs in one straight line. Dark "
        "pitted steel, worn oiled ash wood, a single visible wedge in the eye. "
        "Laid out straight along one axis, not held, no hand, no anvil, no "
        "stand, no other tools. Game-ready prop, clean topology, PBR textures."
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
    # A fresh preview retires the refine that was made from the last one.
    # Without this, `fetch` prefers a refine that belongs to a shape nobody
    # asked for any more, and two generations get quietly mixed -- which is
    # exactly what happened the third time this smith was regenerated.
    if stage == "preview":
        state[name] = {}
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


def fetch(names=None):
    """Download the finished models. Named ones only, if any are named.

    Without a filter this re-downloads every subject ever queued -- forty
    megabytes to collect one new prop, over the top of files later steps have
    already been run against.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    for name, stages in tasks().items():
        if names and name not in names:
            continue
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
        fetch(wanted(sys.argv[2:]) if len(sys.argv) > 2 else None)
    else:
        raise SystemExit(__doc__)
