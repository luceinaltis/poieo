"""What a ``poieo.yaml`` says, and how a folder comes to have one.

Discovery -- walking upward for the marker, the way git finds ``.git`` --
lives in :mod:`poieo.layout`, beside the rest of the answer to "where does
this project keep things"; it is re-exported here because that is where its
callers have always found it. Commands use it to fill flags the user left
silent: the flag always wins, and discovery only fills silence, so a folder
with no marker behaves exactly as it always has.

**A project is the paths its marker names, and nothing more.** What a command
wants from discovery is where the store is and which binding to default to;
it does not want the flows read, the task folder expanded, or the memory
cross-checked. The daemon wants all of that, and :class:`DaemonConfig`
extends this with it -- one schema, read to the depth the caller needs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .errors import SpecError, describe_invalid
from .graph import load_document

# Where a project keeps things is one question with one answer, and it lives
# in layout.py. What is re-exported here is what already had callers.
from .layout import MARKER, Layout, find_project_file

__all__ = [
    "MARKER",
    "ProjectSpec",
    "detect_default_binding",
    "find_project",
    "find_project_file",
    "init_project",
    "load_project",
]


class ProjectSpec(BaseModel):
    """The shared defaults a ``poieo.yaml`` declares: where things live.

    Deliberately shallow. ``flows`` is accepted but left as written -- parsing
    one needs a trigger, a binding and a graph, and a command asking "where is
    the store" has no business loading any of them. ``DaemonConfig`` narrows
    the field when something actually intends to run them.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    # Where run logs are written.
    store: str = ".poieo"
    # Default binding for flows -- and for tasks, and for `poieo run`.
    binding: str | None = None
    # A folder of task files; each one expands into a flow. See poieo.task.
    tasks: str | None = None
    # How often the project sits down to learn from its run records
    # (a duration: "1d"). Absent means never. Validated by the daemon, which
    # is the only thing that acts on it.
    learn: str | None = None
    # Read to the depth the caller needs: see the class docstring.
    flows: list[Any] = Field(default_factory=list)

    source_path: Path | None = Field(default=None, exclude=True)

    # -- path helpers --------------------------------------------------------
    @property
    def base_dir(self) -> Path:
        return self.source_path.parent if self.source_path else Path.cwd()

    def resolve_path(self, relative: str) -> Path:
        """Resolve a path relative to the config file, not the cwd."""
        path = Path(relative)
        return path if path.is_absolute() else (self.base_dir / path)

    def store_path(self) -> Path:
        return self.resolve_path(self.store)

    def layout(self) -> Layout:
        """Where this project keeps things.

        ``store:`` counts only when the document actually named it: a default
        that happened to match is not a decision, and treating it as one would
        make every silent project look like it had asked for something.
        """
        return Layout(
            root=self.base_dir,
            runs_override=self.store_path() if "store" in self.model_fields_set else None,
        )


def load_project(path: str | Path) -> ProjectSpec:
    """Parse a ``poieo.yaml`` for its paths. Flows are not read."""
    path = Path(path)
    data = load_document(path)
    try:
        project = ProjectSpec.model_validate(data)
    except Exception as exc:
        raise SpecError(
            f"{path}: invalid project file: "
            f"{describe_invalid(exc, tuple(ProjectSpec.model_fields))}"
        ) from exc
    project.source_path = path.resolve()
    return project


def find_project(start: str | Path | None = None) -> ProjectSpec | None:
    """The nearest project's paths, or None outside one.

    A marker that cannot be parsed still raises -- a broken project file
    should fail loudly wherever it is consulted. What no longer fails here is
    a problem *inside* something the marker points at: a card with a typo is
    the daemon's business, and used to break an unrelated `poieo run`.
    """
    marker = find_project_file(start)
    return load_project(marker) if marker else None


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
  A card's identity is its filename.
- `memory/shortterm/<card>.md` -- that task's journal: append a line to
  leave it a note; never rewrite its history. It lives here rather than
  beside the card so that `tasks/` holds definitions and nothing else.
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
    # The full load, flows and cards included -- init is the one caller that
    # wants that depth, and it is the only reason this module knows the
    # daemon exists. Late, because DaemonConfig extends ProjectSpec above.
    from .daemon.config import load_config

    load_config(root / "poieo.yaml")
    return report, reason
