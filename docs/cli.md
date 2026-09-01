# Command line interface

`src/poieo/cli.py`, `src/poieo/rebind.py`

The CLI is a Typer interface over the same project, runtime, daemon, binding,
memory, store, and workspace functions used elsewhere. It should parse input,
choose an output shape, and translate known poieo errors; business rules belong
to their component.

Start with [usage.md](usage.md) and use `poieo --help` or a command's `--help`
for the complete option reference.

## Command surface

The main help page follows the user's work:

- **Setting up** — `init`, `validate`, `check`, and `config`;
- **Your tasks** — `run`, `daemon`, `tasks`, `note`, `asking`, and `answer`;
- **What happened** — `memory`, `learn`, and `runs`.

`config models` asks configured endpoints for their current catalogues;
`config add` declares a newly discovered or explicitly addressed endpoint;
`config use` points the default or an existing role at a declared model. Adding
and choosing are separate operations. `runs list` and `runs show` read the
append-only store.

Advanced supported commands remain hidden from the front page where they are
not part of first use: they inspect expansion, open or edit source files, eject
a card to an explicit graph, discard an isolated task environment, or report
the version.
Their discoverability comes from the relevant guide and direct help, not a
second tutorial here.

## Discovery and paths

An explicit argument or flag wins. Otherwise a command searches upward for the
nearest `poieo.yaml` and fills missing store, binding, and task locations from
the project. Paths inside a marker, card, graph, or binding resolve relative to
the file that owns them after user-home expansion.

`poieo daemon` accepts multiple project or task-folder arguments. Project
display names must be unique in one daemon; task names are unique only inside
their project. Commands that inspect or control a task use both identities when
several projects are resident. `asking` and `answer` communicate with a running
daemon because pending questions belong to its runners and persisted run state.

## Writes

`init` never overwrites an existing file and validates what it leaves. Normal
initialization detects reachable models once; mock initialization gives a
non-billing scripted path. Detection later happens only through an explicit
catalogue or add command.

Binding edits use the shared rebind functions. They preserve YAML comments and
formatting around the changed value, validate the resulting binding, and put
the original bytes back if the edit cannot load. They never accept a credential
value. Card editing and Git review similarly delegate to their owning
components.

## Output and failure

Human output uses the product vocabulary and actionable error messages.
Commands that offer `--json` keep a stable machine-readable shape and send no
decorative output into it. A `PoieoError` is rendered without a traceback;
unexpected exceptions retain normal failure semantics. Broken pipes exit
quietly, and legacy Windows console encoding replaces only characters it cannot
represent rather than failing after the work succeeded.

New commands should compose existing library operations. If a command needs a
new rule, add that rule to the component that also serves the daemon or web API,
then make the CLI a caller.
