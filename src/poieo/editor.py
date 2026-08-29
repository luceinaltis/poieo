"""A drag-and-drop canvas editor for graphs, as a single self-contained page.

The editor owns only the *logical* layer: nodes, wiring, prompts, conditions,
and which role each node calls. It never edits a binding -- which model runs a
role stays a separate file, which is the whole point of the split.

Node positions round-trip through the optional ``ui:`` block on each node, so a
graph laid out here keeps its layout the next time it is opened.

Saving needs somewhere to put the file. Two adapters:

``jupyter``  PUT through a running Jupyter server's contents API. Useful where
             the only reachable port already belongs to Jupyter.
``none``     No backend: the page offers a download and a copy button.
"""

from __future__ import annotations

import json
from typing import Any

from .binding import BindingSpec
from .graph import GraphSpec
from .viewer import _FONTS, _TOKENS

_CSS = (
    _TOKENS
    + """
*, *::before, *::after { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--ink); overflow: hidden;
  font-family: "IBM Plex Sans", ui-sans-serif, -apple-system, "Segoe UI", sans-serif;
  font-size: 14px; line-height: 1.5; -webkit-font-smoothing: antialiased;
}
code, pre, input, textarea, select, .mono {
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}

.app { display: grid; grid-template-rows: auto 1fr; height: 100%; }
.bar {
  display: flex; align-items: center; gap: .6rem; padding: .55rem .9rem;
  background: var(--panel); border-bottom: 1px solid var(--line); flex-wrap: wrap;
}
.bar h1 { font-family: "IBM Plex Mono", monospace; font-size: .95rem; font-weight: 600;
          margin: 0 .5rem 0 0; letter-spacing: -.01em; }
.spacer { flex: 1; }
button {
  font: inherit; font-size: .82rem; padding: .32rem .7rem; border-radius: 6px;
  border: 1px solid var(--line); background: var(--panel); color: var(--ink); cursor: pointer;
}
button:hover { border-color: var(--muted); }
button:focus-visible, input:focus-visible, textarea:focus-visible, select:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 1px;
}
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button.primary:disabled { opacity: .45; cursor: default; }
button.danger { color: var(--router); }
.status { font-size: .78rem; color: var(--muted); font-family: "IBM Plex Mono", monospace; }
.status.bad { color: var(--router); }
.status.good { color: var(--agent); }

.main { display: grid; grid-template-columns: 1fr 360px; min-height: 0; }
.canvas-wrap { position: relative; overflow: auto; background: var(--bg);
  background-image: radial-gradient(circle, var(--line) 1px, transparent 1px);
  background-size: 22px 22px; }
.canvas { position: relative; width: 2600px; height: 1800px; transform-origin: 0 0; }
.canvas svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.edge { fill: none; stroke: var(--muted); stroke-width: 1.6; }
.edge.branch { stroke: var(--router); }
.edge.ghost { stroke: var(--accent); stroke-dasharray: 5 4; }
.edge-label { font: 500 11px "IBM Plex Mono", monospace; fill: var(--muted); }

.node {
  position: absolute; width: 208px; background: var(--panel);
  border: 1px solid var(--line); border-left: 3px solid var(--line);
  border-radius: 10px; padding: .55rem .65rem .6rem; cursor: grab;
  box-shadow: 0 1px 2px rgba(0,0,0,.06); user-select: none; touch-action: none;
}
.node.agent { border-left-color: var(--agent); }
.node.router { border-left-color: var(--router); }
.node.selected { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-wash); }
.node.entry::after {
  content: "entry"; position: absolute; top: -9px; left: 8px; font-size: .58rem;
  letter-spacing: .09em; text-transform: uppercase; font-weight: 600;
  background: var(--accent-wash); color: var(--accent); padding: .05rem .3rem; border-radius: 3px;
}
.node.dragging { cursor: grabbing; z-index: 20; }
.node .nid { font-family: "IBM Plex Mono", monospace; font-size: .82rem; font-weight: 600;
             overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.node .nmeta { font-size: .68rem; color: var(--muted); font-family: "IBM Plex Mono", monospace;
               margin-top: .15rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.port {
  position: absolute; width: 13px; height: 13px; border-radius: 50%;
  background: var(--panel); border: 2px solid var(--muted); cursor: crosshair;
}
.port.in { top: -7px; left: 50%; margin-left: -6.5px; }
.port.out { bottom: -7px; border-color: var(--agent); }
.port.out.branch { border-color: var(--router); }
.port:hover { background: var(--accent); border-color: var(--accent); }
.port-tip { position: absolute; bottom: -22px; font-size: .6rem; color: var(--muted);
            font-family: "IBM Plex Mono", monospace; white-space: nowrap; transform: translateX(-50%); }

.inspector { border-left: 1px solid var(--line); background: var(--panel);
             overflow-y: auto; padding: 1rem; display: flex; flex-direction: column; gap: .9rem; }
.inspector h2 { font-size: .68rem; text-transform: uppercase; letter-spacing: .1em;
                color: var(--muted); margin: 0; font-weight: 600; }
.field { display: flex; flex-direction: column; gap: .25rem; }
.field label { font-size: .68rem; text-transform: uppercase; letter-spacing: .08em;
               color: var(--muted); font-weight: 600; }
input, textarea, select {
  font-size: .8rem; padding: .35rem .45rem; border-radius: 6px; width: 100%;
  border: 1px solid var(--line); background: var(--bg); color: var(--ink);
}
textarea { resize: vertical; min-height: 84px; line-height: 1.5; }
.row { display: flex; gap: .5rem; }
.row > * { flex: 1; min-width: 0; }
.branch-row { border: 1px solid var(--line); border-radius: 8px; padding: .5rem;
              display: flex; flex-direction: column; gap: .4rem; background: var(--bg); }
.branch-row .head { display: flex; align-items: center; gap: .4rem; }
.branch-row .head span { font-size: .68rem; color: var(--muted); font-family: "IBM Plex Mono", monospace; }
.hint { font-size: .72rem; color: var(--muted); margin: 0; }
.empty { color: var(--muted); font-size: .82rem; }
.roles { display: flex; flex-direction: column; gap: .25rem; font-size: .74rem;
         font-family: "IBM Plex Mono", monospace; }
.roles div { display: flex; justify-content: space-between; gap: .5rem; }
.roles .r { color: var(--accent); }
.roles .m { color: var(--muted); text-align: right; overflow: hidden; text-overflow: ellipsis; }
.problems { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .3rem; }
.problems li { font-size: .74rem; color: var(--router); }

dialog { border: 1px solid var(--line); border-radius: 12px; background: var(--panel);
         color: var(--ink); padding: 1rem; max-width: min(760px, 92vw); width: 760px; }
dialog::backdrop { background: rgba(0,0,0,.45); }
dialog pre { background: var(--sunk); border-radius: 8px; padding: .8rem; overflow: auto;
             max-height: 60vh; font-size: .76rem; margin: .6rem 0; }
@media (max-width: 900px) { .main { grid-template-columns: 1fr; } .inspector { display: none; } }
"""
)

