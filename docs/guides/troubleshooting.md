# Troubleshooting

Start with the failed run on the board. It keeps the error and progress even
when the work does not finish.

## A task will not run

Check that it is switched on in **Task setup**, resumed, and not waiting for
an answer. To check its file, replace `<task>` with its filename:

```bash
poieo validate tasks/<task>.yaml
```

The error names the file and field to fix. Relative folder paths start from
the task file, not the terminal's current folder.

## A model will not connect

```bash
poieo check
poieo config models
```

Confirm the server is running, its credential is available, and the selected
model is served there. Follow [Models](models.md) to change the selection.

## A change will not apply

Read the checks on the run. Resolve tracked edits or conflicts in your project,
then review the saved work. [Changes](changes.md) explains review, automatic
application, and undo.

## Inspect a run from the terminal

```bash
poieo runs list
poieo runs show <run-id>
```

Use `poieo <command> --help` for command options.
