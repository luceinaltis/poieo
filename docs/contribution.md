# Contributing: the longer procedures

`AGENTS.md` holds the rules, and every session loads it whole, so it is kept
short. This document holds the procedures those rules send you to — steps that
matter only sometimes, worth reading when you are in the situation and worth
nothing before. A rule belongs there; the incantation belongs here.

Each section names the rule that sends you here, so neither drifts alone.

## The checked-in bundle

*Merge condition 8.* You changed something under `web-ui/src/`. **The built
bundle is checked in, and rebuilding it is part of the same PR:**

```bash
npm run build --workspace web-ui
```

Then commit `src/poieo/web/static/`. That folder is deliberately tracked — it is
what a fresh checkout serves — while `web-ui/dist/` and `node_modules/` are
ignored.

Neither suite reads `src/poieo/web/static/`, so it drifts in silence. It once sat
four PRs behind `main`, and one of those four was a CSS fix, so a fresh checkout
served the bug `main` had already fixed — with both suites green over it the
whole time. **A green run is not evidence that the bundle is current; only the
rebuild is.**

## Stacking on unmerged work

*Part 2, "Stacking on unmerged work".* Branch off another branch only when the
work genuinely depends on it, and say so in the PR body along with the base.

### Why the ordinary rebase is wrong here

`main` uses squash merge, so when the parent's PR lands, its commit on `main` is
a **new** object with a new hash. The child branch still carries the parent's
original commits. Rebasing the child onto `main` the usual way replays those a
second time, and the child's diff silently grows to include work already merged.

### Move the child from the parent's pre-merge tip

```bash
git rebase --onto origin/main $PARENT_TIP $BRANCH
git push --force-with-lease origin $BRANCH
```

`$PARENT_TIP` is the commit the parent branch pointed at **while its PR was
open** — its last commit before merging. If the local branch is already deleted,
find it in `git reflog`.

### Check before you trust it

```bash
git log origin/main..HEAD
```

This should list only commits you wrote. If the parent's commits appear, the tip
was wrong: `git rebase --abort` and pick it again.

Then re-run the full gate from `AGENTS.md` Part 2. A rebase that applied cleanly
past a rename refactor proves the syntax still fits, not that the meaning does.

## Getting a reviewer that is not you

*Merge condition 2.* One account, no required review, and the person who wrote a
change is usually the one merging it. Self-review still catches a great deal —
a stale comment, a file staged by accident — but it cannot catch a wrong belief,
because the belief is what produced both the code and the review.

So the second pass has one requirement: **the reviewer must not carry your
reasoning.** Not a second look by you, and not an agent you have been explaining
yourself to for an hour. It needs the diff and the repository, and nothing else.

Any of these qualifies:

- A person.
- A fresh agent session, given the branch and no history of the work.
- A review tool that starts from the diff. In Claude Code the `/code-review`
  command does this; other tools do the same thing from a PR URL.

Give it the diff, not the story behind the diff. "Here is what I changed and why"
hands over the belief you wanted checked.

Then write both passes into the PR, including findings you disagreed with and
why — a review that only records what you already fixed reads as a review that
found nothing.

**A condition, not an approval.** `AGENTS.md` lists this under *merge only when
all of these hold*, so skipping it is skipping a condition, the same as merging on
an unrun suite. What is missing is not force but anyone to apply it: like every
other condition here, it is worth exactly what the person recording it is honest.

## What CI checks, and what it cannot

*Merge condition 1.* `.github/workflows/gate.yml` runs on every PR against `main`
and on every push to it. Three jobs: the Python suite on the lowest Python the
project claims to support; the frontend suite, the types, and a rebuild of the
checked-in bundle; and container isolation against a real docker daemon.

It **reports and does not block.** `main` has no required checks, so a red run
stops nothing by itself. That is deliberate for now — a gate turned on before it
has been watched fails honest work and gets routed around.

Three things are worth knowing when a run disagrees with your machine.

