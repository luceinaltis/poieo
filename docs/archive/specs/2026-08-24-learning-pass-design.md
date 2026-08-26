# Learning Pass Design

**Date:** 2026-08-24
**Status:** Approved for planning
**Roadmap:** a long memory — the sleep-time slice
**Builds on:** docs/specs/2026-08-24-project-memory-design.md, docs/specs/2026-08-24-memory-connections-design.md

## Goal

Every run leaves a full record, and so far a person has to read them. The
records pile up; the lessons in them do not move into `memory/facts/` unless
someone sits down and writes. This slice adds that sitting down: **every so
often the project reads what its runs left behind and writes down what stays
true.** The user's word for it is *learning* — the daemon learns overnight,
or you ask for a pass with `poieo learn`.

The source design calls this sleep-time compaction, and its central claim
survives intact: distillation is storage, so the distiller is the most
dangerous writer in the system, and everything here is shaped by that.

## The one idea

**The machine may author the learned layer only through a narrow, validated
door — and it is the only machine that may.** A learning pass calls one
model (the `learner` binding role), shows it the unread records and what the
project already knows, and receives a *proposal*: entries worth keeping, and
entries that should step aside. The harness — not the model — validates
every line of that proposal and writes the files, exactly as `tell` stamps a
note's sender rather than trusting an argument.

What the pass may do is precisely what a careful person does in an editor,
and nothing more:

- write a **new entry**, with its `source:` naming the runs that taught it —
  the traceability requirement is stamped by the harness, not requested of
  the model;
- **set an entry aside** (`superseded_by:`) in favor of another — demote,
  never delete;
- and that is all. The pass never touches the page (`constitution.md` stays
  a human document — the always-loaded layer has the largest blast radius,
  and its revisions wait for a person), never deletes a file, never
  overwrites an existing entry, and never edits an entry's body.

## Decisions already made (with the user)

From the source design, held here:

- **One author, serialized.** The pass is the sole machine writer of
  `memory/facts/`, and one pass runs at a time. Agents in runs still have no
  memory tool at all.
- **Blast-radius routing is a binding decision, not code.** A wrong entry
  poisons every later run, and the write volume is tiny — so the design
  routes final distillation to the best model available. In poieo that is
  one line in a binding: `roles: {learner: ...}`. Unbound, the role falls
  through to the binding's default, so nothing is required to start. (The
  design's two-stage split — cheap mechanical selection, expensive final
  judgment — is a later refinement; this slice is one call per pass.)
- **An empty proposal is the right answer most nights.** The prompt says so.
  Most runs teach nothing durable, and a pass that manufactures entries to
  seem useful is worse than one that stays quiet.
- **Nothing is lost to a failure.** The pass keeps a bookmark — the last
  record it successfully read — and moves it only on success, so a failed
  pass rereads rather than skips. The same argument, again, as the journal:
  repeating is recoverable, losing is not.

## What a pass is

1. **Collect.** Records under `.poieo/episodes/` newer than the bookmark,
   oldest first, capped per pass; what does not fit arrives next pass, and
   the bookmark only moves as far as what was shown.
2. **Ask.** One completion, role `learner`: the page, the kept entries
   (slugs and bodies, budgeted), and the batch of records (run, task,
   status, summary). The model answers with JSON only:

   ```json
   {
     "entries": [
       {"slug": "batch-cap", "body": "…", "scope": ["importer"],
        "anchors": [], "from": ["20260824T114742-aaadba2a"],
        "links": {"depends_on": [], "contradicts": []}}
     ],
     "set_aside": [
       {"entry": "old-cap", "because": "batch-cap"}
     ]
   }
   ```

