# How code is written here

The component documents say how each part works. This one says how a part is
*written* — the handful of habits this codebase keeps that a competent
programmer would not guess, because they are not what generic good taste says.

Nothing here is about small functions, clear names, or not repeating yourself.
You already know those, and a rule you already follow costs attention to read
without changing a line. What follows is only the places where this repository
differs, and each says why, because a habit whose reason is gone should be
dropped rather than obeyed.

If a rule here and the code disagree, the code wins and this document is a bug.

## A module says what it is for, and where its design lives

Every module opens with one line naming its job, and closes the docstring with a
pointer to the document that explains it:

```python
"""The logical layer: what work happens, in what order.

A graph never names a model. Nodes name a *role* ("classifier", "writer"), and
:mod:`poieo.binding` maps roles onto physical endpoints.

Design: docs/graph.md
"""
```

Fourteen modules carry that `Design:` line. It is the only thing tying a file to
the document that must be updated when the file's shape changes — the merge gate
asks for that edit, and this is how the next reader finds which document it was.

## A spec forbids what it does not know

Every configuration model sets `extra="forbid"`:

```python
class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")
```

A key poieo does not recognise is a typo, and a typo must be a loud failure when
the file loads, never a setting that silently did nothing until someone wonders
at 3am why the retry never happened. `errors.describe_invalid` turns the refusal
into the user's words and offers the nearest real key, so strictness costs the
user a suggestion rather than a puzzle.

This is the invariant *fail at launch, not at 3am* (`docs/architecture.md`) in
the one line that actually enforces it.

## The raise says what broke; a `Cause` says it to the user

Everything raised is a `PoieoError` subclass — nine of them, seven in `errors.py`
and two beside the code that raises them — and a bare `ValueError` reaching the
surface is a bug. The message at the `raise` is for whoever reads the traceback.

The sentence the *user* reads is not written there. It lives in one place,
`errors.explain_failure`, which walks the exception chain and returns a `Cause`:
a stable slug, what happened, and one thing to try.

```python
@dataclass(frozen=True)
class Cause:
    slug: str   # the pause logic counts by it, the web groups by it
    said: str   # what happened, in the user's words
    fix: str    # one thing to try
```

**The slug is an interface; the sentences are not.** Reword `said` and `fix`
freely. Renaming a slug silently resets the count that pauses a task after three
identical failures (`daemon/service.py`, where *identical* means the same slug) and
regroups the web's history — a change to make deliberately, not while rewording.

## Not knowing is an answer worth returning

`explain_failure` returns `None` when nothing matches, and the caller shows the
raw error instead. An honest *unclassified* beats a confident wrong sentence,
and the real error is still there either way.

Prefer that shape wherever a guess would be indistinguishable from knowledge.

## Comments explain the constraint, not the mechanic

The code says what it does. A comment earns its line by saying what the reader
cannot see — why this branch exists, what it is protecting, what will break:

```python
# Overload (429/5xx) lands here too: the server's mood, not the request's
# shape, so the unreachable advice is the right one.
```

```python
class UiSpec(_Spec):
    """Canvas coordinates. Written by the editor, ignored by the runtime."""
```

Comments are sparse on purpose. One that restates the line under it is deleted
on sight; one holding the reason a surprising line is correct is load-bearing.

## A seam is one module and one registry line

Three things are deliberately swappable, each with a single chokepoint
(`docs/architecture.md` names them): which backend answers, where tools run,
what a node type does. Adding a provider, an executor, or a node type should
touch one new module and add one line to a registry.

**If it needs more than that, the seam has leaked, and the leak is the bug** —
fix the seam rather than threading the new case through the callers.

## A test is named after the behaviour it defends

```python
def test_rejects_dangling_edge():
def test_cycles_are_allowed():
def test_rejects_bad_template_at_load_time():
```

Not `test_load_graph_2`. The suite is read most often when something has gone
red, and the name is the first and sometimes the only description of what was
promised. This repo is TDD, so the name exists before the behaviour does.

## A new word costs an old one

The user's vocabulary is three words — a **task**, a **run**, a **change** — and
the merge gate refuses a fourth, or a second way to say one of the three. That
applies inside the code as well: a concept named one thing in `runtime/` and
another in `web/` becomes two concepts in the reader's head, and eventually two
in the product.

Before introducing a name, look for the one already in use. Before keeping both,
delete one.

## Say what you assumed, before it is only in the code

A change almost always rests on something you could not check: what a caller
expects, whether a rule still holds, which of two readings of the request was
meant. **Notice it while you are writing, and put it in the PR** — this belongs
here rather than with the PR rules because the moment it applies is the moment
you decide, not the moment you write the description.

This is not general caution, it is specific to how this repository is built.
Most of what the code answers to came from `docs/archive/`, written by sessions
that no longer exist to be asked, so a fair number of assumptions cannot be
resolved at all — only declared. An assumption you state is one a reader can
disagree with. An assumption that reaches `main` only as code is indistinguishable
from a decision, and the next session will defend it.

This is *Not knowing is an answer worth returning*, above, turned toward the
reader: the code declines to name a cause it is unsure of, and you decline to
encode a belief you could not check.

Two readings that lead to different work are still not a reason to stop. Asking a
human is reserved for the four one-way doors `AGENTS.md` names, and ambiguity is
not one of them: take the likelier reading, say which you took, and carry on. A
question costs a round trip; a declared assumption costs a sentence.
