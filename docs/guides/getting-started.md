# Get started

Install poieo and open your first board.

## Install

You need Python 3.10 or newer and Git.

```bash
git clone https://github.com/luceinaltis/poieo
cd poieo
pip install .
```

## Open the board

Create a project with the offline, scripted model:

```bash
mkdir my-board
cd my-board
poieo init --mock
poieo daemon
```

Open [localhost:8484](http://127.0.0.1:8484). Keep the terminal running while
you use the board. Stop it with Ctrl+C.

The mock lets you try tasks without model credentials or API charges. It does
not do real work or fix code. [Connect your models](models.md), then
[create a task](tasks.md#create-a-task).

For a new project with real models already available, use `poieo init` without
`--mock` to discover them. Initialization leaves existing files intact.

The board is a personal, local tool. It has no account or password layer;
keep its default localhost address.