_JS = r"""
const NODE_W = 208, NODE_H = 62;
const state = {
  graph: BOOT.graph,
  bindings: BOOT.bindings,
  save: BOOT.save,
  selected: null,
  dirty: false,
  link: null,
};

const $ = (sel) => document.querySelector(sel);
const canvas = $("#canvas"), svg = $("#edges"), inspector = $("#inspector");

// ---------------------------------------------------------------- layout
function layout() {
  // Any node without saved coordinates gets placed by breadth from the entry,
  // so an unlaid-out graph still opens as a readable diagram.
  const placed = state.graph.nodes.filter((n) => n.ui);
  if (placed.length === state.graph.nodes.length) return;
  const byId = Object.fromEntries(state.graph.nodes.map((n) => [n.id, n]));
  const depth = {}, queue = [[state.graph.entry, 0]];
  while (queue.length) {
    const [id, d] = queue.shift();
    if (!byId[id] || (id in depth && depth[id] <= d)) continue;
    depth[id] = d;
    for (const t of targetsOf(byId[id])) if (t) queue.push([t, d + 1]);
  }
  const rows = {};
  for (const node of state.graph.nodes) {
    const d = depth[node.id] ?? 0;
    (rows[d] = rows[d] || []).push(node);
  }
  for (const [d, group] of Object.entries(rows)) {
    group.forEach((node, i) => {
      if (!node.ui) node.ui = { x: 80 + i * 260, y: 60 + Number(d) * 170 };
    });
  }
}

function targetsOf(node) {
  if (node.type === "router") return [...node.branches.map((b) => b.to), node.default];
  return [node.next];
}

// ---------------------------------------------------------------- rendering
function render() {
  layout();
  renderNodes();
  renderEdges();
  renderInspector();
  validate();
}

function renderNodes() {
  canvas.querySelectorAll(".node").forEach((el) => el.remove());
  for (const node of state.graph.nodes) {
    const el = document.createElement("div");
    el.className = `node ${node.type}`;
    if (node.id === state.graph.entry) el.classList.add("entry");
    if (node.id === state.selected) el.classList.add("selected");
    el.style.left = node.ui.x + "px";
    el.style.top = node.ui.y + "px";
    el.dataset.id = node.id;

    const meta = node.type === "agent"
      ? (node.role || state.graph.default_role || "default")
      : `${node.branches.length} branch${node.branches.length === 1 ? "" : "es"}`;
    el.innerHTML =
      `<div class="nid"></div><div class="nmeta"></div>` +
      `<div class="port in" data-port="in"></div>`;
    el.querySelector(".nid").textContent = node.id;
    el.querySelector(".nmeta").textContent = meta;

    for (const port of outPorts(node)) {
      const dot = document.createElement("div");
      dot.className = "port out" + (port.kind === "branch" ? " branch" : "");
      dot.style.left = port.fx * NODE_W - 6.5 + "px";
      dot.dataset.port = port.key;
      el.appendChild(dot);
      if (port.label) {
        const tip = document.createElement("div");
        tip.className = "port-tip";
        tip.style.left = port.fx * NODE_W + "px";
        tip.textContent = port.label;
        el.appendChild(tip);
      }
    }
    canvas.appendChild(el);
  }
}

function outPorts(node) {
  if (node.type !== "router") return [{ key: "next", kind: "next", fx: 0.5, label: null }];
  const slots = [...node.branches.map((b, i) => ({ key: "b" + i, kind: "branch",
      label: b.label || `#${i}` })), { key: "default", kind: "next", label: "default" }];
  return slots.map((s, i) => ({ ...s, fx: (i + 1) / (slots.length + 1) }));
}

function portPoint(node, key) {
  const ports = outPorts(node);
  const port = ports.find((p) => p.key === key) || ports[0];
  return { x: node.ui.x + port.fx * NODE_W, y: node.ui.y + NODE_H };
}

function renderEdges() {
  const byId = Object.fromEntries(state.graph.nodes.map((n) => [n.id, n]));
  const parts = [];
  for (const node of state.graph.nodes) {
    const edges = node.type === "router"
      ? [...node.branches.map((b, i) => ({ to: b.to, key: "b" + i, label: b.label || "", cls: "branch" })),
         { to: node.default, key: "default", label: "default", cls: "" }]
      : [{ to: node.next, key: "next", label: "", cls: "" }];
    for (const edge of edges) {
      if (!edge.to || !byId[edge.to]) continue;
      const from = portPoint(node, edge.key);
      const target = byId[edge.to];
      const to = { x: target.ui.x + NODE_W / 2, y: target.ui.y };
      const mid = (from.y + to.y) / 2;
      parts.push(`<path class="edge ${edge.cls}" d="M${from.x},${from.y} C${from.x},${mid} ${to.x},${mid} ${to.x},${to.y}" marker-end="url(#arrow)"/>`);
      if (edge.label) {
        parts.push(`<text class="edge-label" x="${(from.x + to.x) / 2}" y="${mid}" text-anchor="middle">${esc(edge.label)}</text>`);
      }
    }
  }
  if (state.link && state.link.cursor) {
    const from = state.link.from;
    parts.push(`<path class="edge ghost" d="M${from.x},${from.y} L${state.link.cursor.x},${state.link.cursor.y}"/>`);
  }
  svg.innerHTML =
    `<defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
       <path d="M0,0 L8,4 L0,8 z" fill="currentColor"/></marker></defs>` + parts.join("");
  svg.style.color = getComputedStyle(document.body).getPropertyValue("--muted");
}

const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------------------------------------------------------------- inspector
function nodeById(id) { return state.graph.nodes.find((n) => n.id === id); }

function renderInspector() {
  const node = nodeById(state.selected);
  if (!node) {
    inspector.innerHTML =
      `<h2>Graph</h2>
       <div class="field"><label>name</label><input id="g-name" value="${esc(state.graph.name)}"></div>
       <div class="field"><label>entry</label>${nodeSelect("g-entry", state.graph.entry, false)}</div>
       <div class="field"><label>max steps</label><input id="g-max" type="number" min="1" value="${state.graph.max_steps}"></div>
       <h2>Roles this graph needs</h2><div class="roles" id="roles"></div>
       <h2>Problems</h2><ul class="problems" id="problems"></ul>
       <p class="hint">Click a node to edit it. Drag a bottom port onto another node to wire it up.</p>`;
    $("#g-name").oninput = (e) => { state.graph.name = e.target.value; touch(); };
    $("#g-entry").onchange = (e) => { state.graph.entry = e.target.value; touch(true); };
    $("#g-max").oninput = (e) => { state.graph.max_steps = Number(e.target.value) || 1; touch(); };
    renderRoles();
    return;
  }

  const rows = [
    `<h2>${node.type} node</h2>`,
    `<div class="field"><label>id</label><input id="n-id" value="${esc(node.id)}"></div>`,
  ];
  if (node.type === "agent") {
    rows.push(
      `<div class="field"><label>role</label><input id="n-role" value="${esc(node.role || "")}" placeholder="${esc(state.graph.default_role || "default")}"></div>`,
      `<div class="field"><label>system</label><textarea id="n-system" placeholder="(none)">${esc(node.system || "")}</textarea></div>`,
      `<div class="field"><label>prompt</label><textarea id="n-prompt" style="min-height:150px">${esc(node.prompt || "")}</textarea></div>`,
      `<div class="row">
         <div class="field"><label>output as</label><input id="n-as" value="${esc(node.output.as || "")}"></div>
         <div class="field"><label>format</label><select id="n-format">
           <option${node.output.format === "text" ? " selected" : ""}>text</option>
           <option${node.output.format === "json" ? " selected" : ""}>json</option></select></div>
       </div>`,
      `<div class="row">
         <div class="field"><label>into state</label><input id="n-state" value="${esc(node.output.into_state || "")}"></div>
         <div class="field"><label>retry</label><input id="n-retry" type="number" min="1" max="10" value="${node.retry.attempts}"></div>
       </div>`,
      `<div class="field"><label>next</label>${nodeSelect("n-next", node.next, true, node.id)}</div>`,
    );
  } else {
    rows.push(`<h2>Branches</h2>`);
    node.branches.forEach((branch, i) => {
      rows.push(
        `<div class="branch-row">
           <div class="head"><span>#${i}</span><div class="spacer"></div>
             <button class="danger" data-del-branch="${i}">remove</button></div>
           <div class="field"><label>when</label><input data-b-when="${i}" value="${esc(branch.when)}"></div>
           <div class="row">
             <div class="field"><label>label</label><input data-b-label="${i}" value="${esc(branch.label || "")}"></div>
             <div class="field"><label>to</label>${nodeSelect(`b-to-${i}`, branch.to, true, node.id)}</div>
           </div>
         </div>`);
    });
    rows.push(
      `<button id="add-branch">+ branch</button>`,
      `<div class="field"><label>default</label>${nodeSelect("n-default", node.default, true, node.id)}</div>`);
  }
  rows.push(`<button class="danger" id="del-node">delete node</button>`);
  inspector.innerHTML = rows.join("");
  wireInspector(node);
}

function nodeSelect(id, value, allowEnd, exclude) {
  const opts = [allowEnd ? `<option value=""${!value ? " selected" : ""}>(end)</option>` : ""];
  for (const n of state.graph.nodes) {
    if (n.id === exclude && !allowEnd) continue;
    opts.push(`<option value="${esc(n.id)}"${n.id === value ? " selected" : ""}>${esc(n.id)}</option>`);
  }
  return `<select id="${id}">${opts.join("")}</select>`;
}

function wireInspector(node) {
  const on = (sel, ev, fn) => { const el = $(sel); if (el) el[ev] = fn; };
  on("#n-id", "onchange", (e) => renameNode(node, e.target.value.trim()));
  on("#n-role", "oninput", (e) => { node.role = e.target.value.trim() || null; touch(true); });
  on("#n-system", "oninput", (e) => { node.system = e.target.value || null; touch(); });
  on("#n-prompt", "oninput", (e) => { node.prompt = e.target.value; touch(); });
  on("#n-as", "oninput", (e) => { node.output.as = e.target.value.trim() || null; touch(); });
  on("#n-format", "onchange", (e) => { node.output.format = e.target.value; touch(); });
  on("#n-state", "oninput", (e) => { node.output.into_state = e.target.value.trim() || null; touch(); });
  on("#n-retry", "oninput", (e) => { node.retry.attempts = Number(e.target.value) || 1; touch(); });
  on("#n-next", "onchange", (e) => { node.next = e.target.value || null; touch(true); });
  on("#n-default", "onchange", (e) => { node.default = e.target.value || null; touch(true); });
  on("#add-branch", "onclick", () => {
    node.branches.push({ when: "true", to: null, label: null });
    touch(true);
  });
  on("#del-node", "onclick", () => deleteNode(node));
  inspector.querySelectorAll("[data-b-when]").forEach((el) => {
    el.oninput = () => { node.branches[+el.dataset.bWhen].when = el.value; touch(); };
  });
  inspector.querySelectorAll("[data-b-label]").forEach((el) => {
    el.oninput = () => { node.branches[+el.dataset.bLabel].label = el.value.trim() || null; touch(); };
  });
  node.branches?.forEach((branch, i) => {
    const el = $(`#b-to-${i}`);
    if (el) el.onchange = () => { branch.to = el.value || null; touch(true); };
  });
  inspector.querySelectorAll("[data-del-branch]").forEach((el) => {
    el.onclick = () => { node.branches.splice(+el.dataset.delBranch, 1); touch(true); };
  });
}

function renderRoles() {
  const box = $("#roles");
  if (!box) return;
  const roles = new Set(state.graph.nodes.filter((n) => n.type === "agent")
    .map((n) => n.role || state.graph.default_role || "default"));
  box.innerHTML = [...roles].sort().map((role) =>
    `<div><span class="r">${esc(role)}</span><span class="m">${esc(state.bindings[role] || "unbound")}</span></div>`
  ).join("") || `<div class="empty">none</div>`;
}

// ---------------------------------------------------------------- mutation
function renameNode(node, next) {
  if (!next || next === node.id) { render(); return; }
  if (state.graph.nodes.some((n) => n !== node && n.id === next)) {
    flash(`id "${next}" is already taken`, true); render(); return;
  }
  const old = node.id;
  node.id = next;
  if (state.graph.entry === old) state.graph.entry = next;
  for (const other of state.graph.nodes) {
    if (other.next === old) other.next = next;
    if (other.default === old) other.default = next;
    for (const branch of other.branches || []) if (branch.to === old) branch.to = next;
  }
  state.selected = next;
  touch(true);
}

function deleteNode(node) {
  state.graph.nodes = state.graph.nodes.filter((n) => n !== node);
  for (const other of state.graph.nodes) {
    if (other.next === node.id) other.next = null;
    if (other.default === node.id) other.default = null;
    for (const branch of other.branches || []) if (branch.to === node.id) branch.to = null;
  }
  if (state.graph.entry === node.id) state.graph.entry = state.graph.nodes[0]?.id || "";
  state.selected = null;
  touch(true);
}

function addNode(type) {
  let n = 1;
  while (state.graph.nodes.some((x) => x.id === `${type}_${n}`)) n++;
  const node = {
    id: `${type}_${n}`, type, role: null, system: null,
    prompt: type === "agent" ? "" : null,
    output: { as: null, format: "text", into_state: null },
    retry: { attempts: 1 }, branches: [], default: null, next: null,
    ui: { x: canvas.parentElement.scrollLeft + 60, y: canvas.parentElement.scrollTop + 60 },
  };
  if (type === "router") node.branches.push({ when: "true", to: null, label: null });
  state.graph.nodes.push(node);
  if (!state.graph.entry) state.graph.entry = node.id;
  state.selected = node.id;
  touch(true);
}

function touch(rerender) {
  state.dirty = true;
  $("#save").disabled = false;
  if (rerender) render(); else { renderEdges(); validate(); }
}

// ---------------------------------------------------------------- validation
function validate() {
  const problems = [];
  const ids = state.graph.nodes.map((n) => n.id);
  const dupes = ids.filter((id, i) => ids.indexOf(id) !== i);
  if (dupes.length) problems.push(`duplicate ids: ${[...new Set(dupes)].join(", ")}`);
  if (!state.graph.entry) problems.push("no entry node");
  else if (!ids.includes(state.graph.entry)) problems.push(`entry "${state.graph.entry}" does not exist`);

  for (const node of state.graph.nodes) {
    if (node.type === "agent" && !(node.prompt || "").trim()) problems.push(`${node.id}: prompt is empty`);
    if (node.type === "router" && !node.branches.length) problems.push(`${node.id}: needs a branch`);
    for (const branch of node.branches || []) {
      if (!(branch.when || "").trim()) problems.push(`${node.id}: a branch has no condition`);
    }
  }
  // Unreachable nodes are the failure the runtime rejects at load time.
  const byId = Object.fromEntries(state.graph.nodes.map((n) => [n.id, n]));
  const seen = new Set(); const stack = [state.graph.entry];
  while (stack.length) {
    const id = stack.pop();
    if (!byId[id] || seen.has(id)) continue;
    seen.add(id);
    for (const t of targetsOf(byId[id])) if (t) stack.push(t);
  }
  const orphans = ids.filter((id) => !seen.has(id));
  if (orphans.length) problems.push(`unreachable: ${orphans.join(", ")}`);

  const box = $("#problems");
  if (box) box.innerHTML = problems.map((p) => `<li>${esc(p)}</li>`).join("") ||
    `<li style="color:var(--agent)">none</li>`;
  const status = $("#status");
  status.textContent = problems.length ? `${problems.length} problem(s)` : "valid";
  status.className = "status " + (problems.length ? "bad" : "good");
  return problems;
}

// ---------------------------------------------------------------- dragging
let drag = null;

canvas.addEventListener("pointerdown", (event) => {
  const portEl = event.target.closest(".port.out");
  const nodeEl = event.target.closest(".node");
  if (!nodeEl) return;
  const node = nodeById(nodeEl.dataset.id);

  if (portEl) {
    // Start wiring: the ghost line follows the pointer until it lands.
    event.stopPropagation();
    state.link = { node, key: portEl.dataset.port, from: portPoint(node, portEl.dataset.port), cursor: null };
    canvas.setPointerCapture(event.pointerId);
    return;
  }
  state.selected = node.id;
  const rect = canvas.getBoundingClientRect();
  drag = { node, dx: (event.clientX - rect.left) - node.ui.x, dy: (event.clientY - rect.top) - node.ui.y };
  nodeEl.classList.add("dragging");
  canvas.setPointerCapture(event.pointerId);
  render();
});

canvas.addEventListener("pointermove", (event) => {
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left, y = event.clientY - rect.top;
  if (state.link) { state.link.cursor = { x, y }; renderEdges(); return; }
  if (!drag) return;
  drag.node.ui.x = Math.max(0, Math.round(x - drag.dx));
  drag.node.ui.y = Math.max(0, Math.round(y - drag.dy));
  const el = canvas.querySelector(`.node[data-id="${CSS.escape(drag.node.id)}"]`);
  el.style.left = drag.node.ui.x + "px";
  el.style.top = drag.node.ui.y + "px";
  renderEdges();
});

canvas.addEventListener("pointerup", (event) => {
  if (state.link) {
    const dropped = document.elementFromPoint(event.clientX, event.clientY)?.closest(".node");
    const target = dropped ? dropped.dataset.id : null;
    const { node, key } = state.link;
    state.link = null;
    if (target && target !== node.id) {
      if (key === "next") node.next = target;
      else if (key === "default") node.default = target;
      else node.branches[+key.slice(1)].to = target;
    } else if (!target) {
      // Dropping on empty canvas clears the edge -- that is how you make an exit.
      if (key === "next") node.next = null;
      else if (key === "default") node.default = null;
      else node.branches[+key.slice(1)].to = null;
    }
    touch(true);
    return;
  }
  if (drag) {
    canvas.querySelector(".dragging")?.classList.remove("dragging");
    drag = null;
    state.dirty = true;
    $("#save").disabled = false;
  }
});

$("#canvas-wrap").addEventListener("pointerdown", (event) => {
  if (!event.target.closest(".node")) { state.selected = null; render(); }
});

// ---------------------------------------------------------------- YAML out
function yamlString(value, indent) {
  if (value === null || value === undefined) return "null";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  const text = String(value);
  if (text.includes("\n")) {
    const pad = " ".repeat(indent + 2);
    return "|\n" + text.replace(/\n+$/, "").split("\n").map((l) => pad + l).join("\n");
  }
  if (text === "" || /^[\s]|[\s]$|^[-?:,\[\]{}#&*!|>'"%@`]|:\s|\s#|^(true|false|null|yes|no|on|off|~)$/i.test(text)
      || /^[-+]?[0-9.]+$/.test(text)) {
    return "'" + text.replace(/'/g, "''") + "'";
  }
  return text;
}

function emitYaml(graph) {
  const out = [];
  const push = (line) => out.push(line);
  push(`name: ${yamlString(graph.name, 0)}`);
  push(`version: ${graph.version || 1}`);
  if (graph.description) push(`description: ${yamlString(graph.description, 0)}`);
  push(`entry: ${yamlString(graph.entry, 0)}`);
  if (graph.default_role && graph.default_role !== "default")
    push(`default_role: ${yamlString(graph.default_role, 0)}`);
  push(`max_steps: ${graph.max_steps}`);
  if (graph.state && Object.keys(graph.state).length) {
    push("state:");
    for (const [k, v] of Object.entries(graph.state)) push(`  ${k}: ${JSON.stringify(v)}`);
  }
  push("");
  push("nodes:");
  for (const node of graph.nodes) {
    push(`  - id: ${yamlString(node.id, 4)}`);
    push(`    type: ${node.type}`);
    if (node.description) push(`    description: ${yamlString(node.description, 4)}`);
    if (node.type === "agent") {
      if (node.role) push(`    role: ${yamlString(node.role, 4)}`);
      if (node.system) push(`    system: ${yamlString(node.system, 4)}`);
      push(`    prompt: ${yamlString(node.prompt || "", 4)}`);
      const out2 = node.output || {};
      const bits = [];
      if (out2.as) bits.push(`      as: ${yamlString(out2.as, 6)}`);
      if (out2.format && out2.format !== "text") bits.push(`      format: ${out2.format}`);
      if (out2.into_state) bits.push(`      into_state: ${yamlString(out2.into_state, 6)}`);
      if (bits.length) { push("    output:"); bits.forEach(push); }
      if (node.retry && node.retry.attempts > 1) {
        push("    retry:");
        push(`      attempts: ${node.retry.attempts}`);
      }
      push(`    next: ${node.next ? yamlString(node.next, 4) : "null"}`);
    } else {
      push("    branches:");
      for (const branch of node.branches) {
        push(`      - when: ${yamlString(branch.when, 8)}`);
        push(`        to: ${branch.to ? yamlString(branch.to, 8) : "null"}`);
        if (branch.label) push(`        label: ${yamlString(branch.label, 8)}`);
      }
      push(`    default: ${node.default ? yamlString(node.default, 4) : "null"}`);
    }
    if (node.ui) push(`    ui: {x: ${Math.round(node.ui.x)}, y: ${Math.round(node.ui.y)}}`);
  }
  return out.join("\n") + "\n";
}

// ---------------------------------------------------------------- saving
async function save() {
  const problems = validate();
  if (problems.length && !confirm(`${problems.length} problem(s) will make this graph fail to load.\n\n${problems.join("\n")}\n\nSave anyway?`)) return;
  const text = emitYaml(state.graph);

  if (state.save.mode === "jupyter") {
    try {
      const response = await fetch(state.save.url, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: "token " + state.save.token },
        body: JSON.stringify({ type: "file", format: "text", content: text }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status} ${await response.text()}`);
      state.dirty = false;
      $("#save").disabled = true;
      flash(`saved ${state.save.path}`);
    } catch (err) {
      flash("save failed: " + err.message, true);
      showYaml(text);
    }
    return;
  }
  showYaml(text);
}

function showYaml(text) {
  $("#yaml-out").textContent = text;
  $("#yaml-dialog").showModal();
}

function flash(message, bad) {
  const status = $("#status");
  status.textContent = message;
  status.className = "status " + (bad ? "bad" : "good");
  setTimeout(validate, 2600);
}

// ---------------------------------------------------------------- wiring up
$("#add-agent").onclick = () => addNode("agent");
$("#add-router").onclick = () => addNode("router");
$("#save").onclick = save;
$("#yaml").onclick = () => showYaml(emitYaml(state.graph));
$("#copy-yaml").onclick = async () => {
  await navigator.clipboard.writeText($("#yaml-out").textContent);
  $("#copy-yaml").textContent = "copied";
  setTimeout(() => ($("#copy-yaml").textContent = "copy"), 1500);
};
$("#download-yaml").onclick = () => {
  const blob = new Blob([$("#yaml-out").textContent], { type: "text/yaml" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = state.save.filename || "graph.yaml";
  a.click();
  URL.revokeObjectURL(a.href);
};
$("#close-yaml").onclick = () => $("#yaml-dialog").close();
window.addEventListener("beforeunload", (e) => { if (state.dirty) e.preventDefault(); });
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); save(); }
  if (e.key === "Delete" && state.selected && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
    deleteNode(nodeById(state.selected));
  }
});

render();
$("#save").disabled = true;
"""


