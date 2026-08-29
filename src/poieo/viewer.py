"""Renders a graph as a self-contained HTML page.

This is the read-only half of the web editor that comes later: the same graph
schema, drawn instead of printed. The page embeds its own CSS and needs no
build step -- the only external asset is the mermaid bundle, and even that is
optional (``embed_mermaid_script=False`` produces a page for a host that
renders ``<pre class="mermaid">`` itself).
"""

from __future__ import annotations

import html
from typing import Iterable

from .binding import BindingSpec
from .graph import GraphSpec, NodeSpec

MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs"


def mermaid_source(graph: GraphSpec) -> str:
    """A mermaid flowchart for one graph.

    Terminal edges get their own end marker per branch, so two different exit
    conditions do not collapse into one node in the drawing.
    """
    lines = ["flowchart TD"]
    ends: list[str] = []

    for node in graph.nodes:
        label = html.escape(node.id)
        if node.type == "router":
            lines.append(f'    {node.id}{{"{label}"}}')
        elif node.type == "agent":
            role = html.escape(node.role or graph.default_role)
            lines.append(f'    {node.id}["{label}<br/><small>{role}</small>"]')
        else:
            # A step that calls no model has no role to draw, and drawing the
            # default would name one it never asks for.
            lines.append(f'    {node.id}["{label}<br/><small>{node.type}</small>"]')

    for node in graph.nodes:
        if node.next:
            lines.append(f"    {node.id} --> {node.next}")
        for index, branch in enumerate(node.branches):
            label = html.escape((branch.label or branch.when).replace('"', "'"))
            if branch.to:
                target = branch.to
            else:
                target = f"{node.id}__end{index}"
                ends.append(target)
            lines.append(f'    {node.id} -->|"{label}"| {target}')
        if node.type == "router":
            if node.default:
                lines.append(f'    {node.id} -->|"default"| {node.default}')
            else:
                target = f"{node.id}__end_default"
                ends.append(target)
                lines.append(f'    {node.id} -->|"default"| {target}')

    for end in ends:
        lines.insert(1, f'    {end}(["end"])')

    lines.append(f"    class {graph.entry} entry")
    if ends:
        lines.append(f"    class {','.join(ends)} terminal")
    lines.append("    classDef entry stroke-width:3px")
    lines.append("    classDef terminal stroke-dasharray:4 3")
    return "\n".join(lines)


def _chip(label: str, value: str) -> str:
    return (
        f'<span class="chip"><span class="chip-k">{html.escape(label)}</span>'
        f"{html.escape(value)}</span>"
    )


def _node_card(node: NodeSpec, graph: GraphSpec, binding: BindingSpec | None) -> str:
    parts = [f'<article class="card {node.type}" id="node-{html.escape(node.id)}">']
    parts.append('<header class="card-head">')
    parts.append(f'<h3>{html.escape(node.id)}</h3>')
    parts.append(f'<span class="tag tag-{node.type}">{node.type}</span>')
    if node.id == graph.entry:
        parts.append('<span class="tag tag-entry">entry</span>')
    parts.append("</header>")

    if node.description:
        parts.append(f'<p class="desc">{html.escape(node.description)}</p>')

    if node.type == "agent":
        role = node.role or graph.default_role
        meta = [_chip("role", role)]
        if binding:
            try:
                meta.append(_chip("runs on", binding.resolve(role, node.params or None).describe().split(" -> ")[1]))
            except Exception:
                meta.append(_chip("runs on", "unbound"))
        if node.output.as_:
            meta.append(_chip("as", node.output.as_))
        if node.output.format != "text":
            meta.append(_chip("format", node.output.format))
        if node.output.into_state:
            meta.append(_chip("state", node.output.into_state))
        if node.retry.attempts > 1:
            meta.append(_chip("retry", f"{node.retry.attempts}x"))
        parts.append(f'<div class="chips">{"".join(meta)}</div>')

        if node.system:
            parts.append('<div class="block"><span class="block-k">system</span>')
            parts.append(f"<pre>{html.escape(node.system.strip())}</pre></div>")
        parts.append('<div class="block"><span class="block-k">prompt</span>')
        parts.append(f"<pre>{html.escape((node.prompt or '').strip())}</pre></div>")
        parts.append(
            f'<p class="edge">next &rarr; <code>{html.escape(node.next or "end")}</code></p>'
        )
    else:
        parts.append('<ul class="branches">')
        for branch in node.branches:
            target = branch.to or "end"
            label = (
                f'<span class="label">{html.escape(branch.label)}</span>'
                if branch.label
                else ""
            )
            parts.append(
                f'<li><code class="cond">{html.escape(branch.when)}</code>{label}'
                f'<span class="hop">&rarr;</span><code>{html.escape(target)}</code></li>'
            )
        parts.append(
            f'<li class="fallback">default<span class="hop">&rarr;</span>'
            f'<code>{html.escape(node.default or "end")}</code></li>'
        )
        parts.append("</ul>")

    parts.append("</article>")
    return "".join(parts)


