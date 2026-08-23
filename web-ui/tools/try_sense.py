"""Film the swing in both directions and lay them out to be compared."""

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

WEB = Path("C:/Users/82109/Desktop/poieo/.claude/worktrees/web-frontend")
SKIN = WEB / "web-ui/src/skins/atelier/index.ts"
DEMO = Path("C:/Users/82109/poieo-demo")


def run(*args, **kwargs):
    return subprocess.run(args, capture_output=True, **kwargs)


def apply(sense):
    lines = []
    for line in SKIN.read_text(encoding="utf-8").splitlines():
        if line.startswith("const ARM_SENSE"):
            line = f"const ARM_SENSE = {sense}"
        lines.append(line)
    SKIN.write_text("\n".join(lines) + "\n", encoding="utf-8")


def restart():
    run("powershell", "-NoProfile", "-Command",
        "Get-NetTCPConnection -LocalPort 8484 -State Listen -ErrorAction SilentlyContinue"
        " | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }")
    subprocess.Popen(
        ["python", "main.py", "daemon", str(DEMO / "live.yaml")],
        cwd=WEB, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    run("curl", "-s", "--retry", "40", "--retry-delay", "1", "--retry-connrefused",
        "--max-time", "80", "http://127.0.0.1:8484/api/flows", shell=True)


def film(label):
    for _ in range(3):
        run("node", "film.js", f"{label}.png", "6", "9", cwd=DEMO, shell=True)
        if (DEMO / "frames.json").exists():
            break
    if not (DEMO / "frames.json").exists():
        return None
    info = json.loads((DEMO / "frames.json").read_text())
    frames = [Image.open(DEMO / f"frame-{i}.png") for i in range(info["count"])]
    strip = Image.new("RGB", (sum(f.width for f in frames), frames[0].height))
    x = 0
    for frame in frames:
        strip.paste(frame, (x, 0))
        x += frame.width
    (DEMO / "frames.json").unlink()
    return strip


if __name__ == "__main__":
    strips = []
    for sense in (1, -1):
        apply(sense)
        run("npm", "run", "build", "--workspace", "web-ui", cwd=WEB, shell=True)
        restart()
        strip = film(f"sense{sense}")
        if strip is None:
            print(f"  sense {sense}: no film")
            continue
        ImageDraw.Draw(strip).text((8, 8), f"sense {sense}", fill=(255, 200, 120))
        strips.append(strip)
        print(f"  sense {sense}: filmed")

    sheet = Image.new("RGB", (max(s.width for s in strips), sum(s.height for s in strips)))
    y = 0
    for strip in strips:
        sheet.paste(strip, (0, y))
        y += strip.height
    sheet.save(DEMO / "sense.png")
    print("  wrote sense.png")
