# Project Folders — Implementation Plan

**Spec:** `docs/specs/2026-08-25-project-folders-design.md`
**Branch slug:** `project-folders` (one PR per task, squash-merged)

Verification gate for every task, before its PR merges:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio
```

---

## Task 1: `poieo.project` — discovery, and the store stops crashing

**New module** `src/poieo/project.py`:

- `find_project(start: Path | None = None) -> DaemonConfig | None` — walk from
  `start` (default cwd) upward to the filesystem root; at the first directory
  holding a file literally named `poieo.yaml`, return `load_config` of it;
  otherwise `None`. Discovery must not blow up on an invalid config — that
  file was about to be read anyway, so let `SpecError` propagate (it is the
  product's voice already).

**CLI**: `runs list` and `runs show` resolve their store as
flag → `find_project().store_path()` → `Path(".poieo")`.

Tests (`tests/test_project.py`, plus `tests/test_cli.py` additions):

- [x] `find_project` finds `poieo.yaml` in the start dir; in a parent; returns
      `None` when absent all the way up.
- [x] nearest file wins when two ancestors both hold one.
- [x] `poieo runs list` with no `--store` and no project exits cleanly with
      "no runs recorded" — the current `TypeError` traceback, pinned first as
      a failing test.
- [x] `poieo runs list` with no `--store` inside a tmp project reads the
      project's store.
- [x] the empty-store message names the directory it searched.

Steps: failing tests → run to see them fail → implement → suite green →
self-review → PR `feat: a poieo.yaml marks a project; runs commands find its store`.

---

## Task 2: commands read the project file

**Binding chain** in `run`, `validate`, `learn`; `check`'s `-b` becomes
`Optional`: flag → card's `binding:` → project's `binding:` (resolved against
the config file, via `resolve_path`) → today's failure message, now ending
"…or run `poieo init`". When the project supplied it, `run`/`validate` echo
`binding    <path>  (from <poieo.yaml path>)`.

**Store for `run`**: flag → project `store:` → beside the card → `./.poieo`.

**Argless daemon/flows**: `config_path` becomes `Optional`; omitted, use the
discovered `poieo.yaml`, else fail naming `poieo init`.

Tests:

- [x] `poieo run card.yaml` with no `-b`, card silent, inside a project whose
      `poieo.yaml` names the mock binding: runs, and the output contains
      `(from` — the transparency line.
- [x] flag still beats project; card still beats project.
- [x] outside a project the failure message names `poieo init`.
- [x] `poieo run` on a card inside a project writes the run log into the
      project store, not beside the card.
- [x] `poieo check` with no `-b` inside the project probes the project's
      binding; outside, fails in the product's voice.
- [x] `poieo daemon --once` with no argument inside a project runs it;
      outside, fails naming `poieo init`. Same for `poieo flows`.

PR `feat: run, check, learn and the daemon read the project's poieo.yaml`.

---

## Task 3: `poieo init`

`src/poieo/cli.py` gains `init`; the writing/detection logic lives in
`src/poieo/project.py` so the web control plane can call it later.

- Detection (init-time only): `ANTHROPIC_API_KEY` → claude binding; else
  Ollama `GET /api/tags`, 1 s timeout, ≥1 model → ollama binding naming the
  first model; else mock is the default.
- Writes per the spec: `poieo.yaml`, `bindings/default.yaml`,
  `bindings/mock.yaml`, `tasks/hello.yaml` (`enabled: false`), `.gitignore`
  line `.poieo/` (file created if absent, line appended once, never
  duplicated).
- Idempotent: existing files are never touched; each path reports `wrote` or
  `kept`. Exit 0 either way.
- Output ends with the next two commands
  (`poieo run tasks/hello.yaml`, `poieo daemon`).
- Everything written must load: the last act of `init` is
  `load_config("poieo.yaml")` — a generated project that fails its own
  validation is a bug caught at init, not at 3am.

Tests (network probe stubbed):

- [x] empty dir + no key + no ollama → mock default; the generated project
      passes `load_config`; `poieo run tasks/hello.yaml` completes offline.
- [x] `ANTHROPIC_API_KEY` set → default binding names the anthropic provider.
- [x] ollama stub answering with a model → ollama binding naming it.
- [x] second `init` reports `kept` for every file and changes nothing
      (byte-compare).
- [x] `.gitignore` gains the line once, keeps existing content, and a third
      run does not duplicate it.

PR `feat: poieo init writes a working project from what the machine has`.

---

## Follow-ups this plan does not do

- README: the project-folder walkthrough replacing the copy-from-examples
  onboarding — after Task 3 lands, docs-only.
- Binding composition (`extends`, fallbacks, aliases) — next spec.
