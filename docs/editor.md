# Graph editor

`src/poieo/editor.py`

`render_editor(graph, binding=None, *, save=None)` returns one self-contained
HTML document: a drag-and-drop canvas for a single graph, its CSS and its
JavaScript inline, with no build step and no server of its own. It shares the
fonts and colour tokens of the read-only renderer in `viewer.py`.

The editor owns the logical layer only — nodes, wiring, prompts, conditions and
the role each node names. It never edits a binding; which model serves a role
stays a separate file, which is the point of the split
([binding.md](binding.md)). A binding passed in is read-only context: each role
the graph needs is resolved to a model reference, and a role that cannot resolve
is reported as `unbound` rather than raising.

## The page

`_boot_payload` turns the graph into plain data and embeds it as `const BOOT`.
Two contracts hold there:

- Every node carries `branches`, `output` and `retry`, defaulted if the schema
  left them out, because the page writes into those fields without guarding.
- `</` becomes `<\/`, and U+2028/U+2029 are escaped, so a prompt containing
  `</script>` cannot close the tag and spill graph text into the document as
  markup. The browser still decodes the original text.

Node coordinates round-trip through the optional `ui:` block on each node, so a
graph laid out here opens the same way next time. A node with no coordinates is
placed by breadth from the entry, so an unlaid-out graph still opens readable.

The page validates continuously — duplicate ids, a missing or dangling entry, an
empty agent prompt, a router with no branch or a branch with no condition, and
unreachable nodes. This mirrors what the runtime refuses at load time;
[graph.md](graph.md) remains the authority, and the page only warns.

## Save adapters

Python never writes the graph file. It renders a page, and the page saves
through one of two adapters named by `save["mode"]`. Both emit the same YAML
from the same client-side emitter, and both ask for confirmation first when
validation found problems.

| mode | how it saves | what it guarantees |
|---|---|---|
| `jupyter` | `PUT save["url"]` with `Authorization: token <save["token"]>` and a `{type, format, content}` body — the Jupyter contents API | on success the page is clean and `save` disables; on any non-2xx it flashes the error and opens the YAML dialog, so the text is never lost |
| `none` | no backend: `save` opens the YAML dialog with copy and download buttons | the graph text is always reachable by hand; the download is named `save["filename"]`, or `graph.yaml` |

`save["url"]` is site-relative on purpose: the page saves through whatever origin
served it, so a proxy hostname never has to be known when the page is rendered.

With no `save` argument the mode is `none`, so a page rendered by a caller that
did not choose an adapter offers download and copy rather than writing anywhere.

## Choosing one: `poieo edit`

`cli.py` picks the adapter and renders the page. `--save-via` takes `auto`
(default), `jupyter` or `none`.

- `auto` and `jupyter` look for a running server with `jupyter server list
  --json` and take the first entry that reports a token; `--token` and
  `--jupyter-root` override what it found, and supply it when there is none.
- `jupyter` needs both a token and a root, and needs the graph to sit under that
  root — the save path is the graph's path relative to it. `--save-via jupyter`
  fails and names the reason, no server or a graph outside the root; `auto`
  falls back to `none` and warns that the page offers download and copy instead.
- A task card is refused before anything is rendered: the editor saves back over
  what it opened, and a task is not a graph. Run `poieo eject` first.

The page is written to `--output` or `<graph name>-edit.html`, and the command
prints where it saves. `--serve` serves it over http (`--host`, `--port`, both
loopback by default) instead of leaving the reader to open a `file://` URL.

## Limits

- The YAML emitter is hand-written and emits only the fields it knows.
  Comments and unrecognised keys in the original file do not survive a save.
- The inspector and the emitter know `agent` and `router` nodes. A `command` or
  `confirm` node opened here is not round-tripped faithfully; edit those files
  directly until the editor grows them.
- In `jupyter` mode the rendered page contains a live Jupyter token. It is a
  local file with a credential in it: do not commit or share the output.
