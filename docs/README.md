# poieo documentation

The documentation has two paths: using poieo and changing it. Everything here
describes the current repository; git keeps the history.

## Use poieo

Start with the root [`README.md`](../README.md) for the one-minute tour, then use
[`usage.md`](usage.md) to create a project, keep tasks running and review their
changes. [`DESIGN.md`](../DESIGN.md) records the promises and limits behind that
experience.

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

Then read the document for the component you are changing:

| document | responsibility | code |
|---|---|---|
| [graph.md](graph.md) | the logical work and its wiring | `graph.py`, `expr.py` |
| [binding.md](binding.md) | resolving roles to models and providers | `binding.py`, `providers/` |
| [runtime.md](runtime.md) | executing one run | `runtime/` |
| [tools.md](tools.md) | file, shell and note tools; execution and isolation | `tools/` |
| [tasks.md](tasks.md) | task cards, journals and notes | `card.py` |
| [daemon.md](daemon.md) | triggers, residency, control and handoff | `daemon/` |
| [workspace.md](workspace.md) | private copies and reviewable changes | `workspace.py` |
| [memory.md](memory.md) | long-term project memory and learning | `memory/`, `learn.py`, `strength.py`, `blob.py` |
| [storage.md](storage.md) | project layout, run records and detection | `layout.py`, `project.py`, `detect.py`, `store.py` |
| [web.md](web.md) | the HTTP/SSE API and browser interface | `web/`, `web-ui/` |
| [cli.md](cli.md) | command-line behavior and project discovery | `cli.py` |

## Documentation contract

- A component document explains current responsibilities, contracts and
  non-obvious constraints. It is updated in the PR that changes them.
- Product instructions belong in `usage.md`; product promises and future work
  belong in `DESIGN.md`.
- Implementation history belongs in git, not in dated design files or in a
  current component guide.
- If the code and a current document disagree, the document is a bug.
