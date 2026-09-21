# Tasks

A task is a folder, instructions, and a schedule. Each run records what happened.

## Create a task

Choose **New task** on the board and say what it should do, in any language:
“every night, run the tests and fix one failure”. Not sure what to ask for?
Press one of the examples under the box. Your project's model asks what it
needs to know and proposes a card; **use this draft** fills it in for you to
read over, change and save. If the reply says no model could answer, **open
models** takes you to where one is connected. Or choose **or write it
yourself** and type the prompt; the name can stay blank and is taken from its
first line. Choose **save and start**, or **save without starting** to inspect
it first. Open **Task setup** to switch a saved task on or edit its
instructions.

A task works in your whole project and runs every hour. To limit it to one
folder or choose when it runs, open **more** under the prompt. The line above
the save button always says which folder will change and whether poieo can
undo it. Letting a task apply its own checked changes is switched on later,
in **Task setup**, under [Changes](changes.md).

Use a Git project for work you can [review and undo](changes.md). Without Git,
a task edits the folder directly and poieo cannot undo it.

## Run and schedule

The default is once at startup, then hourly. **run now**, **pause**, and
**resume** control an enabled task. Pause stops future work; it does not kill
an operation already in progress.

Choose **when** under **more** on the form: every hour, every 30 minutes,
every day, every night at 2, or **at another time…** for a line of your own.
In **Task setup** the same thing is the **every** line: an interval such as
`30m`, the word `loop`, or a cron line such as `0 2 * * *`. Leave it blank
for the hourly default. A changed schedule takes effect when
the daemon restarts, and the form says so. In the task's file under `tasks/`
the same line is one of:

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

A task of several steps — model instructions, commands, conditions, or a
question for you — is drawn in the standalone graph editor, `poieo edit`,
until the board hosts that canvas; see the [graph reference](../graph.md).
Answer waiting questions on the board while the daemon is running.

Cards start collapsed, keeping their inputs, outputs and connections visible.
Choose **Expand** on a card to see its steps, then **View steps** for a larger view.
Choose **Collapse** to return to the compact flow. Editing an existing graph uses
its file; see the [graph reference](../graph.md).

## Give direction

Open a task and use **Give direction** to leave a note for its next run.
Recent results carry forward through its journal.
[Project memory](../memory.md) can retain shared context across tasks.
