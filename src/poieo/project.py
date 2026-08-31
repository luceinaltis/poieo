"""What a ``poieo.yaml`` says, and how a folder comes to have one.

**A project is the paths its marker names, and nothing more.** Commands use
discovery (re-exported from :mod:`poieo.layout`) to fill flags the user left
silent -- the flag always wins, and discovery only fills silence.

A command asking "where is the store" does not want the cards read, the task
folder expanded or the memory cross-checked. The daemon wants all of that, and
:class:`DaemonConfig` extends this with it: one schema, read to the depth the
caller needs.

Design: docs/storage.md
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Sequence

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .detect import CANDIDATES, Engine
from .graph import load_spec

# Where a project keeps things is one question with one answer, and it lives
# in layout.py. What is re-exported here is what already had callers.
from .layout import MARKER, Layout, find_project_file

__all__ = [
    "MARKER",
    "ProjectSpec",
    "binding_document",
    "find_project",
    "find_project_file",
    "init_project",
    "marker_body",
    "load_project",
    "nothing_found",
]


class SpendSpec(BaseModel):
    """A ceiling on what this project may spend, as a rate.

    A rate rather than a total, because a daemon has no end: "no more than a
    dollar an hour" is a sentence somebody can mean, and "no more than twenty
    dollars, ever" is one they would have to keep resetting.

    The exposure is not one run -- forty turns measured here cost two and a
    half cents -- it is a board firing all night. A handoff loop early in this
    project burnt $0.19 in ten minutes, which left alone is $27 a day.
    """

    model_config = ConfigDict(extra="forbid")

    # In whatever currency the endpoint bills in. poieo does not know one
    # currency from another and does not need to: it adds up what it was told
    # and compares it to what it was given.
    limit: float = Field(gt=0)
    # How far back to look. A duration the way every other one here is spelled.
    over: str = "1h"


class ProjectSpec(BaseModel):
    """The shared defaults a ``poieo.yaml`` declares: where things live.

    Deliberately shallow: it says where things are, and ``DaemonConfig`` is
    what reads the cards it points at.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    version: int = 1
    # What this project is called on a board. Optional because the folder name
    # is right nearly always -- it is only needed when it is not, and the case
    # that needs it is two worktrees of one repository: two folders with the
    # same name, two daemons, two boards that otherwise look identical.
    name: str | None = None
    # Where a run's events and its result are written. Moves the run history
    # and nothing else: the memory and the working copies stay with the project.
    store: str = "runs"
    # What this project may spend per unit time, if anybody said. `None` means
    # nobody has, and nothing is enforced -- which is the right default for a
    # local model that costs nothing and the honest one for an endpoint whose
    # charges poieo cannot see.
    spend: SpendSpec | None = None
    # Default binding for every task here, and for `poieo run`.
    binding: str | None = None
    # The folder of cards. Named for what is in it, while the document key
    # stays `tasks:` -- that is the word a reader of the file wants.
    cards: str | None = Field(default=None, alias="tasks")
    # How often the project learns from its run records ("1d"); absent means
    # never. Validated by the daemon, the only thing that acts on it.
    learn: str | None = None

    source_path: Path | None = Field(default=None, exclude=True)

    @property
    def display_name(self) -> str:
        """What to call this project, which is never nothing.

        A board with a blank title is worse than one with a dull title, so a
        `name:` that is empty or only spaces falls back the same as an absent
        one rather than being taken at its word.
        """
        return (self.name or "").strip() or self.base_dir.name

    # -- path helpers --------------------------------------------------------
    @property
    def base_dir(self) -> Path:
        return self.source_path.parent if self.source_path else Path.cwd()

    def resolve_path(self, relative: str) -> Path:
        """Resolve a path relative to the config file, not the cwd.

        `~` expands first, as it does in a card (`CardSpec.resolve`) and in the
        route that writes one. This file was the one that did not, so
        `store: ~/runs` made a directory *called* `~` inside the project and
        filed the run history in it -- somewhere nobody looks, with the home
        folder they named left empty.

        **A home that cannot be found leaves the path alone.**
        `Path.expanduser` raises `RuntimeError` exactly where `os.path`'s
        version hands the string back untouched: `~someone` naming nobody, and
        a container with no `$HOME` and no passwd entry for the uid it runs as,
        where even `~/runs` has nothing to expand against. Nothing catches a
        `RuntimeError` on the way out of a config load -- `_guarded` answers for
        `PoieoError` -- so it would reach the reader as a traceback. A folder
        with a `~` in its name is the wrong answer; a traceback is not an answer.
        """
        path = Path(relative)
        try:
            path = path.expanduser()
        except RuntimeError:
            pass
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
    """Parse a ``poieo.yaml`` for its paths. Tasks are not read."""
    return load_spec(path, ProjectSpec, "project file", resolve=True)


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
# Detection happens once, in detect.py, and its answer is written into ordinary
# files. Run time never probes the machine again.

