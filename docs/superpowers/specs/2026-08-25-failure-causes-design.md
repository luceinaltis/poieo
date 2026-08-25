# Failure Causes Design

**Date:** 2026-08-25
**Status:** Approved for planning
**Relates to:** `2026-08-22-user-experience-gaps.md` — this is candidate **C**,
graduated from proposal to design. DESIGN.md principles 5 (fail at launch) and 6
(you can always see what it did).

## Goal

When a run fails, the user's first question is *why*, and today the answer is
`NodeError: node 'work' failed after 2 attempt(s): local: cannot reach
http://localhost:11434: ...` — a stack trace's opening line, in a log. And a
cause that persists — Ollama down at 2am — produces the same failure every
trigger until morning: four hundred red runs that say nothing three didn't.

Two moves, from the original proposal:

1. **Failures carry a cause**: a user-level sentence and one suggested action,
   attached to the run everywhere the run goes.
2. **A flow that fails the same way three times in a row pauses itself** and
   says so. Staying up is the default; staying up while failing identically is
   not resilience, it is noise.

## 1. The cause

A new value classified at the one place the original exception still exists —
the executor's catch — and carried on `RunResult`:

```
cause: {slug, said, fix} | None
```

`said` is a plain sentence (*the model could not be reached*), `fix` one
suggested action (*is the server running? `poieo check` probes every
provider*), `slug` a stable key the pause logic and the web can group by.
Classification walks the exception chain (`__cause__`), so a `ProviderError`
wrapped in a `NodeError` still explains itself.

The causes, from the failures the code can actually produce:

| slug | said | typical origin |
|---|---|---|
| `unreachable` | the model could not be reached | retryable ProviderError exhausted |
| `no_credentials` | the model's credentials are missing | `$X is not set`, auth failures |
| `rejected` | the model rejected the request | provider HTTP 4xx |
| `out_of_turns` | ran out of turns before finishing | agent hit `max_turns` |
| `bad_output` | the answer was not the shape the graph expects | JSON parse / output path |
| `folder_gone` | the folder it works in is missing | workdir vanished under the flow |
| `no_isolation` | the isolated environment could not be provided | IsolationError |
| `cycling` | the graph kept cycling and hit max_steps | RunAborted(max_steps) |
| `bad_expression` | an expression in the graph failed | runtime ExpressionError |

Unmatched failures carry no cause — an honest "unclassified" beats a wrong
sentence. The raw error stays exactly where it is today, for whoever wants it.

Where the cause reaches the user:

- `poieo run` prints two lines under the error: `cause` and `try`.
- The run summary and the `run_failed` event carry it, so `runs list`, the
  API, and the web board can show it without re-parsing error strings.
- A task's journal `failed` line becomes the sentence plus the action —
  what the model (and the person) reads next run, instead of an exception
  repr.

## 2. The pause

`FlowRunner` counts consecutive failed runs sharing one key — the cause slug,
or the raw error string when unclassified. A completed run resets the count.
At **three**, the flow pauses: status becomes `paused` (visible in
`/api/flows` and `poieo flows` through the existing status field), one log
line says why, and a task-backed flow gets a journal line so the reason
survives to the next morning. `on_error: stop` keeps its existing, stricter
meaning; the pause is the new default between "ignore forever" and "die on
first failure".

Paused is not failed, and resuming is deliberately manual in this slice:
restarting the daemon rearms the flow. The web control plane's resume button
lands with the rest of its mutations, later. Three is a constant, not a
setting — a knob would be configuration nobody asked for; revisit only on
real demand.

## Out of scope

- Ceilings and the morning digest (candidate **D**) — separate design.
- Retry/backoff changes. Classification observes; it never alters behaviour
  of the run itself.
- A paused flow auto-resuming when the cause clears. It needs the probe
  machinery running on a schedule; design it when someone misses it.