**CI drops two flags you use locally.** Part 2 of `AGENTS.md` runs pytest as
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio`; CI runs plain
`pytest -q`. Those flags work around a broken global plugin on one machine, and
CI is the standing check that the workaround stays local. If CI ever needs them,
the problem was never local and Part 2 is wrong.

**CI runs Ubuntu; you develop on Windows.** A break that only happens on Windows
— a shell, a codepage, a path separator — is invisible here and still has to be
caught by hand. The reverse is also true and newer: code that only ever ran on
Windows is now exercised on Linux for the first time.

**Thirty tests skip here and run in CI.** `tests/test_tools_docker.py` needs a
docker daemon *and* `alpine:3.20` already local — the module never pulls, so no
test is slow for a reason unrelated to isolation. On this machine the daemon is
usually not running, so those thirty skip and container isolation goes unverified
locally. CI has the daemon and pulls the image, and its job fails if the tests
skip rather than run: a green check that checked nothing is worse than a red one.

**The bundle check is a rebuild, not a heuristic.** vite writes straight into
`src/poieo/web/static/`, so CI rebuilds and fails if anything changed. A failure
means the committed bundle does not match the source it claims to come from;
`npm run build --workspace web-ui` and commit the result. A source edit that
changes nothing in the output — a comment, which minification drops — correctly
leaves the check green; it is asking about the bundle, not about your diff.

**The installed command has its own job.** Every other job runs against the
source tree — `tests/conftest.py` puts `src/` on `sys.path`, and `poieo` is not
installed on the machine this is developed on at all — so nothing else here would
notice if the package stopped installing or the console script stopped existing.
The `cli` job does `pip install .` (a real install, not `-e`), works outside the
checkout so `src/` cannot answer an import the install should have, walks **every**
command and subcommand asking each for its own `--help`, and then makes a project
and runs it end to end against the mock binding, which exists precisely so the
wiring can be exercised without spending a token.

The command list is enumerated from the app rather than written down, because a
list kept by hand goes stale the first time somebody adds a command and says
nothing about it. Two guards keep the job from passing vacuously: the enumeration
must yield at least ten commands, and `runs list` must actually show the run.

What it does **not** do is re-run each command's behaviour through a shell — that
is what the suite already covers, and repeating it per command would cost twenty
times as much to learn the same thing. What only a real process can show is the
process itself: the entry point, a fresh interpreter's import, and the exit code a
shell sees.

What CI cannot judge stays prose, and stays yours: whether a second reader looked
(condition 2), whether the component documents still describe the code (5), and
whether the change fits the design at all (9).

## What lint enforces, and what it refuses to

*Merge condition 1.* `ruff check .`, configured in `pyproject.toml` and
run by the same CI job as the Python suite. Three rule families, and the choice
of *which* is the whole point:

- **`F` — pyflakes.** A name that does not exist, an import or a local nobody
  reads, an f-string with nothing to fill in. These say *this is wrong*, not
  *I would have written it differently*, so they almost never cry wolf. A linter
  that is usually wrong gets skimmed past, and then it is worth nothing.
- **`E501` at 120, not the default 88.** The comments here carry as much as the
  code and are wrapped by hand at about 86; the formatter never reflows those,
  so an 88 limit would have meant rewrapping prose across the repository to
  satisfy a rule about code. At 120 there are eleven long lines instead of 374.
- **`I` — import order.** Mechanical, and `--fix` does all of it.

Everything past that is deliberately off. Style rules encode somebody's taste,
and a rule nobody agreed to is a rule that gets argued with in review forever.

`ruff format --check .` runs beside it. `--check`, never a rewrite: CI reports and
the author commits, because a job that edits the branch it is testing is a job you
cannot reproduce. The formatter is why `E501` is nearly free — it keeps code under
the limit on its own, and the eleven lines it cannot reach are the ones worth
looking at. It never reflows a comment or a docstring, so the prose is yours.

**`.git-blame-ignore-revs` names the reformat**, GitHub reads that file by name,
and one `git config blame.ignoreRevsFile .git-blame-ignore-revs` does the same
locally. Only list a commit there that changed nothing but layout — one carrying a
real edit alongside would take that edit out of blame with it.

It earned less than it was argued for. Measured on `cli.py`, the most reformatted
file: 1,483 of its 1,484 lines already blamed to whoever wrote them *without* the
file, because git matches a moved line on its own. The objection that a reformat
destroys history is largely folklore, and it was the objection this PR series
first refused the formatter over. The file stays because the next reformat may be
one git cannot follow, and because it costs nothing until then.

`src/poieo/editor.py` and `src/poieo/viewer.py` are exempt from `E501`. They hold
JavaScript and CSS inside Python strings, where a `# noqa` would be written into
the asset rather than the module — the line cannot be excused where it sits.
