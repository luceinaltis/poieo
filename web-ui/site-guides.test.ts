import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { afterEach, expect, test, vi } from "vitest"

const ROOT = resolve(process.cwd(), "..")
const GUIDES = [
  ["get-started", "Get started", "getting-started"],
  ["models", "Models", "models"],
  ["run-tasks", "Tasks", "tasks"],
  ["changes", "Changes", "changes"],
  ["troubleshooting", "Troubleshooting", "troubleshooting"],
]

afterEach(() => {
  sessionStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

test("short guides have separate articles, stable page selection, and working old and relative links", async () => {
  const page = readFileSync(resolve(ROOT, "site/docs.html"), "utf8")
  document.body.innerHTML = new DOMParser().parseFromString(page, "text/html").body.innerHTML
  Element.prototype.scrollIntoView = vi.fn()
  Object.defineProperty(window, "scrollTo", { configurable: true, value: vi.fn() })
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { callback(0); return 1 })
  const fetcher = vi.fn(async (url: string) => ({
    ok: true,
    text: async () => readFileSync(resolve(ROOT, new URL(url).pathname.replace("/luceinaltis/poieo/main/", "")), "utf8"),
  }))
  vi.stubGlobal("fetch", fetcher)
  history.replaceState(null, "", "#get-started")
  new Function(readFileSync(resolve(ROOT, "site/docs.js"), "utf8"))()
  const nav = document.getElementById("doc-nav")!
  const fold = document.querySelector<HTMLDetailsElement>(".doc-nav-fold")!
  const visit = (hash: string) => {
    history.replaceState(null, "", hash)
    window.dispatchEvent(new HashChangeEvent("hashchange"))
  }
  const loaded = async (title: string) => {
    await vi.waitFor(() => expect(document.querySelector("#doc h1")?.textContent).toBe(title))
  }

  expect([...nav.querySelectorAll(":scope > .nav-group > a")].map((a) => a.textContent))
    .toEqual(GUIDES.map(([, title]) => title))
  for (const [id, title, file] of GUIDES) {
    if (id !== "get-started") visit(`#${id}`)
    await loaded(title)
    expect(fetcher).toHaveBeenCalledWith(expect.stringContaining(`/docs/guides/${file}.md`))
    expect(document.querySelectorAll("#doc h1")).toHaveLength(1)
    expect(nav.querySelector(".doc-sections")).toBeNull()
    expect(document.querySelector<HTMLDetailsElement>(".nav-contributor")!.open).toBe(false)
    const section = document.querySelector("#doc h2")!.id
    visit(`#${id}/${section}`)
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
    window.dispatchEvent(new Event("scroll"))
    expect([...nav.querySelectorAll("a.active")].map((a) => a.textContent)).toEqual([title])
    expect(nav.querySelector('a[aria-current="page"]')?.textContent).toBe(title)
    expect(fold.querySelector("summary")?.textContent).toBe(title)
  }
  expect(document.querySelector(".pager-next")).toBeNull()
  visit("#get-started")
  await loaded("Get started")
  expect(document.querySelector(".pager-prev")).toBeNull()
  expect(document.querySelector(".pager-next")?.getAttribute("href")).toBe("#models")

  // Bookmarked sections must still lead to the actual topic after the split.
  for (const [old, current] of [
    ["", "get-started"],
    ["/missing", "get-started"],
    ["/__proto__", "get-started"],
    ["/install", "get-started/install"],
    ["/start-a-project", "get-started/open-the-board"],
    ["/create-and-run-a-task", "run-tasks/create-a-task"],
    ["/keep-tasks-running", "run-tasks/run-and-schedule"],
    ["/let-a-task-apply-its-work", "changes/apply-automatically"],
    ["/review-a-change", "changes/review"],
    ["/schedule-and-control-work", "run-tasks/run-and-schedule"],
    ["/choose-models", "models"],
    ["/isolate-model-tools", "tools/isolation"],
    ["/journals-and-project-memory", "run-tasks/give-direction"],
    ["/grow-a-task-into-a-graph", "run-tasks/add-steps"],
    ["/if-something-fails", "troubleshooting"],
  ]) {
    visit(`#usage${old}`)
    await vi.waitFor(() => expect(location.hash).toBe(`#${current}`))
    const [id, anchor] = current.split("/")
    await loaded(id === "tools" ? "Tools and isolation" : GUIDES.find(([key]) => key === id)![1])
    if (anchor) expect(document.querySelector(`#doc #${anchor}`)).not.toBeNull()
  }

  // The guide and component can have the same filename in different folders.
  sessionStorage.clear()
  fetcher.mockResolvedValue({ ok: true, text: async () => `# Link checks

[Models](models.md)
[Tasks reference](../tasks.md#card-shape)
[This page](#add-steps)
[Old guide](../usage.md#choose-models)
[Doc index](../README.md)
[Source](../../src/poieo/card.py#L10)
[Website](https://example.com/guide)
` })
  visit("#run-tasks")
  await loaded("Link checks")
  const links = [...document.querySelectorAll<HTMLAnchorElement>("#doc p a")]
  const target = (label: string) => links.find((a) => a.textContent === label)?.getAttribute("href")
  expect(target("Models")).toBe("#models")
  expect(target("Tasks reference")).toBe("#tasks/card-shape")
  expect(target("This page")).toBe("#run-tasks/add-steps")
  expect(target("Old guide")).toBe("#models")
  expect(target("Doc index")).toBe("https://github.com/luceinaltis/poieo/blob/main/docs/README.md")
  expect(target("Source")).toBe("https://github.com/luceinaltis/poieo/blob/main/src/poieo/card.py#L10")
  expect(target("Website")).toBe("https://example.com/guide")
})
