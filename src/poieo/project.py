"""What a ``poieo.yaml`` says, and how a folder comes to have one.

**A project is the paths its marker names, and nothing more.** Commands use
discovery (re-exported from :mod:`poieo.layout`) to fill flags the user left
silent -- the flag always wins, and discovery only fills silence.

A command asking "where is the store" does not want the flows read, the task
folder expanded or the memory cross-checked. The daemon wants all of that, and
:class:`DaemonConfig` extends this with it: one schema, read to the depth the
caller needs.

Design: docs/storage.md
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

    Deliberately shallow: ``flows`` is accepted but left as written, and
    ``DaemonConfig`` narrows the field when something intends to run them.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    # Where a run's events and its result are written. Moves the run history
    # and nothing else: the memory and the working copies stay with the project.
    store: str = "runs"
    # Default binding for flows -- and for tasks, and for `poieo run`.
    binding: str | None = None
    # A folder of task files; each one expands into a flow. See poieo.task.
    tasks: str | None = None
    # How often the project learns from its run records ("1d"); absent means
    # never. Validated by the daemon, the only thing that acts on it.
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

        ``store:`` counts only when the document actually named it -- a default
        that happened to match is not a decision.
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

    A marker that cannot be parsed raises; a problem *inside* what the marker
    points at does not -- a card with a typo is the daemon's business, not an
    unrelated `poieo run`'s.
    """
    marker = find_project_file(start)
    return load_project(marker) if marker else None


# -- poieo init ---------------------------------------------------------------
#
# Detection happens here, once, and its answer is written into ordinary files.
# Run time never probes the machine again.

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
# This file's folder is the project -- everything below resolves from here.
version: 1
store: runs                       # where a run's events and result go
binding: models/default.yaml      # which model serves each role, by default
tasks: tasks/                     # the cards, and the graphs they name
"""

_CONSTITUTION = """\
<!--
This page is read whole by every run of every task in this project. Before
adding a line, ask: does it apply to every task? is violating it expensive?
would lookup fail to bring it up when needed? is it invisible in the code?
Four yeses earn the page; anything less belongs in memory/longterm/facts/.

Delete this file, and its folder, if the project keeps no long memory. The
folder is the whole opt-in -- nothing else turns the feature on.
-->
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

This folder is the project. Every path below hangs off it, and one folder
answers one question.

- `poieo.yaml` -- the marker: store, default binding, tasks folder.
- `models/*.yaml` -- **which model** serves each role.
  `models/mock.yaml` answers from a script: free, offline.
- `tasks/` -- **what to do**. `<card>.yaml` is one standing task (`name`,
  `folder`, `prompt`; optionally `every`/`at`, `binding`, `enabled`,
  `tools`); a card's identity is its filename. `<card>.graph.yaml` is a
  graph, which a card may name instead of carrying a prompt.
- `memory/` -- **what the project remembers**.
  - `shortterm/<card>.md` -- that task's journal. Append a line to leave it
    a note; never rewrite its history.
  - `longterm/constitution.md` -- read whole before every run of every task.
  - `longterm/facts/*.md` -- one file per thing learned. This folder
    existing is what makes the project keep a long memory at all.
  - `cache/` -- rebuilt from the above. Delete it and lose nothing.
- `runs/` -- **what happened**. `events/<id>.jsonl` as it happened,
  `results/<id>.json` when it was over. Read freely, never edit.
- `worktrees/` -- each flow's private copy of the repository it works on.

`memory/cache/`, `runs/` and `worktrees/` are gitignored; everything else
is yours and belongs in git.

## The loop

Edit a file, then prove it loads -- a typo must fail now, not at 3am:

    poieo validate tasks/<card>.yaml   # after editing a card or a graph
    poieo check -b models/<name>.yaml  # after editing a binding (probes it)
    poieo flows                        # after editing poieo.yaml (loads all)

Try a card once, without the daemon:

    poieo run tasks/<card>.yaml                        # --json for structure
    poieo run tasks/<card>.yaml -b models/mock.yaml    # spends nothing

See what happened, and what the project has in mind:

    poieo runs list
    poieo runs show <run_id>
    poieo memory                       # the page, the counts, what to look at
    poieo memory tasks/<card>.yaml     # the exact block its next run gets

## What is not yours

Starting `poieo daemon`, and accepting or discarding a night's work on the
web board, belong to the person. Add and edit cards; leave the daemon,
`runs/` and `worktrees/` alone.
"""

# Claude Code reads CLAUDE.md; the import points it at the same page.
_CLAUDE_MD = "@AGENTS.md\n"

# Three ordinary names rather than one hidden folder, so a project living
# inside somebody else's repository takes three lines and not a rename.
_GITIGNORE_LINES = ("memory/cache/", "runs/", "worktrees/")


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
        ("models/default.yaml", default_body),
        ("models/mock.yaml", _MOCK_BINDING),
        ("tasks/hello.yaml", _HELLO_CARD),
        # An empty page, so the memory is a folder you can see rather than a
        # feature you have to be told about. Nothing switches on: it is all
        # comments, and those are stripped before any prompt.
        ("memory/longterm/constitution.md", _CONSTITUTION),
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
    missing = [line for line in _GITIGNORE_LINES if line not in existing.splitlines()]
    if not missing:
        report.append(("kept", ".gitignore"))
    else:
        joined = existing + ("" if existing.endswith("\n") or not existing else "\n")
        gitignore.write_text(
            joined + "".join(f"{line}\n" for line in missing), encoding="utf-8"
        )
        report.append(("wrote", ".gitignore"))

    # A generated project that cannot load is an init bug, caught here and not
    # at 3am -- and a kept, hand-edited poieo.yaml is re-checked too. The one
    # caller that wants the full depth, and the only reason this module knows
    # the daemon exists. Late, because DaemonConfig extends ProjectSpec above.
    from .daemon.config import load_config

    load_config(root / "poieo.yaml")
    return report, reason
