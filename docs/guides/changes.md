# Changes

In a Git project, poieo works in a private copy. You decide how its work
reaches your branch. Non-Git folders are edited directly, with no review or undo.

## Review

Open a run's change on the board and read the diff. **accept** merges it into
your current branch; **discard** sets it aside. Commit or set aside your own
tracked edits before accepting a change.

Review is the default. Nothing is applied automatically unless you enable it.

## Apply automatically

Open **Changes** in **New task** or **Task setup**. Choose **Apply automatically**,
allowed files or folders, and at least one verification command, such as
`python -m pytest -q`. Leaving allowed paths empty permits the whole task folder.

Checks run against the work combined with the latest project. All must pass
before application. A compatible conflict or failed check gets one repair
attempt within the task's permission, then fresh checks.

Contradictory goals, a failed repair, or work outside allowed paths leave the
work saved and pause that task. Other tasks continue. See the run's checks
to understand what happened.

Choose **Review before applying** to require your decision again. Revoking
permission also stops an application that is still being checked.

## Undo

Open an applied run and choose **Undo this change**. Later work is preserved,
and the same checks must pass. A conflict or failed check leaves the project
unchanged. A successful undo pauses that task.

[Application details](../daemon.md#applying-completed-work).