def _binding_table(graph: GraphSpec, binding: BindingSpec) -> str:
    """One row per logical-to-physical hop: role, endpoint, model, parameters."""
    rows = []
    for role in sorted(graph.roles()):
        try:
            resolved = binding.resolve(role)
            endpoint = (
                f"<code>{html.escape(resolved.provider_name)}</code>"
                f"<span class='muted'> {html.escape(resolved.provider.type)}</span>"
            )
            model = f"<code>{html.escape(resolved.model)}</code>"
            params = ", ".join(f"{k}={v}" for k, v in sorted(resolved.params.items()))
        except Exception as exc:
            endpoint = "<span class='bad'>unbound</span>"
            model = "<span class='muted'>&mdash;</span>"
            params = html.escape(str(exc))
        rows.append(
            f"<tr><td><code class='role'>{html.escape(role)}</code>"
            f"<span class='hop'>&rarr;</span></td>"
            f"<td>{endpoint}</td><td>{model}</td>"
            f"<td class='muted'>{html.escape(params) if params else '&mdash;'}</td></tr>"
        )
    return (
        "<table class='wire'><thead><tr><th>role</th><th>endpoint</th>"
        f"<th>model</th><th>parameters</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=IBM+Plex+Mono:wght@400;500;600&"
    'family=IBM+Plex+Sans:wght@400;500;600;700&display=swap">'
)

# A schematic palette, not a document one: two hues carry meaning (green = a node
# that does work, amber = a node that decides) and steel blue marks the seams
# where the logical layer meets the physical one.
# Shared palette. The editor imports these so both surfaces are one product.
_TOKENS = """
:root {
  --bg: #f7f8f6; --panel: #ffffff; --sunk: #eef1ee;
  --ink: #16191c; --muted: #5f6a70; --line: #dde2e0; --line-soft: #e9ecea;
  --agent: #1c6e5a; --router: #a86a12; --accent: #1f5fa8;
  --agent-wash: #e8f2ee; --router-wash: #f7eede; --accent-wash: #e6eefa;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14171a; --panel: #1c2024; --sunk: #23282c;
    --ink: #e6eae8; --muted: #8b9599; --line: #2f353a; --line-soft: #262c31;
    --agent: #4fb99c; --router: #d99a3c; --accent: #6ba6e8;
    --agent-wash: #17302a; --router-wash: #322715; --accent-wash: #182636;
  }
}
:root[data-theme="dark"] {
  --bg: #14171a; --panel: #1c2024; --sunk: #23282c;
  --ink: #e6eae8; --muted: #8b9599; --line: #2f353a; --line-soft: #262c31;
  --agent: #4fb99c; --router: #d99a3c; --accent: #6ba6e8;
  --agent-wash: #17302a; --router-wash: #322715; --accent-wash: #182636;
}

"""

