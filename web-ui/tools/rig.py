"""Rig a generated character, then download the skinned model.

Rigging gives the mesh a skeleton. Meshy's own animations are walking and
running, which are no use at an anvil -- but with bones in place the arm can
be swung from code, on the timing the flat skin already uses.

    python rig.py start   # queue rigging for smith-striking
    python rig.py wait
    python rig.py fetch
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import meshy  # noqa: E402

STATE = Path("C:/Users/82109/poieo-demo/rig-task.json")
OUT = Path("C:/Users/82109/poieo-demo/models")


def remember(task_id: str) -> None:
    STATE.write_text(json.dumps({"task": task_id}), encoding="utf-8")


def task_id() -> str:
    if not STATE.exists():
        raise SystemExit("nothing rigged yet; run: python rig.py start")
    return json.loads(STATE.read_text(encoding="utf-8"))["task"]


def start() -> None:
    source = meshy.tasks()["smith"]["refine"]
    result = meshy.call("/v1/rigging", {"input_task_id": source, "height_meters": 1.8})
    remember(result["result"])
    print("  rigging queued")


def wait(minutes=15) -> None:
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        task = meshy.call(f"/v1/rigging/{task_id()}")
        state = task.get("status")
        print(f"  rigging: {state} {task.get('progress', 0)}%", flush=True)
        if state not in ("PENDING", "IN_PROGRESS"):
            return
        time.sleep(20)
    print("  still running")


def fetch() -> None:
    task = meshy.call(f"/v1/rigging/{task_id()}")
    if task.get("status") != "SUCCEEDED":
        print(f"  {task.get('status')} {task.get('progress', 0)}%")
        print("  keys:", list(task))
        return

    OUT.mkdir(parents=True, exist_ok=True)
    # Downloads are signed, so the urls carry a query string: match on the
    # field name, not the extension.
    payload = task.get("result") if isinstance(task.get("result"), dict) else task
    urls = {
        name: url for name, url in payload.items() if isinstance(url, str) and "glb" in name and url.startswith("http")
    }
    if not urls:
        print("  no glb in response; fields:", list(payload))
        return

    for name, url in urls.items():
        target = OUT / f"{name.replace('_url', '').replace('rigged_character', 'rigged')}.glb"
        with urllib.request.urlopen(url, timeout=300) as response:
            target.write_bytes(response.read())
        print(f"  {target.name}: {target.stat().st_size // 1024} kB")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "wait"
    {"start": start, "wait": wait, "fetch": fetch}.get(what, lambda: print(__doc__))()
