import { readFileSync } from "node:fs"
import { afterEach, expect, test, vi } from "vitest"

const SCRIPT = readFileSync(new URL("../../site/docs.js", import.meta.url), "utf8")

afterEach(() => {
  location.hash = ""
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

test("contributor documents stay folded until one is being read", async () => {
  document.body.innerHTML = `
    <nav id="doc-nav"></nav>
    <article id="doc"></article>
    <details id="doc-toc"><summary>On this page</summary><nav></nav></details>
    <details class="doc-nav-fold"><summary>All documents</summary></details>
  `
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({ matches: true, addEventListener: vi.fn() }),
  })
  Object.defineProperty(window, "scrollTo", { configurable: true, value: vi.fn() })
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, text: async () => "# A document" })),
  )

  location.hash = "#usage"
  new Function(SCRIPT)()
  await vi.waitFor(() => expect(document.querySelector("#doc h1")?.textContent).toBe("A document"))

  const contributor = document.querySelector<HTMLDetailsElement>(".nav-contributor")!
  expect(contributor.open).toBe(false)
  expect(contributor.querySelector("summary")?.textContent).toBe("Contributor reference")
  expect(document.querySelector('[data-id="usage"]')?.closest(".nav-contributor")).toBeNull()

  location.hash = "#architecture"
  window.dispatchEvent(new HashChangeEvent("hashchange"))
  await vi.waitFor(() => expect(contributor.open).toBe(true))
})