def _boot_payload(graph: GraphSpec, binding: BindingSpec | None, save: dict[str, Any]) -> dict[str, Any]:
    """The editor's initial state: the graph as plain data, plus read-only context."""
    data = graph.model_dump(mode="json")
    for node in data["nodes"]:
        node.setdefault("branches", [])
        node.setdefault("output", {"as": None, "format": "text", "into_state": None})
        node.setdefault("retry", {"attempts": 1, "backoff": 1.0})

    bindings: dict[str, str] = {}
    if binding:
        for role in graph.roles():
            try:
                resolved = binding.resolve(role)
                bindings[role] = resolved.ref
            except Exception:
                bindings[role] = "unbound"
    return {"graph": data, "bindings": bindings, "save": save}


def render_editor(
    graph: GraphSpec,
    binding: BindingSpec | None = None,
    *,
    save: dict[str, Any] | None = None,
) -> str:
    """Build the editor page for one graph."""
    save = save or {"mode": "none", "filename": f"{graph.name}.yaml"}
    # A prompt containing "</script>" would otherwise close the tag early and
    # spill graph text into the document as markup.
    boot = (
        json.dumps(_boot_payload(graph, binding, save), ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )

    body = f"""<div class="app">
  <div class="bar">
    <h1>{graph.name}</h1>
    <button id="add-agent">+ agent</button>
    <button id="add-router">+ router</button>
    <button id="yaml">yaml</button>
    <span id="status" class="status"></span>
    <span class="spacer"></span>
    <button id="save" class="primary">save</button>
  </div>
  <div class="main">
    <div class="canvas-wrap" id="canvas-wrap">
      <div class="canvas" id="canvas"><svg id="edges"></svg></div>
    </div>
    <aside class="inspector" id="inspector"></aside>
  </div>
</div>
<dialog id="yaml-dialog">
  <div class="bar" style="border:none;padding:0 0 .5rem">
    <h1>graph yaml</h1><span class="spacer"></span>
    <button id="copy-yaml">copy</button>
    <button id="download-yaml">download</button>
    <button id="close-yaml">close</button>
  </div>
  <pre id="yaml-out"></pre>
</dialog>
<script>const BOOT = {boot};</script>
<script>{_JS}</script>"""

    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{graph.name} — poieo editor</title>\n{_FONTS}\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )
