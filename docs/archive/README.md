# archive

The dated design specs and implementation plans poieo's features were built
from, up to 2026-08-27. They are kept because they record *why* a thing was
shaped the way it was, and a decision's reasoning is worth more than its date.

**This is history, not documentation.** Every one of these was accurate about
the intent at the time it was written; none of them is guaranteed to describe
the code today. For that, read the component documents one level up —
`docs/README.md` is the index.

Nothing new is written here. A design worth recording belongs in the component
document it describes.

```
specs/   what a feature should do, written before any code
plans/   the same feature cut into task-sized, test-first slices
```

Two things to know when reading them:

- **Paths inside these files are pre-move.** A document referring to
  `docs/specs/…` or `docs/plans/…` means `docs/archive/specs/…` and
  `docs/archive/plans/…`. They were left as written rather than rewritten,
  because a snapshot that gets edited is no longer one.
- **Checked boxes in a plan mean the slice landed**, not that the code still
  looks like the slice described.
