import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { afterEach, expect, test, vi } from "vitest"

const SCRIPT = readFileSync(resolve(process.cwd(), "../site/docs.js"), "utf8")

afterEach(() => {
  location.hash = ""
  sessionStorage.clear()
  document.documentElement.style.removeProperty("scroll-padding-top")
  vi.unstubAllGlobals()
})

test("docs navigation follows the document and headings below the sticky header", async () => {
  document.body.innerHTML = `
    <a class="skip-link" href="#doc">Skip to content</a>
    <nav id="doc-nav"></nav>
    <article id="doc" tabindex="-1"></article>
    <details id="doc-toc"><summary>On this page</summary><nav></nav></details>
    <details class="doc-nav-fold"><summary>All documents</summary></details>
  `
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({ matches: true, addEventListener: vi.fn() }),
  })
  Object.defineProperty(window, "scrollTo", { configurable: true, value: vi.fn() })
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { callback(0); return 1 })
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, text: async () => "# A document\n\n## Install\n\n## Choose models" })),
  )

  location.hash = "#usage"
  new Function(SCRIPT)()
  await vi.waitFor(() => expect(document.querySelector("#doc h1")?.textContent).toBe("A document"))

  const contributor = document.querySelector<HTMLDetailsElement>(".nav-contributor")!
  expect(contributor.open).toBe(false)
  expect(contributor.querySelector("summary")?.textContent).toBe("Contributor reference")
  expect(document.querySelector('[data-id="usage"]')?.closest(".nav-contributor")).toBeNull()

  // Anchor jumps leave the heading below the sticky bar. The outline must
  // name that heading, including when the compact layout uses a taller bar.
  document.documentElement.style.scrollPaddingTop = "128px"
  const headings = document.querySelectorAll("#doc h2")
  headings[0].getBoundingClientRect = () => new DOMRect(0, -100, 500, 40)
  headings[1].getBoundingClientRect = () => new DOMRect(0, 128, 500, 40)
  window.dispatchEvent(new Event("scroll"))
  expect(document.querySelector("#doc-toc a.active")?.textContent).toBe("Choose models")
  headings[1].getBoundingClientRect = () => new DOMRect(0, 200, 500, 40)
  window.dispatchEvent(new Event("scroll"))
  expect(document.querySelector("#doc-toc a.active")?.textContent).toBe("Install")

  location.hash = "#architecture"
  window.dispatchEvent(new HashChangeEvent("hashchange"))
  await vi.waitFor(() => expect(contributor.open).toBe(true))

  const article = document.getElementById("doc")!
  article.scrollIntoView = vi.fn()
  document.querySelector<HTMLAnchorElement>(".skip-link")!.click()
  await vi.waitFor(() => expect(document.activeElement).toBe(article))
  expect(location.hash).toBe("#architecture")
  expect(document.title).toBe("Architecture — poieo docs")
  expect(article.scrollIntoView).toHaveBeenCalled()
})
