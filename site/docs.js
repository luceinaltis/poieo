/* The docs viewer: a sidebar of every document, and the document itself
   fetched from the main branch and rendered here. No copy of any document
   lives on this site -- the moment one merges, this page shows it.

   The renderer is deliberately small. It covers exactly the markdown these
   documents use (headings, paragraphs, fenced code, inline marks, lists two
   levels deep, tables, quotes, rules) and HTML-escapes everything else, so a
   literal <placeholder> in prose can never become a tag. A construct it does
   not know arrives as escaped text: the failure mode is plain, never broken. */

const REPO = "luceinaltis/poieo"
const RAW = `https://raw.githubusercontent.com/${REPO}/main/`
const BLOB = `https://github.com/${REPO}/blob/main/`

const GROUPS = [
  ["Using poieo", [
    ["usage", "The manual", "docs/usage.md"],
    ["design", "What poieo promises", "DESIGN.md"],
  ]],
  ["The code, part by part — for contributors", [
    ["architecture", "Architecture", "docs/architecture.md"],
    ["tasks", "tasks", "docs/tasks.md"],
    ["graph", "graph", "docs/graph.md"],
    ["binding", "binding", "docs/binding.md"],
    ["runtime", "runtime", "docs/runtime.md"],
    ["tools", "tools", "docs/tools.md"],
    ["daemon", "daemon", "docs/daemon.md"],
    ["workspace", "workspace", "docs/workspace.md"],
    ["memory", "memory", "docs/memory.md"],
    ["storage", "storage", "docs/storage.md"],
    ["web", "web", "docs/web.md"],
    ["cli", "cli", "docs/cli.md"],
  ]],
  ["Working here — for contributors", [
    ["agents", "The working agreements", "AGENTS.md"],
    ["contribution", "The longer procedures", "docs/contribution.md"],
    ["conventions", "How the code is written", "docs/conventions.md"],
  ]],
]

const DOCS = new Map(GROUPS.flatMap(([, docs]) => docs.map(([id, title, path]) => [id, { title, path }])))
const BY_FILE = new Map([...DOCS].map(([id, doc]) => [doc.path.split("/").pop().toLowerCase(), id]))
const DEFAULT = "usage"

/* ---------------- markdown, the subset the documents actually use -------- */

function esc(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
}

/** A link's destination, rewritten for where this page lives: another
    document routes inside the viewer, a source path goes to GitHub, and a
    full URL is left alone. */
let activeDoc = DEFAULT // which document href() resolves bare anchors against

function href(target) {
  if (/^[a-z]+:/i.test(target)) return target
  const [path, anchor] = target.split("#")
  if (!path) return `#${activeDoc}${anchor ? "/" + anchor : ""}`
  const id = BY_FILE.get(path.split("/").pop().toLowerCase())
  if (id && path.toLowerCase().endsWith(".md")) return `#${id}${anchor ? "/" + anchor : ""}`
  return BLOB + path.replace(/^(\.\.\/)+/, "")
}

/** A heading's anchor: the text with its markdown marks dropped, kebab-cased. */
function slug(text) {
  return text
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[`*_]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
}

/** Inline marks, applied to already-escaped text. Code first, so nothing
    inside a span of code is treated as emphasis or a link. */
function inline(text) {
  const codes = []
  text = esc(text).replace(/`([^`]+)`/g, (_, code) => {
    codes.push(`<code>${code}</code>`)
    return `\u0000${codes.length - 1}\u0000`
  })
  text = text
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, target) => `<a href="${href(target)}">${label}</a>`)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
  return text.replace(/\u0000(\d+)\u0000/g, (_, i) => codes[i])
}

function table(lines) {
  const cells = (line) => line.replace(/^\||\|$/g, "").split("|").map((cell) => inline(cell.trim()))
  const head = cells(lines[0])
  const rows = lines.slice(2).map(cells)
  return `<table class="md-table"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows
    .map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
    .join("")}</tbody></table>`
}

