"""Ask Meshy to animate the rigged smith, then download the result.

Hand-tuned joint angles never stopped looking hand-tuned. Meshy's animation
library retargets motion-captured clips onto a rigged character, and it has
exactly the two this room needs: Heavy_Hammer_Swing for a flow that is
working, Idle for one that is not.

    python animate.py rigs             # list rigging tasks, to pick the right model
    python animate.py start <rig_id>   # queue both clips against that rig
    python animate.py wait
    python animate.py fetch            # download as models/anim-<name>.glb
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import meshy  # noqa: E402

STATE = Path("C:/Users/82109/poieo-demo/anim-tasks.json")
OUT = Path("C:/Users/82109/poieo-demo/models")

# From the animation library reference; the names are Meshy's.
CLIPS = {"swing": 128, "idle": 0}


def rigs() -> None:
    """Every rigging task on the account, newest first, with what it rigged."""
    tasks = meshy.call("/v1/rigging?page_size=20")
    rows = tasks if isinstance(tasks, list) else tasks.get("result", tasks.get("data", []))
    for task in rows:
        print(f"  {task.get('id')}  {task.get('status'):9}  input {task.get('input_task_id')}")


def start(rig_id: str) -> None:
    state = {}
    for name, action in CLIPS.items():
        result = meshy.call(
            "/v1/animations", {"rig_task_id": rig_id, "action_id": action}
        )
        state[name] = result["result"]
        print(f"  {name}: queued")
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def tasks() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8"))


def wait(minutes=15) -> None:
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        pending = False
        for name, task_id in tasks().items():
            task = meshy.call(f"/v1/animations/{task_id}")
            state = task.get("status")
            print(f"  {name}: {state} {task.get('progress', 0)}%", flush=True)
            pending = pending or state in ("PENDING", "IN_PROGRESS")
        if not pending:
            return
        time.sleep(15)
    print("  still running")


def fetch() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, task_id in tasks().items():
        task = meshy.call(f"/v1/animations/{task_id}")
        if task.get("status") != "SUCCEEDED":
            print(f"  {name}: {task.get('status')} {task.get('progress', 0)}%")
            continue
        payload = task.get("result") if isinstance(task.get("result"), dict) else task
        url = next(
            (u for k, u in payload.items()
             if isinstance(u, str) and "glb" in k and u.startswith("http")),
            None,
        )
        if not url:
            print(f"  {name}: succeeded but no glb; fields {list(payload)}")
            continue
        target = OUT / f"anim-{name}.glb"
        with urllib.request.urlopen(url, timeout=300) as response:
            target.write_bytes(response.read())
        print(f"  {name}: {target.name} ({target.stat().st_size // 1024} kB)")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "rigs"
    if what == "rigs":
        rigs()
    elif what == "start":
        start(sys.argv[2])
    elif what == "wait":
        wait()
    elif what == "fetch":
        fetch()
    else:
        raise SystemExit(__doc__)
