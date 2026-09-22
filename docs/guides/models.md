# Models

Use small models for routine steps and larger ones where the work needs them.
You choose the assignments; compare results against your own checks.

## Connect a model

Start your local model server or set your cloud provider's credential
environment variable. From the board's project folder, run:

```bash
poieo config add
poieo config models
poieo config use <provider>/<model>
poieo check
```

`config add` detects available endpoints. `config models` lists the models
served by your configured endpoints. Replace `<provider>/<model>` with one
of those choices. `check` tests the connection.

If you set credentials after opening the board, restart the daemon from
that terminal.

Use `poieo config` to inspect the current selection. Hosted credentials stay
in environment variables; model files store their names, not secret values.
For an endpoint discovery does not find, see
[provider configuration](../binding.md#configuration).

## Try a model from the board

The board's `chat` button, beside the project name, opens a conversation
with the project's default model, the one a plain task uses. Each reply says
which model answered, so a change made with `config use` shows up on the
next message. Use it to check that an endpoint answers, and how a model
handles your language, before giving it a task.

The conversation stays on the page. Nothing is saved, no run is recorded,
and the model has no tools there, so it cannot read or change your files.

## Use small and large models together

A simple prompt uses the default model. For [a task with steps](tasks.md#add-steps),
give model steps roles such as `reader` and `reviewer`. Declare the roles in
the [model file](../binding.md#role-resolution), then assign a model to an
existing role:

```bash
poieo config use <provider>/<model> --role reviewer
```

New assignments take effect on the next run. poieo does not choose models
automatically. Check run results, tests, and usage before deciding
whether an assignment improves cost and accuracy. Cost appears when the
provider reports it or you configure model prices.
