# poieo design docs

One document per component, describing **how that component works and why it is
shaped that way**. These are the developer's map of the code: read them before
changing something, and update them when the shape of a component changes.

Three other documents sit outside this folder and answer different questions:

| document | answers |
|---|---|
| `DESIGN.md` | what poieo promises its *user* — vision, principles, roadmap |
| `README.md` | how to *use* poieo — commands, file formats, examples |
| `CLAUDE.md` | how to *change* this repository — branches, PRs, the merge gate |

## Start here

**[architecture.md](architecture.md)** — the whole system in one page: the
layers, one run end to end, which module owns what, and the invariants every
component is written to hold.

## The components

| doc | covers | code |
|---|---|---|
| [graph.md](graph.md) | the logical layer: what work happens, in what order | `graph.py`, `expr.py` |
| [binding.md](binding.md) | the physical layer: which model actually answers | `binding.py`, `providers/` |
| [runtime.md](runtime.md) | executing one run: the walker, the scope, the nodes | `runtime/` |
| [tools.md](tools.md) | the hands: toolsets, the executor seam, isolation | `tools/` |
| [tasks.md](tasks.md) | the short form: one card, its journal, notes between cards | `task.py` |
| [daemon.md](daemon.md) | residency: config, triggers, the runner, the control seam | `daemon/` |
| [workspace.md](workspace.md) | the private copy, and last night's work as a change | `workspace.py` |
| [memory.md](memory.md) | what a project keeps and how a run is shown it | `memory/`, `learn.py`, `strength.py`, `blob.py` |
| [storage.md](storage.md) | where every file lives, the run log, and what `init` finds | `layout.py`, `project.py`, `detect.py`, `store.py` |
| [web.md](web.md) | the HTTP/SSE API and the page it serves | `web/`, `web-ui/` |
| [cli.md](cli.md) | the command line, and the rules it uses to fill silence | `cli.py` |

## Conventions

- A component doc describes the **current** code. If a doc and the code
  disagree, the code wins and the doc is a bug.
- Features that are half-built say so, in the doc for the component that would
  own the other half. There is no separate roadmap here — `DESIGN.md` has one.
- No dated files. When a component changes, edit its document; git already
  records when and why.

## archive/

[`archive/`](archive/README.md) holds the dated design specs and implementation
plans the features were built from, up to 2026-08-27. They are history: accurate
about the intent at the time, not necessarily about the code today. Nothing is
written there any more, and nothing needs to be read there to understand the
system — the component docs above are the current account.