# The generation settings each backend is worth starting from. A role inherits
# them through `default:`, and overrides what it does not want.
_PARAMS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "anthropic": (
        "max_tokens: 16000",
        "effort: high                # low | medium | high | xhigh | max",
        "thinking: auto              # adaptive where the model supports it",
    ),
    "ollama": ("max_tokens: 2048",),
    "openai_compatible": ("max_tokens: 2048",),
}

MOCK_BINDING = """\
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
# The project: where runs land, which models answer, and where the tasks are.
# This file's folder is the project -- everything below resolves from here.
version: 1
{name} # what a board calls this; yours to change
store: runs                       # where a run's events and result go
binding: models/default.yaml      # which model serves each role, by default
tasks: tasks/                     # the cards, and the graphs they name
"""


def _name_line(name: str) -> str:
    """``name: ...``, quoted exactly as much as the value needs.

    A folder can be called ``notes: 2026`` or ``#1``, and hand-writing the
    quoting rules for that is how a generated project comes out unparseable --
    in the user's own folder, on their first command, before they have written
    anything. The emitter knows the rules, so it writes the line.

    ``allow_unicode`` because a project named in Korean should read as Korean
    in the file rather than as a row of escapes. Padded to the column the
    other comments start at; a name long enough to pass it still gets its
    single space.
    """
    line = yaml.safe_dump({"name": name}, allow_unicode=True, default_flow_style=False)
    return f"{line.strip():<33}"


def marker_body(name: str) -> str:
    """The ``poieo.yaml`` a new project starts with, named.

    Substituted rather than ``format``ed: these templates are YAML, and YAML
    has a flow mapping spelled with braces. The day one appears in here,
    ``format`` raises and this is the last place anyone would look.
    """
    return _MARKER_BODY.replace("{name}", _name_line(name))


