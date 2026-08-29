import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const fetchModels = vi.hoisted(() => vi.fn())
vi.mock("../api", () => ({ fetchModels }))

import { Models } from "./Models"

const REPORT = {
  binding: { name: "hybrid", path: "/home/k/proj/models/default.yaml" },
  providers: {
    ollama: { type: "ollama", api_key_env: null, api_key_set: null },
    claude: { type: "anthropic", api_key_env: "ANTHROPIC_API_KEY", api_key_set: false },
  },
  default: "ollama/qwen3:32b",
  roles: { reader: "ollama/llama3.2:3b" },
}

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  fetchModels.mockReset()
  fetchModels.mockResolvedValue(REPORT)
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

async function render(report: unknown = REPORT) {
  fetchModels.mockResolvedValue(report)
  await act(async () => {
    root.render(<Models project="board" onClose={() => {}} />)
  })
}

test("the panel names the file the answer came from", async () => {
  await render()

  expect(fetchModels).toHaveBeenCalledWith("board")
  expect(container.textContent).toContain("models/default.yaml")
})

test("every endpoint is listed with what kind it is", async () => {
  await render()

  const names = [...container.querySelectorAll(".models-endpoint-name")].map(
    (el) => el.textContent,
  )
  expect(names).toEqual(["ollama", "claude"])
  expect(container.textContent).toContain("anthropic")
})

test("an endpoint whose key is missing says which variable, and never a value", async () => {
  await render()

  // The panel's whole job here is to explain why a model will not answer, so
  // the variable is named -- and nothing else about it ever is.
  const claude = container.querySelector('[data-endpoint="claude"]')!
  expect(claude.textContent).toContain("ANTHROPIC_API_KEY")
  expect(claude.querySelector('[data-key="missing"]')).not.toBeNull()
})

test("an endpoint that names no variable says nothing about keys at all", async () => {
  await render()

  // Null is not false: a local server resolving its own is not a warning, and
  // a panel that flagged it would cry wolf on every one of them.
  const ollama = container.querySelector('[data-endpoint="ollama"]')!
  expect(ollama.textContent).not.toContain("KEY")
  expect(ollama.querySelector("[data-key]")).toBeNull()
})

test("what runs by default is shown, and named roles beside it", async () => {
  await render()

  expect(container.querySelector('[data-role="default"]')!.textContent).toContain(
    "ollama/qwen3:32b",
  )
  expect(container.querySelector('[data-role="reader"]')!.textContent).toContain(
    "ollama/llama3.2:3b",
  )
})

test("a project whose models file names no roles shows no trace of them", async () => {
  // Gated on content, like the memory block in a card's prompt: most projects
  // run everything on one model, and a heading over an empty list is furniture.
  await render({ ...REPORT, roles: {} })

  expect(container.querySelector('[data-role="default"]')).not.toBeNull()
  expect(container.querySelector(".models-roles")).toBeNull()
})

test("a project with no models file says so instead of drawing an empty table", async () => {
  await render({ binding: null, providers: {}, default: null, roles: {} })

  expect(container.textContent).toContain("no models file")
  expect(container.querySelector(".models-endpoint-name")).toBeNull()
})

test("a daemon that did not answer is said out loud", async () => {
  await render(null)

  expect(container.textContent).toContain("could not be read")
})
