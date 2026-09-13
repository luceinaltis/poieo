/* The docs viewer: short user guides, with a separate contributor reference.
   Documents are fetched from the main branch and rendered here; no separate
   copy lives on this site.

   The renderer is deliberately small. It covers exactly the markdown these
   documents use (headings, paragraphs, fenced code, inline marks, lists two
   levels deep, tables, quotes, rules) and HTML-escapes everything else, so a
   literal <placeholder> in prose can never become a tag. A construct it does
   not know arrives as escaped text: the failure mode is plain, never broken. */

const REPO = "luceinaltis/poieo"
const RAW = `https://raw.githubusercontent.com/${REPO}/main/`
const BLOB = `https://github.com/${REPO}/blob/main/`

const USER_GROUPS = [
  ["Documentation", [
    ["get-started", "Get started", "docs/guides/getting-started.md"],
    ["models", "Models", "docs/guides/models.md"],
    ["run-tasks", "Tasks", "docs/guides/tasks.md"],
    ["changes", "Changes", "docs/guides/changes.md"],
    ["troubleshooting", "Troubleshooting", "docs/guides/troubleshooting.md"],
  ]],
]
const CONTRIBUTOR_GROUPS = [
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
    ["design", "Product principles", "DESIGN.md"],
    ["agents", "The working agreements", "AGENTS.md"],
    ["contribution", "The longer procedures", "docs/contribution.md"],
    ["conventions", "How the code is written", "docs/conventions.md"],
  ]],
]
const GROUPS = [...USER_GROUPS, ...CONTRIBUTOR_GROUPS]
const CONTRIBUTOR_IDS = new Set(CONTRIBUTOR_GROUPS.flatMap(([, docs]) => docs.map(([id]) => id)))

const DOCS = new Map(
  GROUPS.flatMap(([group, docs]) => docs.map(([id, title, path]) => [id, { title, path, group }])),
)
const USER_ORDER = USER_GROUPS.flatMap(([, docs]) => docs.map(([id]) => id))
const REFERENCE_ORDER = CONTRIBUTOR_GROUPS.flatMap(([, docs]) => docs.map(([id]) => id))
const BY_PATH = new Map([...DOCS].map(([id, doc]) => [doc.path, id]))
const DEFAULT = "get-started"

// Keep shared links into the former single-page manual useful.
const LEGACY_USAGE = new Map([
  ["install", "get-started/install"],
  ["start-a-project", "get-started/open-the-board"],
  ["create-and-run-a-task", "run-tasks/create-a-task"],
  ["keep-tasks-running", "run-tasks/run-and-schedule"],
  ["let-a-task-apply-its-work", "changes/apply-automatically"],
  ["review-a-change", "changes/review"],
  ["schedule-and-control-work", "run-tasks/run-and-schedule"],
  ["choose-models", "models"],
  ["isolate-model-tools", "tools/isolation"],
  ["journals-and-project-memory", "run-tasks/give-direction"],
  ["grow-a-task-into-a-graph", "run-tasks/add-steps"],
  ["if-something-fails", "troubleshooting"],
])

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
  // Resolve from the source document, including nested guides. A basename
  // lookup would confuse guides/tasks.md with the component docs/tasks.md.
  const source = new URL(target, `https://source.invalid/${DOCS.get(activeDoc).path}`)
  const resolved = source.pathname.slice(1)
  if (resolved === "docs/usage.md") return `#${LEGACY_USAGE.get(anchor) || DEFAULT}`
  const id = BY_PATH.get(resolved)
  if (id) return `#${id}${source.hash ? "/" + source.hash.slice(1) : ""}`
  return BLOB + resolved + source.search + source.hash
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
  const docFor = activeDoc
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
      out.push(
        `<h${level} id="${id}">${inline(heading[2])}` +
          (level > 1 ? `<a class="h-anchor" href="#${docFor}/${id}" aria-label="link here">#</a>` : "") +
          `</h${level}>`,
      )
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
const folded = document.querySelector(".doc-nav-fold")

// Hashes select documents. Skipping the navigation must keep that selection.
document.querySelector(".skip-link")?.addEventListener("click", (event) => {
  event.preventDefault()
  article.focus({ preventScroll: true })
  article.scrollIntoView()
})

// Selecting the current hash still needs to jump back after scrolling away.
nav.addEventListener("click", (event) => {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
  const link = event.target.closest("a")
  if (!link) return
  if (folded) folded.open = false
  if (link.hash === location.hash) {
    event.preventDefault()
    const { id, anchor } = route()
    show(id, anchor)
  }
})

function route() {
  const [id, anchor] = location.hash.replace("#", "").split("/")
  if (id === "usage") {
    const destination = LEGACY_USAGE.get(anchor) || DEFAULT
    history.replaceState(null, "", `#${destination}`)
    const [page, section] = destination.split("/")
    return { id: page, anchor: section || null }
  }
  return { id: DOCS.has(id) ? id : DEFAULT, anchor: anchor || null }
}