function render(md, toc) {
  const out = []
  const seen = new Map() // slug -> count, so repeated headings stay unique
  const lines = md.split(/\r?\n/)
  let i = 0
  // list state: a stack of "ul"/"ol", two levels deep in practice
  const stack = []
  const closeLists = (depth) => {
    while (stack.length > depth) out.push(`</${stack.pop()}>`)
  }

  while (i < lines.length) {
    const line = lines[i]

    if (/^```/.test(line)) {
      closeLists(0)
      const lang = line.slice(3).trim()
      const body = []
      i++
      while (i < lines.length && !/^```/.test(lines[i])) body.push(lines[i++])
      i++
      out.push(`<pre${lang ? ` data-lang="${esc(lang)}"` : ""}><code>${esc(body.join("\n"))}</code></pre>`)
      continue
    }

    const heading = line.match(/^(#{1,4})\s+(.*)/)
    if (heading) {
      closeLists(0)
      const level = heading[1].length
      let id = slug(heading[2]) || "section"
      const n = seen.get(id) || 0
      seen.set(id, n + 1)
      if (n) id += `-${n}`
      out.push(`<h${level} id="${id}">${inline(heading[2])}</h${level}>`)
      if (toc && (level === 2 || level === 3)) toc.push({ level, id, text: heading[2] })
      i++
      continue
    }

    if (/^(---|\*\*\*)\s*$/.test(line)) {
      closeLists(0)
      out.push("<hr>")
      i++
      continue
    }

    if (/^\|/.test(line) && /^\|?[\s:|-]+\|/.test(lines[i + 1] || "")) {
      closeLists(0)
      const rows = []
      while (i < lines.length && /^\|/.test(lines[i])) rows.push(lines[i++])
      out.push(table(rows))
      continue
    }

    const item = line.match(/^(\s*)([-*]|\d+\.)\s+(.*)/)
    if (item) {
      const depth = item[1].length >= 2 ? 2 : 1
      const kind = /\d/.test(item[2]) ? "ol" : "ul"
      while (stack.length > depth) out.push(`</${stack.pop()}>`)
      while (stack.length < depth) {
        out.push(`<${kind}>`)
        stack.push(kind)
      }
      // a list item may wrap; the continuation lines are indented prose
      let text = item[3]
      while (/^\s{2,}\S/.test(lines[i + 1] || "") && !/^\s*([-*]|\d+\.)\s/.test(lines[i + 1])) {
        text += " " + lines[++i].trim()
      }
      out.push(`<li>${inline(text)}</li>`)
      i++
      continue
    }
    closeLists(0)

    if (/^>/.test(line)) {
      const body = []
      while (i < lines.length && /^>/.test(lines[i])) body.push(lines[i++].replace(/^>\s?/, ""))
      out.push(`<blockquote>${render(body.join("\n"))}</blockquote>`)
      continue
    }

    if (line.trim() === "") {
      i++
      continue
    }

    // a paragraph runs until a blank line or a construct above
    const body = [line]
    while (
      lines[i + 1] &&
      lines[i + 1].trim() !== "" &&
      !/^(#{1,4}\s|```|\||>|---|\s*([-*]|\d+\.)\s)/.test(lines[i + 1])
    ) {
      body.push(lines[++i])
    }
    out.push(`<p>${inline(body.join(" "))}</p>`)
    i++
  }
  closeLists(0)
  return out.join("\n")
}

/* ---------------- the viewer --------------------------------------------- */

const article = document.getElementById("doc")
const nav = document.getElementById("doc-nav")

function route() {
  const [id, anchor] = location.hash.replace("#", "").split("/")
  return { id: DOCS.has(id) ? id : DEFAULT, anchor: anchor || null }
}

function buildNav() {
  nav.innerHTML = GROUPS.map(
    ([group, docs]) => `
    <div class="nav-group">
      <div class="nav-title">${group}</div>
      ${docs.map(([id, title]) => `<a data-id="${id}" href="#${id}">${title}</a>`).join("")}
    </div>`,
  ).join("")
}

function markActive(id) {
  for (const a of nav.querySelectorAll("a")) a.classList.toggle("active", a.dataset.id === id)
  const folded = document.querySelector(".doc-nav-fold")
  if (folded) {
    folded.open = false
    folded.querySelector("summary").textContent = DOCS.get(id).title
  }
}

async function show(id, anchor) {
  const { title, path } = DOCS.get(id)
  activeDoc = id
  markActive(id)
  document.title = `${title} — poieo docs`

  const cached = sessionStorage.getItem("poieo.doc." + path)
  if (!cached) article.innerHTML = `<p class="doc-state">Fetching ${path} from main…</p>`

  let md = cached
  if (!md) {
    try {
      const answer = await fetch(RAW + path)
      if (!answer.ok) throw new Error(`${answer.status} for ${path}`)
      md = await answer.text()
      sessionStorage.setItem("poieo.doc." + path, md)
    } catch {
      article.innerHTML = `<p class="doc-state">Could not fetch <code>${esc(path)}</code> from the main branch —
        the network, or GitHub, is not answering. <a href="${BLOB + path}">Read it on GitHub</a>,
        or <a href="#${id}" onclick="location.reload()">try again</a>.</p>`
      return
    }
  }
  if (route().id !== id) return // the reader moved on while this fetched
  const toc = []
  article.innerHTML =
    `<p class="doc-meta"><a href="${BLOB + path}">Edit on GitHub</a> · served from <code>main</code></p>` +
    render(md, toc)
  paintToc(id, toc)
  const target = anchor && document.getElementById(anchor)
  if (target) target.scrollIntoView()
  else window.scrollTo(0, 0)
}

/** "On this page", under the document list in the sidebar. */
function paintToc(id, toc) {
  const box = document.getElementById("doc-toc")
  if (!box) return
  box.innerHTML = toc.length
    ? `<div class="nav-title">On this page</div>` +
      toc.map((h) => `<a class="toc-h${h.level}" href="#${id}/${h.id}">${inline(h.text)}</a>`).join("")
    : ""
}

buildNav()
window.addEventListener("hashchange", () => { const r = route(); show(r.id, r.anchor) })
const first = route()
show(first.id, first.anchor)
