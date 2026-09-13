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
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({ matches: true, addEventListener: vi.fn() }),
  })
  Object.defineProperty(window, "scrollTo", { configurable: true, value: vi.fn() })
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { callback(0); return 1 })
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, text: async () => "# A document\n\n## Install\n\n## Choose models\n\n### Cloud models" })),
  )

  location.hash = "#usage"
  new Function(SCRIPT)()
  await vi.waitFor(() => expect(document.querySelector("#doc h1")?.textContent).toBe("A document"))

  const contributor = document.querySelector<HTMLDetailsElement>(".nav-contributor")!
  expect(contributor.open).toBe(false)
  expect(contributor.querySelector("summary")?.textContent).toBe("Contributor reference")
  expect(document.querySelector('[data-id="usage"]')?.closest(".nav-contributor")).toBeNull()

  // The guide and its topics form one outline, instead of a quick-link list,
  // a separate "The manual" selection, and another outline on the right.
  const nav = document.getElementById("doc-nav")!
  const fold = document.querySelector<HTMLDetailsElement>(".doc-nav-fold")!
  expect(document.querySelector(".doc-nav-intro")).toBeNull()
  expect(document.querySelector("#doc-toc")).toBeNull()
  expect(nav.querySelector(":scope > .nav-group > .nav-title")?.textContent).toBe("Documentation")
  expect(nav.querySelectorAll('a[href="#usage/choose-models"]')).toHaveLength(1)
  expect(nav.querySelector('a[aria-current="page"]')?.textContent).toBe("Overview")

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
  expect(nav.querySelector("a.active")?.textContent).toBe("Overview")
  expect(fold.querySelector("summary")?.textContent).toBe("Overview")

  location.hash = "#architecture"
  window.dispatchEvent(new HashChangeEvent("hashchange"))
  await vi.waitFor(() => expect(contributor.open).toBe(true))
  await vi.waitFor(() => expect(nav.querySelector('a[href="#architecture/choose-models"]')).not.toBeNull())
  expect(nav.querySelector('a[href="#usage/choose-models"]')).toBeNull()

  fold.open = true
  nav.querySelector<HTMLAnchorElement>('a[href="#architecture"]')!.click()
  expect(fold.open).toBe(false)

  const article = document.getElementById("doc")!
  article.scrollIntoView = vi.fn()
  document.querySelector<HTMLAnchorElement>(".skip-link")!.click()
  await vi.waitFor(() => expect(document.activeElement).toBe(article))
  expect(location.hash).toBe("#architecture")
  expect(document.title).toBe("Architecture — poieo docs")
  expect(article.scrollIntoView).toHaveBeenCalled()
})
