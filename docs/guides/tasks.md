# Tasks

A task is a folder, instructions, and a schedule. Each run records what happened.

## Create a task

Choose **New task** on the board. Enter a name, the absolute path to your
project folder, and a prompt such as “Run the tests. Fix failures and run
them again.” Choose **save and start**, or **save without starting** to inspect
it first. Open **Task setup** to switch a saved task on or edit its instructions.

Use a Git project for work you can [review and undo](changes.md). Without Git,
a task edits the folder directly and poieo cannot undo it.

## Run and schedule

The default is once at startup, then hourly. **run now**, **pause**, and
**resume** control an enabled task. Pause stops future work; it does not kill
an operation already in progress.

To change the schedule, edit the task's file under `tasks/`. Use one of:

```yaml
every: 30m
```

```yaml
at: "0 2 * * *"
```

Restart the daemon after changing a schedule or working folder. Prompt edits
and switching a task on or off do not need a restart.
[More schedule options](../daemon.md#triggers).

## Add steps

For a new task, choose **Write as steps**. Add model instructions, commands,
conditions, or a question for you. **Insert result from…** passes an earlier
answer into later instructions. Answer waiting questions on the board while
the daemon is running.

**View steps** shows the flow. Editing an existing graph uses its file;
see the [graph reference](../graph.md).

## Give direction

Open a task and use **Give direction** to leave a note for its next run.
Recent results carry forward through its journal.
[Project memory](../memory.md) can retain shared context across tasks.