_CONSTITUTION = """\
<!--
This page is read whole by every run of every task in this project. Before
adding a line, ask: does it apply to every task? is violating it expensive?
would lookup fail to bring it up when needed? is it invisible in the code?
Four yeses earn the page; anything less belongs in a learned entry.

Delete memory/longterm.sqlite3 if the project keeps no long memory. That
file is the whole opt-in -- nothing else turns the feature on.
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
  - `longterm.sqlite3` -- the page every run reads, everything the project
    has learned, and the history of every change to either. This file
    existing is what makes the project keep a long memory at all.
    `poieo memory` reads it; the board searches and edits it.
  - `cache/` -- rebuilt from the above. Delete it and lose nothing.
- `runs/` -- **what happened**. `events/<id>.jsonl` as it happened,
  `results/<id>.json` when it was over. Read freely, never edit.
- `worktrees/` -- each task's private copy of the repository it works on.

`memory/cache/`, `runs/` and `worktrees/` are gitignored; everything else
is yours and belongs in git.

## The loop

Edit a file, then prove it loads -- a typo must fail now, not at 3am:

    poieo validate tasks/<card>.yaml   # after editing a card or a graph
    poieo check -b models/<name>.yaml  # after editing a binding (probes it)
    poieo tasks                        # after editing poieo.yaml (loads all)

Before naming a model in a binding, read what is actually there -- a model
named from memory fails at 3am, not now:

    poieo config                       # what this project is bound to
    poieo config models                # what each endpoint serves right now
    poieo config use <provider/model>  # change it (--role NAME for one role)
    poieo config add                   # declare an engine installed since init

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


def _catalogue(engines: Sequence[Engine]) -> list[str]:
    """Every model each engine reported, as comment lines.

    A comment, not data, because it is a **snapshot**: detection never runs
    again, so a list the file presented as fact would quietly go stale the
    first time a model was pulled. What a role may name is whatever the engine
    actually serves; this is here so naming one is reading rather than
    remembering.
    """
    gutter = max(len(engine.key) for engine in engines)
    lines = []
    for engine in engines:
        # Neither flag is optional: a real Ollama tag is long and full of
        # hyphens (`hf.co/empero-ai/Qwen3.8-9B-Distill-GGUF:Q5_K_M`), and this
        # list exists to be copied from. A name broken across two lines is
        # worse than no name -- so ids wrap between, never inside.
        wrapped = textwrap.wrap(
            "  ".join(engine.models),
            width=68 - gutter,
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""]
        lines.append(f"#   {engine.key:<{gutter}}  {wrapped[0]}")
        lines += [f"#   {'':<{gutter}}  {more}" for more in wrapped[1:]]
    return lines


def _worked_example(engines: Sequence[Engine], chosen: tuple[str, str]) -> tuple[str, str]:
    """A (engine, model) pair to show the `roles:` block with.

    Anything but ``chosen``: an example that repeats the default demonstrates
    nothing, and the whole point of the block is that a role can go somewhere
    else. A different engine first, since that is the harder half to guess.
    """
    for engine in engines:
        if engine.key != chosen[0]:
            return engine.key, engine.models[0]
    for engine in engines:
        for model in engine.models:
            if model != chosen[1]:
                return engine.key, model
    return chosen  # one engine, one model: there is nothing else to show


def binding_document(engines: Sequence[Engine], chosen: tuple[str, str]) -> str:
    """The binding file for a machine with these engines on it.

    **Every** engine found is declared, not only the one serving `default:`.
    A role exists so a graph can send its cheap step somewhere cheap, and that
    is unreachable if the file names one endpoint -- so the pool is written
    down once, here, and picking from it later is an edit rather than another
    round of detection.

    ``chosen`` is ``(engine key, model id)``: what an unnamed role gets.
    """
    key, model = chosen
    engine = next(e for e in engines if e.key == key)
    example_key, example_model = _worked_example(engines, chosen)

    lines = [
        "# Physical layer: every engine this machine answered on when",
        "# `poieo init` looked. A graph names a role; a role names a model here.",
        "#",
        "# Detection does not run again -- edit this file freely.",
        "name: default",
        "version: 1",
        "",
        "providers:",
    ]
    for found in engines:
        lines.append(f"  {found.key}:")
        lines.append(f"    type: {found.type}")
        if found.base_url is not None:
            lines.append(f"    base_url: {found.base_url}")
    lines += [
        "",
        "default:",
        f"  provider: {key}",
        f'  model: "{model}"',
        "  params:",
    ]
    lines += [f"    {param}" for param in _PARAMS_BY_TYPE.get(engine.type, ())]
    lines += [
        "",
        "# Give a role its own model, and a graph that names that role uses it:",
        "#",
        "#   roles:",
        "#     classifier:",
        f"#       provider: {example_key}",
        f'#       model: "{example_model}"',
        "#",
        "# What each engine had when this file was written:",
        *_catalogue(engines),
    ]
    return "\n".join(lines) + "\n"


def nothing_found() -> str:
    """Why init is refusing, and the two ways forward.

    One wording, here, because the sentence a user reads is a thing with one
    wording and two copies are two chances for that to stop being true.
    """
    looked = "\n".join(f"  {c.label:<16} {c.base_url or 'ANTHROPIC_API_KEY, or `ant auth login`'}" for c in CANDIDATES)
    return (
        "nothing on this machine can answer yet. poieo looked for:\n\n"
        f"{looked}\n\n"
        "Start one of those, or set a Claude credential, then run `poieo init` "
        "again.\nTo lay the project out now and bind a real model later, run "
        "`poieo init --mock`\n-- which answers from a script, so nothing it "
        "writes is a real model's work."
    )


def init_project(root: Path, default_body: str, name: str | None = None) -> list[tuple[str, str]]:
    """Write a working project into ``root``; never touch an existing file.

    ``default_body`` is the binding the caller settled on -- see
    :func:`binding_document`. ``name`` is what a board will call this project,
    defaulting to the folder's own name -- a good guess and a bad default, so
    it is written into the file where it can be seen and changed rather than
    left as a fallback a reader has to be told about.

    Returns one ``(action, relative path)`` pair per file, action ``wrote`` or
    ``kept``.
    """
    files = [
        ("poieo.yaml", marker_body(name or root.name)),
        ("models/default.yaml", default_body),
        # Always written, never chosen for you: `-b models/mock.yaml` is how
        # the wiring gets exercised without spending a token.
        ("models/mock.yaml", MOCK_BINDING),
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

    # An empty page, so the memory is something you can open rather than a
    # feature you have to be told about. Nothing switches on: the page is all
    # comments, and those are stripped before any prompt sees it.
    from .layout import layout_for
    from .memory import keeps_memory, write_page

    kept_memory = keeps_memory(root)
    if not kept_memory:
        write_page(root, _CONSTITUTION)
    report.append(("kept" if kept_memory else "wrote", str(layout_for(root).longterm().relative_to(root))))

    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    missing = [line for line in _GITIGNORE_LINES if line not in existing.splitlines()]
    if not missing:
        report.append(("kept", ".gitignore"))
    else:
        joined = existing + ("" if existing.endswith("\n") or not existing else "\n")
        gitignore.write_text(joined + "".join(f"{line}\n" for line in missing), encoding="utf-8")
        report.append(("wrote", ".gitignore"))

    # A generated project that cannot load is an init bug, caught here and not
    # at 3am -- and a kept, hand-edited poieo.yaml is re-checked too. The one
    # caller that wants the full depth, and the only reason this module knows
    # the daemon exists. Late, because DaemonConfig extends ProjectSpec above.
    from .daemon.config import load_config

    load_config(root / "poieo.yaml")
    return report
