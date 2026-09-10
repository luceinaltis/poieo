<picture>
  <source media="(prefers-color-scheme: dark)" srcset="site/img/lockup.svg">
  <img src="site/img/lockup-light.svg" alt="poieo — the tree with its golden fruit and original wordmark" width="460">
</picture>

# The right intelligence, in the right place.

**Small and large models, working together.**

Give routine work to a small model and demanding steps to a larger one. poieo keeps your tasks running, carries their context forward, and records the results.

[Website](https://luceinaltis.github.io/poieo/) · [Documentation](https://luceinaltis.github.io/poieo/docs.html) · [Get started](#start-with-one-task)

[![gate](https://github.com/luceinaltis/poieo/actions/workflows/gate.yml/badge.svg)](https://github.com/luceinaltis/poieo/actions/workflows/gate.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-285b3f.svg)](LICENSE)
[![python: 3.10+](https://img.shields.io/badge/python-3.10%2B-536657.svg)](pyproject.toml)

## Put each model where it helps

The goal is more accuracy for the cost. A small model can handle frequent,
well-bounded steps; a larger model can take on demanding reasoning, writing,
or review. Add checks that tell you whether the result is useful.

| Work | An approach to try |
|---|---|
| Read, sort, summarize | Start with a small model and check its output. |
| Make a difficult change | Use a larger model where its capability earns the cost. |
| Check the result | Run your tests and inspect the change; model size alone is not evidence. |

You choose the model for each step. poieo follows those assignments; it does
not automatically find the cheapest or most accurate model. Savings and
accuracy depend on the models, tasks, and checks you choose.

Models can run locally or through cloud APIs. The work names roles; a separate
configuration assigns models to them, so a model can change without rewriting
the task. [Choose your models](docs/usage.md#choose-models).

## Work that keeps going

| | |
|---|---|
| **task** | The work you want kept running: a name, a folder, and instructions. |
| **run** | One attempt at that task, with a record of what happened. |
| **change** | File edits a run leaves for review in a Git project. |

Write the task once. poieo runs it on your schedule, keeps its journal, and
shows its results on one board. Project memory can share learned context
across tasks. Pause a task, run it now, or leave a note for its next run.

![The task board, with a run's result and a file change opened for review](site/img/task.png)

In a Git project, the task works in a **private copy**. Read the diff and
**accept** it when you want the edits in your checkout, or **discard** it to
set the work aside. A folder without Git is edited directly and has no
built-in review or undo.

## Start with one task

Install poieo and create a project with its offline scripted model:

```bash
git clone https://github.com/luceinaltis/poieo
cd poieo
pip install .

mkdir my-board
cd my-board
poieo init --mock
```

Save this as `tasks/keep-green.yaml`. Replace the folder with an existing Git
project on your machine:

```yaml
name: keep the tests green
folder: /path/to/your/git-project
prompt: |
  Run the tests. Find and fix a failing test.
  Run them again to check the change.
```

```bash
poieo daemon
```

Open the board at **http://127.0.0.1:8484**. The mock exercises the loop without
calling a real model; it does not actually repair your project. Follow the
[model setup guide](docs/usage.md#choose-models) to connect real models.

For a new project that should discover real models immediately, use
`poieo init` without `--mock`. It records reachable model endpoints and
credential variable names in plain files.

## Give the work more shape

An ordinary task needs one prompt. When it needs several kinds of work, a
graph adds steps, branches, loops, and checks. Each model step names a role:

```yaml
nodes:
  - id: classify
    type: agent
    role: reader
    prompt: "Classify as bug, feature, or question.\n{{ input.message }}"
```

Assign a small model to `reader` and a larger one to a demanding role in the
model configuration. `poieo show` displays a task's graph; `poieo eject`
exports the full graph when the short form is no longer enough.

The [self-improvement example](examples/improving-poieo/README.md) connects
reading, planning, building, and review. It is a concrete place to try different
model assignments and judge their results.

## Yours to run and inspect

- **Choose the models.** Local models, hosted APIs, and supported coding-agent subscriptions can serve different roles.
- **Keep the context.** Task journals carry earlier work forward; optional project memory shares learned context.
- **See what happened.** Run records include model responses, tool activity where available, usage, and cost when reported or configured.
- **Own the records.** Tasks and model settings are plain files. Project memory is an inspectable SQLite database with its own history.

poieo is a personal tool: no accounts or team workspaces. The browser handles
ordinary tasks, model choices, memory, and review. Advanced schedules,
isolation, and graph wiring are configured in files.

The [manual](docs/usage.md) covers setup and everyday use.
[DESIGN.md](DESIGN.md) records product principles and the roadmap.
[Component documentation](docs/README.md) and [AGENTS.md](AGENTS.md) are the
starting points for contributing.

MIT licensed. `poieo` is Greek *ποιέω*, “to make.”