_CSS = _TOKENS + """
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font-family: "IBM Plex Sans", ui-sans-serif, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px; line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
code, pre, .mono { font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace; }

.wrap { max-width: 1080px; margin: 0 auto; padding: 3rem 1.25rem 6rem; display: flex; flex-direction: column; gap: 3.5rem; }
.graph { display: flex; flex-direction: column; gap: 1.75rem; }
.graph + .graph { padding-top: 3.5rem; border-top: 1px solid var(--line); }

.head { display: flex; flex-direction: column; gap: .6rem; }
h1 { font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace;
     font-size: clamp(1.5rem, 3.5vw, 2rem); font-weight: 600; margin: 0;
     letter-spacing: -.02em; text-wrap: balance; }
.lede { color: var(--muted); margin: 0; max-width: 62ch; }
h2 { font-size: .72rem; text-transform: uppercase; letter-spacing: .11em;
     color: var(--muted); margin: 0 0 .85rem; font-weight: 600; }
h3 { font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace;
     font-size: .95rem; font-weight: 600; margin: 0; }

.chips { display: flex; flex-wrap: wrap; gap: .4rem; }
.chip { font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace; font-size: .74rem;
        background: var(--sunk); border-radius: 5px; padding: .2rem .5rem;
        font-variant-numeric: tabular-nums; }
.chip-k { color: var(--muted); margin-right: .35rem; }

.diagram { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
           padding: 1.75rem 1rem; overflow-x: auto; }
.diagram > * { min-width: max-content; margin: 0 auto; }
.diagram pre { background: none; padding: 0; margin: 0; }

.wire { width: 100%; border-collapse: collapse; font-size: .85rem;
        background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
        overflow: hidden; }
.wire th { text-align: left; font-size: .68rem; text-transform: uppercase;
           letter-spacing: .09em; color: var(--muted); font-weight: 600;
           padding: .7rem .9rem; background: var(--sunk); }
.wire td { padding: .65rem .9rem; border-top: 1px solid var(--line-soft); vertical-align: baseline; }
.wire tr:first-child td { border-top: none; }
.role { color: var(--accent); font-weight: 500; }
.hop { color: var(--muted); padding: 0 .1rem; }

.cards { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
        padding: 1.05rem 1.15rem 1.2rem; display: flex; flex-direction: column; gap: .75rem;
        border-left: 3px solid var(--line); }
.card.agent { border-left-color: var(--agent); }
.card.router { border-left-color: var(--router); }
.card-head { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.tag { font-size: .64rem; text-transform: uppercase; letter-spacing: .09em; font-weight: 600;
       padding: .18rem .45rem; border-radius: 4px; }
.tag-agent { color: var(--agent); background: var(--agent-wash); }
.tag-router { color: var(--router); background: var(--router-wash); }
.tag-entry { color: var(--accent); background: var(--accent-wash); }
.desc { color: var(--muted); font-size: .87rem; margin: 0; }

.block { display: flex; flex-direction: column; gap: .3rem; }
.block-k { font-size: .64rem; text-transform: uppercase; letter-spacing: .09em; color: var(--muted); font-weight: 600; }
pre { background: var(--sunk); border-radius: 8px; padding: .75rem .85rem; margin: 0;
      overflow-x: auto; font-size: .8rem; line-height: 1.55; white-space: pre-wrap;
      word-break: break-word; }

.branches { list-style: none; margin: 0; padding: 0; font-size: .84rem;
            display: flex; flex-direction: column; }
.branches li { padding: .5rem 0; border-top: 1px solid var(--line-soft);
               display: flex; align-items: baseline; gap: .4rem; flex-wrap: wrap; }
.branches li:first-child { border-top: none; padding-top: 0; }
.cond { background: var(--sunk); padding: .12rem .35rem; border-radius: 4px; }
.label { color: var(--router); font-size: .76rem; font-weight: 500; }
.fallback { color: var(--muted); }
.edge { margin: 0; font-size: .82rem; color: var(--muted); }
.muted { color: var(--muted); }
.bad { color: var(--router); font-weight: 500; }

@media (max-width: 640px) {
  .wrap { padding: 2rem 1rem 4rem; gap: 2.5rem; }
  .cards { grid-template-columns: 1fr; }
}
"""

_SCRIPT = f"""
import mermaid from "{MERMAID_CDN}";
const dark = matchMedia("(prefers-color-scheme: dark)").matches;
mermaid.initialize({{
  startOnLoad: true,
  securityLevel: "strict",
  theme: dark ? "dark" : "neutral",
  flowchart: {{ curve: "basis", nodeSpacing: 45, rankSpacing: 55 }},
}});
"""


def render_page(
    graphs: Iterable[GraphSpec],
    binding: BindingSpec | None = None,
    *,
    title: str | None = None,
    embed_mermaid_script: bool = True,
    full_document: bool = True,
) -> str:
    """Build the viewer page for one or more graphs."""
    graphs = list(graphs)
    page_title = title or (
        graphs[0].name if len(graphs) == 1 else f"{len(graphs)} workflows"
    )

    body: list[str] = ['<div class="wrap">']
    for graph in graphs:
        body.append('<section class="graph">')
        body.append('<header class="head">')
        body.append(f"<h1>{html.escape(graph.name)}</h1>")
        if graph.description:
            body.append(f'<p class="lede">{html.escape(graph.description)}</p>')
        chips = [
            _chip("version", str(graph.version)),
            _chip("entry", graph.entry),
            _chip("nodes", str(len(graph.nodes))),
            _chip("max steps", str(graph.max_steps)),
        ]
        body.append(f'<div class="chips">{"".join(chips)}</div></header>')

        body.append('<section><h2>Flow</h2><div class="diagram">')
        body.append(f'<pre class="mermaid">{html.escape(mermaid_source(graph))}</pre>')
        body.append("</div></section>")

        if binding:
            body.append(
                f"<section><h2>Runs on &mdash; {html.escape(binding.name)} binding</h2>"
                + _binding_table(graph, binding)
                + "</section>"
            )

        body.append('<section><h2>Nodes</h2><div class="cards">')
        for node in graph.nodes:
            body.append(_node_card(node, graph, binding))
        body.append("</div></section></section>")
    body.append("</div>")

    script = f'<script type="module">{_SCRIPT}</script>' if embed_mermaid_script else ""
    content = f"<style>{_CSS}</style>\n" + "\n".join(body) + "\n" + script

    if not full_document:
        # For a host that supplies the document shell and renders mermaid itself.
        return f"<title>{html.escape(page_title)}</title>\n{_FONTS}\n{content}"

    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(page_title)}</title>\n{_FONTS}\n</head>\n<body>\n"
        f"{content}\n</body>\n</html>\n"
    )
