# Contributing

The repository-wide working agreement and exact merge gate are in
[`AGENTS.md`](../AGENTS.md). This page holds procedures that matter only when a
change reaches one of the less obvious edges of that agreement.

## Checked-in browser bundle

`src/poieo/web/static/` is the browser application served by an installed
Python package. It is committed so users do not need Node.js at runtime.

Any change under `web-ui/src/` must rebuild and commit that bundle in the same
PR:

```bash
npm run build --workspace web-ui
git status --short src/poieo/web/static
```

Review the generated diff for unexpected assets. The ordinary Python and
frontend tests do not prove that the checked-in bundle matches the source;
the CI bundle job performs a clean rebuild for that purpose.

## Browser screenshots

When a browser change affects layout or interaction, capture the states a
reviewer cannot infer from tests: the normal view and any changed empty,
loading, error, narrow-screen, or open-panel state.

Build the bundle, start a mock project with `poieo daemon`, and use a fixed
viewport. Keep credentials and real transcripts out of screenshots. Attach
images to the PR rather than committing temporary captures unless the image is
an intentional documentation asset.

## Measuring recall

The suites fix what recall does; they do not say how well it does it.

```bash
python tools/recall_eval.py                                  # score every arm
python tools/recall_eval.py --write-terms <binding.yaml>     # only to add cases
```

Fixed tasks, the one lesson each should surface, and a look-alike aimed at each:
same topic, opposite advice. Scoring goes through `read_memory` and reports what
was found, whether the look-alike came with it, and how much budget went
elsewhere. Model-written inputs are checked in beside the cases, so an ordinary
run needs no binding and repeats exactly. Nothing inside the repository is
written. Run it when recall changes, and add a case when a real project turns
out to hold a lesson it could not find.

## Stacked branches after a squash merge

A child branch may depend on an unmerged parent. Record that parent and its tip
in the child PR. After the parent is squash-merged, do not rebase the child
normally: that would replay the parent’s original commits because the squash
has a different identity.

```bash
git fetch origin
git rebase --onto origin/main <old-parent-tip> <child-branch>
git log --oneline origin/main..<child-branch>
git push --force-with-lease
```

The final log must contain only the child’s work. Run the complete gate again;
a clean rebase proves only that patches applied.

## Independent review

The independent pass must read the complete `main...HEAD` diff without relying
on the author’s explanation. Record who or what performed it and the result in
the PR.

The review is looking beyond green tests:

- behavior or error paths that disappeared accidentally;
- a public surface, credential boundary, or storage contract that widened;
- stale comments or component documentation;
- generated, temporary, or unrelated files staged by accident;
- tests that assert the implementation instead of the user-visible contract.

Resolve findings before merge. A second review after a material rewrite should
cover the revised diff, not only the fix.

## What CI covers

The required gate checks:

- the Python suite on supported Windows and Linux environments;
- Ruff lint and formatting;
- frontend tests and TypeScript compilation;
- a clean browser-bundle rebuild;
- Docker isolation where a real daemon is available;
- an installed-package smoke test.

Coverage reporting is diagnostic, not a substitute for a behavior test. CI
does not exercise macOS, every local inference server, every browser, or a
developer’s real credential and filesystem setup. Perform the relevant manual
check when a change depends on one of those surfaces and paste its output in
the PR body.

Required check names are part of repository protection. If a workflow job is
renamed, update protection in the same administrative change or the old name
can leave every PR permanently waiting.

## Formatting and lint

The Python gate uses Ruff for errors, import order, line length, and formatting.
Run the commands from `AGENTS.md`; do not treat an editor’s formatting preview
as the gate. Frontend formatting follows the existing files and TypeScript is
the authoritative structural check.
