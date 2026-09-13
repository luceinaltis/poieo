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

Use `poieo config` to inspect the current selection. Hosted credentials stay
in environment variables; model files store their names, not secret values.
For an endpoint discovery does not find, see
[provider configuration](../binding.md#configuration).

## Use small and large models together

A simple prompt uses the default model. For [a task with steps](tasks.md#add-steps),
give model steps roles such as `reader` and `reviewer`. Declare the roles in
the [model file](../binding.md#role-resolution), then assign a model to an
existing role:

```bash
poieo config use <provider>/<model> --role reviewer
```

Restart the daemon after changing model assignments. poieo does not choose
models automatically. Check run results, tests, and usage before deciding
whether an assignment improves cost and accuracy. Cost appears when the
provider reports it or you configure model prices.
