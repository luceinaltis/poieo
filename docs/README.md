# poieo documentation

The documentation has two paths: using poieo and changing it. Everything here
describes the current repository; git keeps the history.

## Use poieo

The short guides each cover one part of everyday use:

- [Get started](guides/getting-started.md) — install and open the board.
- [Models](guides/models.md) — connect models and assign them to steps.
- [Tasks](guides/tasks.md) — create, schedule, and direct work.
- [Changes](guides/changes.md) — review, apply, and undo work.
- [Troubleshooting](guides/troubleshooting.md) — find and fix a problem.

[`DESIGN.md`](../DESIGN.md) records the product's promises and limits.

The CLI itself is the command reference:

```bash
poieo --help
poieo <command> --help
```

## Change poieo

Read [`architecture.md`](architecture.md) for the system boundary and one run end
to end. [`conventions.md`](conventions.md) contains the repository-specific coding
rules, and [`contribution.md`](contribution.md) contains the procedures needed to
land a change. `AGENTS.md` at the repository root is the working agreement and
the source of the merge gate.

[`branding.md`](branding.md) records the approved persimmon identity, copy,
colours, and visual direction shared by the website, docs, README, and board.
The [brand guide](../brand/README.md) lists the assets and their use.

Then read the document for the component you are changing:

| document | responsibility | code |
|---|---|---|
| [graph.md](graph.md) | the logical work and its wiring | `graph.py`, `expr.py` |
| [binding.md](binding.md) | resolving roles to models and providers | `binding.py`, `providers/` |
| [runtime.md](runtime.md) | executing one run | `runtime/` |
| [tools.md](tools.md) | file, shell and note tools; execution and isolation | `tools/` |
| [tasks.md](tasks.md) | the full form of a task, task cards, journals and notes | `task.py`, `card.py`, `journal.py` |
| [daemon.md](daemon.md) | triggers, residency, control and handoff | `daemon/`, `cron.py` |
| [workspace.md](workspace.md) | private copies and reviewable changes | `workspace.py` |
| [memory.md](memory.md) | long-term project memory and learning | `memory/`, `learn.py`, `strength.py`, `blob.py` |
| [storage.md](storage.md) | project layout, run records and detection | `layout.py`, `project.py`, `detect.py`, `store.py` |
| [web.md](web.md) | the HTTP/SSE API and browser interface | `web/`, `web-ui/` |
| [cli.md](cli.md) | command-line behavior and project discovery | `cli.py` |

## Documentation contract

- A component document explains current responsibilities, contracts and
  non-obvious constraints. It is updated in the PR that changes them.
- Product instructions belong in the short pages under `guides/`; `usage.md`
  is their entry index. Product promises and future work belong in `DESIGN.md`.
- Implementation history belongs in git, not in dated design files or in a
  current component guide.
- If the code and a current document disagree, the document is a bug.