3. **Validate, per proposal.** A slug must be plain (`[a-z0-9-]`, letter or
   digit first) and must not collide with any existing entry or another
   proposal — the pass never overwrites. Typed links must name entries that
   exist (counting this pass's accepted ones). `from` is intersected with
   the batch; if nothing survives, the whole batch is stamped. A proposal
   that fails any check is dropped and logged; the rest still land — one bad
   slug must not waste the night's good entries.
4. **Apply.** New entries are written by the harness with `source:` stamped.
   A set-aside edits exactly one frontmatter line of the target, keeping the
   body byte-identical — the entry remains what its author wrote, merely set
   aside; `because` must name an entry that exists, including one accepted
   this pass.
5. **Record.** One line appended to `.poieo/learning.jsonl`: when, the
   bookmark it reached, how many records it read, what it wrote, what it set
   aside, what it dropped, or how it failed. A runtime record like the run
   log — not derived, not truth, just what happened, so "what did learning
   do last night?" has a file that answers it.

## Where it runs

- **By hand: `poieo learn <folder-or-card>`.** One pass, now. This is the
  whole feature for a user without a resident daemon — an OS scheduler or a
  habit can drive it — and it is how the feature is tested and trusted
  before anyone hands it the night.
- **In the daemon: `learn: 1d` in the config.** A daemon-owned background
  loop (the web server and box-sweep precedent) that waits its interval,
  and runs a pass only when every runner is idle — learning always yields
  to work. Off unless configured.

Opt-in stays what it was: **no `memory/` folder, no pass, anywhere.** The
folder is the project's one memory switch; a config key must not be able to
conjure the feature for a project that never chose it. `poieo learn` on a
memoryless project says how to start one and exits cleanly.

## Out of scope (deferred, with their guardrails kept)

- **Page revisions.** The design routes constitution changes through human
  review even when machines propose them; this slice does not propose them
  at all. When proposals arrive, they arrive as a diff for a person, never
  as an applied edit.
- **Git-hook anchor revalidation and cascade re-checking** — the next
  lifecycle slice; the report's second-look line remains the interim.
- **Merging entries, editing bodies, restoring set-aside entries.** The
  pass's verbs stay at two until the two are trusted.
- **Two-stage model routing, batching by similarity, grace-period sweeps,
  cold archives.** Later, and deletion stays out of every later slice's
  fast path.

## Vocabulary

The project **learns** from the records its work leaves; a pass **keeps**
an entry or **sets one aside**; the daemon learns **while nothing else is
running**. The binding role is `learner`; the config key is `learn`. Words
that must not reach a prompt or CLI output, beyond the earlier lists:
*compact, distill, pipeline, worker, proposal, cursor, batch, ingest*. (The
bookmark needs no name in the interface at all — as with the journal,
nothing is written to mark it beyond the pass record itself.)

## Failure handling

| | |
|---|---|
| **no `memory/` folder** | no pass. The CLI says how to start one, exit 0; the daemon loop skips silently. |
| **no unread records** | no model call, nothing logged but a quiet debug line. Free. |
| **the model answers non-JSON** | the pass fails: recorded, bookmark unmoved, retried next pass with the same records. |
| **the provider is down** | same — one attempt per pass, no retry loop of its own; the next pass is the retry. |
| **one bad proposal** | dropped and named in the pass record; the rest land. |
| **a slug that already exists** | that proposal is dropped — the pass never overwrites, even its own past work. |
| **set-aside of a missing entry** | dropped and named. |
| **an empty proposal** | success. The bookmark moves; the record says nothing was worth keeping. |
| **the daemon is busy** | the loop waits for the next interval. Learning never runs beside a run. |
| **two passes at once (CLI beside daemon)** | the slug collision rule makes the race lose gracefully — duplicates are dropped, nothing is corrupted. Rare enough to accept, stated rather than hidden. |

## Testing

- The traceability property is the point, written first: an entry written by
  a pass carries `source:` run ids from the records that taught it, stamped
  by the harness even when the model claims otherwise.
- The bookmark: a failed pass rereads; a successful one never rereads; a
  capped pass drains across passes and drops nothing.
- Every validation refusal: bad slug, colliding slug, dangling link,
  dangling set-aside — dropped, logged, and the good proposals still land.
- A set-aside changes one frontmatter line and leaves the body
  byte-identical.
- The page is never written by any pass, and a memoryless project never
  gains a `memory/` folder from one.
- The daemon: learns only when idle, never learns unconfigured, and a
  failing pass never takes the daemon down.

## Implementation split

One plan (H), four tasks: the pass as a library function; `poieo learn`;
the daemon's idle loop; documentation, a scripted `learner` in the mock
binding, and the worked example learning from its own runs.
