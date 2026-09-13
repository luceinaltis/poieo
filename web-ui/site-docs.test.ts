import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { afterEach, expect, test, vi } from "vitest"

const SCRIPT = readFileSync(resolve(process.cwd(), "../site/docs.js"), "utf8")
const PAGE = readFileSync(resolve(process.cwd(), "../site/docs.html"), "utf8")

afterEach(() => {
  location.hash = ""
  sessionStorage.clear()
  document.documentElement.style.removeProperty("scroll-padding-top")
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

test("docs navigation follows the document and headings below the sticky header", async () => {
  document.body.innerHTML = new DOMParser().parseFromString(PAGE, "text/html").body.innerHTML
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(
    () => new DOMRect(0, 400, 500, 40),
  )
  Element.prototype.scrollIntoView = vi.fn()
  Object.defineProperty(window, "scrollTo", { configurable: true, value: vi.fn() })
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { callback(0); return 1 })
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, text: async () => "# A document\n\n## Install\n\n## Choose models\n\n### Cloud models" })),
  )

  location.hash = "#tasks"
  new Function(SCRIPT)()
  await vi.waitFor(() => expect(document.querySelector("#doc h1")?.textContent).toBe("A document"))

  const contributor = document.querySelector<HTMLDetailsElement>(".nav-contributor")!
  expect(contributor.open).toBe(true)
  expect(contributor.querySelector("summary")?.textContent).toBe("Contributor reference")
  expect(document.querySelector('[data-id="tasks"]')?.closest(".nav-contributor")).toBe(contributor)

  // Long component references retain a single heading outline in the sidebar.
  // The short user guides are exercised separately in site-guides.test.ts.
  const nav = document.getElementById("doc-nav")!
  const fold = document.querySelector<HTMLDetailsElement>(".doc-nav-fold")!
  expect(document.querySelector(".doc-nav-intro")).toBeNull()
  expect(document.querySelector("#doc-toc")).toBeNull()
  expect(nav.querySelector(":scope > .nav-group > .nav-title")?.textContent).toBe("Documentation")
  expect(nav.querySelectorAll('a[href="#tasks/choose-models"]')).toHaveLength(1)
  expect(nav.querySelector('a[aria-current="page"]')?.textContent).toBe("tasks")

  // Anchor jumps leave the heading below the sticky bar. The outline must
  // name that heading, including when the compact layout uses a taller bar.
  document.documentElement.style.scrollPaddingTop = "128px"
  const headings = document.querySelectorAll("#doc h2")
  headings[0].getBoundingClientRect = () => new DOMRect(0, -100, 500, 40)
  headings[1].getBoundingClientRect = () => new DOMRect(0, 128, 500, 40)
  window.dispatchEvent(new Event("scroll"))
  expect([...nav.querySelectorAll("a.active")].map((a) => a.textContent)).toEqual(["Choose models"])
  expect(nav.querySelector('a[aria-current="location"]')?.textContent).toBe("Choose models")
  expect(fold.querySelector("summary")?.textContent).toBe("Choose models")

  const subheading = document.querySelector("#doc h3")!
  subheading.getBoundingClientRect = () => new DOMRect(0, 128, 500, 40)
  window.dispatchEvent(new Event("scroll"))
  expect([...nav.querySelectorAll("a.active")].map((a) => a.textContent)).toEqual(["Cloud models"])
  expect(fold.querySelector("summary")?.textContent).toBe("Cloud models")

  subheading.getBoundingClientRect = () => new DOMRect(0, 300, 500, 40)
  headings[1].getBoundingClientRect = () => new DOMRect(0, 200, 500, 40)
  window.dispatchEvent(new Event("scroll"))
  expect(nav.querySelector("a.active")?.textContent).toBe("Install")

  headings[0].getBoundingClientRect = () => new DOMRect(0, 160, 500, 40)
  window.dispatchEvent(new Event("scroll"))
  expect(nav.querySelector("a.active")?.textContent).toBe("tasks")
  expect(fold.querySelector("summary")?.textContent).toBe("tasks")

  location.hash = "#architecture"
  window.dispatchEvent(new HashChangeEvent("hashchange"))
  await vi.waitFor(() => expect(contributor.open).toBe(true))
  await vi.waitFor(() => expect(nav.querySelector('a[href="#architecture/choose-models"]')).not.toBeNull())
  expect(nav.querySelector('a[href="#tasks/choose-models"]')).toBeNull()

  fold.open = true
  for (const gesture of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }]) {
    const event = new MouseEvent("click", { bubbles: true, cancelable: true, ...gesture })
    nav.querySelector<HTMLAnchorElement>('a[href="#architecture"]')!.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
    expect(fold.open).toBe(true)
  }
  await new Promise((resolve) => setTimeout(resolve, 0))

  vi.mocked(window.scrollTo).mockClear()
  nav.querySelector<HTMLAnchorElement>('a[href="#architecture"]')!.click()
  expect(fold.open).toBe(false)
  await vi.waitFor(() => expect(window.scrollTo).toHaveBeenCalledWith(0, 0))

  const article = document.getElementById("doc")!
  article.scrollIntoView = vi.fn()
  document.querySelector<HTMLAnchorElement>(".skip-link")!.click()
  await vi.waitFor(() => expect(document.activeElement).toBe(article))
  expect(location.hash).toBe("#architecture")
  expect(document.title).toBe("Architecture — poieo docs")
  expect(article.scrollIntoView).toHaveBeenCalled()

  // A fast second navigation can finish first. The older response must not
  // append a second outline or move the reader back to the previous topic.
  const answers: ((value: { ok: boolean; text: () => Promise<string> }) => void)[] = []
  sessionStorage.clear()
  vi.stubGlobal("fetch", vi.fn(() => new Promise((resolve) => answers.push(resolve))))
  location.hash = "#tasks/choose-models"
  await vi.waitFor(() => expect(answers).toHaveLength(1))
  location.hash = "#tasks"
  await vi.waitFor(() => expect(answers).toHaveLength(2))
  const guide = { ok: true, text: async () => "# The guide\n\n## Install\n\n## Choose models" }
  answers[1](guide)
  await vi.waitFor(() => expect(nav.querySelectorAll('a[href="#tasks/choose-models"]')).toHaveLength(1))
  vi.mocked(Element.prototype.scrollIntoView).mockClear()
  answers[0](guide)
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(nav.querySelectorAll(".doc-sections")).toHaveLength(1)
  expect(nav.querySelectorAll('a[href="#tasks/choose-models"]')).toHaveLength(1)
  expect(nav.querySelectorAll("a[aria-current]")).toHaveLength(1)
  expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()

  // An obsolete error must not replace the document the reader chose next.
  location.hash = "#design"
  await vi.waitFor(() => expect(answers).toHaveLength(3))
  location.hash = "#tasks"
  await vi.waitFor(() => expect(document.querySelector("#doc h1")?.textContent).toBe("The guide"))
  answers[2]({ ...guide, ok: false })
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(document.querySelector("#doc h1")?.textContent).toBe("The guide")
})
