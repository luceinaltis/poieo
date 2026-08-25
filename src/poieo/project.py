"""A folder is a project when it holds a ``poieo.yaml``.

Discovery walks from a starting directory upward and stops at the first
marker, the way git finds ``.git``. Commands use it to fill flags the user
left silent -- the flag always wins, and discovery only fills silence, so a
folder with no marker behaves exactly as it always has.
"""

from __future__ import annotations

import os
from pathlib import Path

from .daemon.config import DaemonConfig, load_config

MARKER = "poieo.yaml"


def find_project_file(start: str | Path | None = None) -> Path | None:
    """The nearest ``poieo.yaml`` at or above ``start`` (default: cwd)."""
    here = Path(start) if start is not None else Path.cwd()
    here = here.resolve()
    for candidate in (here, *here.parents):
        marker = candidate / MARKER
        if marker.is_file():
            return marker
    return None


def find_project(start: str | Path | None = None) -> DaemonConfig | None:
    """The loaded config of the nearest project, or None outside one.

    A marker that fails to load raises the same ``SpecError`` an explicit
    ``poieo daemon poieo.yaml`` would -- a broken project file should fail
    loudly wherever it is consulted, not be silently skipped over.
    """
    marker = find_project_file(start)
    return load_config(marker) if marker else None


# -- poieo init ---------------------------------------------------------------
#
# Detection happens here, once, and its answer is written into ordinary files.
# Nothing at run time ever probes the machine again, so no night's run can
# silently pick a different model than the one written down.

_CLAUDE_BINDING = """\
# Physical layer: the Claude API.
# Credentials resolve from the environment (ANTHROPIC_API_KEY or `ant auth login`).
name: claude
version: 1

providers:
  claude:
    type: anthropic

default:
  provider: claude
  model: claude-opus-5
  params:
    max_tokens: 16000
    effort: high                  # low | medium | high | xhigh | max
    thinking: auto                # adaptive where the model supports it
"""

_OLLAMA_BINDING = """\
# Physical layer: the Ollama server on this machine.
name: local
version: 1

providers:
  ollama:
    type: ollama
    base_url: http://localhost:11434

default:
  provider: ollama
  model: {model}
  params:
    max_tokens: 2048
"""

_MOCK_BINDING = """\
# Physical layer that spends nothing: scripted replies, for trying the wiring.
name: mock
version: 1

providers:
  fake:
    type: mock
    options:
      responses:
        "*": "A mock answer -- the wiring works. Swap poieo.yaml's binding for a real one."

default:
  provider: fake
  model: mock-model
"""

_MARKER_BODY = """\
# The project: which flows run, on what trigger, against which binding.
# Paths resolve relative to this file.
version: 1
store: .poieo
binding: bindings/default.yaml
tasks: tasks/
"""

_HELLO_CARD = """\
# A sample card: a name, a folder, and a prompt. Delete freely.
# `enabled: false` keeps the daemon's hands off it; run it once by hand:
#   poieo run tasks/hello.yaml
name: hello poieo
folder: .
enabled: false
prompt: |
  Look around this folder and write one sentence about what you see.
"""

_AGENTS_MD = """\
# Operating this poieo project

This folder is a poieo project: LLM workflows kept running by a resident
daemon. A coding agent manages it by editing files and running the commands
below -- there is no API to learn beyond this page.

## The files

- `poieo.yaml` -- the project: store, default binding, tasks folder.
- `tasks/*.yaml` -- one card per standing task: `name`, `folder`, `prompt`
  (optionally `every`/`at` for schedule, `binding`, `enabled`, `tools`).
  A card's identity is its filename. `tasks/<card>.md` is that task's
  journal: append a line to leave it a note; never rewrite its history.
- `bindings/*.yaml` -- which physical model serves each role.
  `bindings/mock.yaml` answers from a script: free, offline.
- `.poieo/` -- derived state (run logs, episodes). Read freely, never edit.

## The loop

Edit a file, then prove it loads -- a typo must fail now, not at 3am:

    poieo validate tasks/<card>.yaml     # after editing a card or a graph
    poieo check -b bindings/<name>.yaml  # after editing a binding (probes it)
    poieo flows                          # after editing poieo.yaml (loads all)

Try a card once, without the daemon:

    poieo run tasks/<card>.yaml                          # --json for structure
    poieo run tasks/<card>.yaml -b bindings/mock.yaml    # spends nothing

See what happened:

    poieo runs list
    poieo runs show <run_id>

## What is not yours

Starting `poieo daemon`, and accepting or discarding a night's work on the
web board, belong to the person. Add and edit cards; leave the daemon and
`.poieo/` alone.
"""

# Claude Code reads CLAUDE.md; the import points it at the same page.
_CLAUDE_MD = "@AGENTS.md\n"

_GITIGNORE_LINE = ".poieo/"


def _ollama_models() -> list[str]:
    """What the local Ollama has installed; [] when it is not there.

    One probe, one second: init must feel instant on a machine with nothing.
    """
    import httpx

    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=1.0)
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", []) if m.get("name")]
    except Exception:
        return []


def detect_default_binding() -> tuple[str, str]:
    """(binding file body, why it was chosen) -- the machine's answer, once."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _CLAUDE_BINDING, "claude -- ANTHROPIC_API_KEY is set"
    models = _ollama_models()
    if models:
        return (
            _OLLAMA_BINDING.format(model=models[0]),
            f"ollama -- answering on localhost:11434 with {models[0]}",
        )
    return _MOCK_BINDING, "mock -- no key, no local server; runs free, answers from a script"


def init_project(root: Path) -> tuple[list[tuple[str, str]], str]:
    """Write a working project into ``root``; never touch an existing file.

    Returns ``(report, reason)``: one ``(action, relative path)`` pair per
    file, action ``wrote`` or ``kept``, and the sentence saying why the
    default binding is what it is.
    """
    default_body, reason = detect_default_binding()
    files = [
        ("poieo.yaml", _MARKER_BODY),
        ("bindings/default.yaml", default_body),
        ("bindings/mock.yaml", _MOCK_BINDING),
        ("tasks/hello.yaml", _HELLO_CARD),
        ("AGENTS.md", _AGENTS_MD),
        ("CLAUDE.md", _CLAUDE_MD),
    ]
    report: list[tuple[str, str]] = []
    for relative, body in files:
        path = root / relative
        if path.exists():
            report.append(("kept", relative))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        report.append(("wrote", relative))

    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if _GITIGNORE_LINE in existing.splitlines():
        report.append(("kept", ".gitignore"))
    else:
        joined = existing + ("" if existing.endswith("\n") or not existing else "\n")
        gitignore.write_text(joined + _GITIGNORE_LINE + "\n", encoding="utf-8")
        report.append(("wrote", ".gitignore"))

    # A generated project that cannot load is an init bug, caught here and
    # not at 3am. Also re-checks a kept, hand-edited poieo.yaml still parses.
    load_config(root / "poieo.yaml")
    return report, reason