function buildNav() {
  const groups = (of) => of.map(
    ([group, docs]) => `
    <div class="nav-group">
      <div class="nav-title">${group}</div>
      ${docs.map(([id, title]) => `<a data-id="${id}" href="#${id}">${title}</a>`).join("")}
    </div>`,
  ).join("")
  nav.innerHTML = `${groups(USER_GROUPS)}
    <details class="nav-contributor">
      <summary>Contributor reference</summary>
      ${groups(CONTRIBUTOR_GROUPS)}
    </details>`
}

function markActive(id) {
  nav.querySelector(".doc-sections")?.remove()
  heads = []
  markLocation(null)
  const contributor = nav.querySelector(".nav-contributor")
  if (contributor) contributor.open = CONTRIBUTOR_IDS.has(id)
  if (folded) folded.open = false
}

function markLocation(anchor) {
  for (const a of nav.querySelectorAll("a")) {
    const selected = anchor ? a.dataset.anchor === anchor : a.dataset.id === activeDoc
    a.classList.toggle("active", selected)
    if (selected) {
      a.setAttribute("aria-current", anchor ? "location" : "page")
      if (folded) folded.querySelector("summary").textContent = a.textContent
    } else a.removeAttribute("aria-current")
  }
}

let latestRequest = 0
async function show(id, anchor) {
  const request = ++latestRequest
  const { title, path } = DOCS.get(id)
  activeDoc = id
  markActive(id)
  document.title = `${title} — poieo docs`

  const cached = sessionStorage.getItem("poieo.doc." + path)
  if (!cached) article.innerHTML = `<p class="doc-state">Loading ${title}…</p>`

  let md = cached
  if (!md) {
    try {
      const answer = await fetch(RAW + path)
      if (!answer.ok) throw new Error(`${answer.status} for ${path}`)
      md = await answer.text()
      sessionStorage.setItem("poieo.doc." + path, md)
    } catch {
      if (request !== latestRequest) return
      article.innerHTML = `<p class="doc-state">Could not fetch <code>${esc(path)}</code> from the main branch —
        the network, or GitHub, is not answering. <a href="${BLOB + path}">Read it on GitHub</a>,
        or <a href="#${id}" onclick="location.reload()">try again</a>.</p>`
      return
    }
  }
  if (request !== latestRequest) return // includes another topic in the same document
  const toc = []
  const group = DOCS.get(id).group
  article.innerHTML =
    `<p class="doc-meta"><span class="doc-crumb">${group}</span>` +
    `<a href="${BLOB + path}">Edit on GitHub</a></p>` +
    render(md, toc) +
    pager(id)
  if (CONTRIBUTOR_IDS.has(id)) {
    paintSections(id, toc)
    watchHeadings()
  }
  const target = anchor && document.getElementById(anchor)
  if (target) target.scrollIntoView()
  else window.scrollTo(0, 0)
}

/** Long references expose their headings. Guides keep a stable page list. */
function paintSections(id, toc) {
  if (!toc.length) return
  const sections = document.createElement("div")
  sections.className = "doc-sections"
  sections.innerHTML = toc
    .map((h) => `<a class="toc-h${h.level}" data-anchor="${h.id}" href="#${id}/${h.id}">${inline(h.text)}</a>`)
    .join("")
  nav.querySelector(`[data-id="${id}"]`).after(sections)
}

/** Read on within the guide or reference, in the sidebar's own order. */
function pager(id) {
  const order = CONTRIBUTOR_IDS.has(id) ? REFERENCE_ORDER : USER_ORDER
  const i = order.indexOf(id)
  const cell = (which, of) =>
    of
      ? `<a class="pager-${which}" href="#${of}"><span>${which === "prev" ? "← Previous" : "Next →"}</span>${DOCS.get(of).title}</a>`
      : `<span></span>`
  return `<nav class="pager" aria-label="Read next">${cell("prev", order[i - 1])}${cell("next", order[i + 1])}</nav>`
}

/** The outline marker follows the reader: the last heading above the fold
    owns the active line. A scroll listener, throttled to frames — a dozen
    getBoundingClientRect calls per frame is nothing, and unlike an observer
    it cannot miss a programmatic jump. */
let heads = []
function watchHeadings() {
  heads = [...article.querySelectorAll("h2[id], h3[id]")]
  markScroll()
}

let ticking = false
function markScroll() {
  if (ticking || !heads.length) return
  ticking = true
  requestAnimationFrame(() => {
    ticking = false
    let current = null
    // Use the same offset as anchor scrolling, including the taller phone bar.
    const top = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0
    for (const h of heads) if (h.getBoundingClientRect().top <= top + 1) current = h.id
    markLocation(current)
  })
}
window.addEventListener("scroll", markScroll, { passive: true })

buildNav()
window.addEventListener("hashchange", () => { const r = route(); show(r.id, r.anchor) })
const first = route()
show(first.id, first.anchor)
