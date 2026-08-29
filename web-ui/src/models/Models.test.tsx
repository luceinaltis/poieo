import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const fetchModels = vi.hoisted(() => vi.fn())
vi.mock("../api", () => ({ fetchModels }))

import { Models } from "./Models"

const LOCAL = {
  id: "qwen3.5:latest",
  ref: "ollama/qwen3.5:latest",
  context: 262144,
  size: "9.0B",
  quantization: "Q4_K_M",
  capabilities: ["completion", "vision"],
  price: null,
  used_by: ["default"],
}

const ROUTED = {
  id: "qwen/qwen3.8-flash",
  ref: "routed/qwen/qwen3.8-flash",
  context: 1000000,
  size: null,
  quantization: null,
  capabilities: [],
  price: { input: 0.15, output: 0.47 },
  used_by: [],
}

const REPORT = {
  binding: { name: "hybrid", path: "/home/k/proj/models/default.yaml" },
  endpoints: [
    {
      name: "ollama",
      type: "ollama",
      askable: true,
      api_key_env: null,
      api_key_set: null,
      models: [LOCAL],
    },
    {
      name: "routed",
      type: "openai_compatible",
      askable: true,
      api_key_env: "OPENROUTER_API_KEY",
      api_key_set: true,
      models: [ROUTED],
    },
  ],
}

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  fetchModels.mockReset()
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

const row = (ref: string) => container.querySelector<HTMLElement>(`[data-model="${ref}"]`)
const fact = (ref: string, kind: string) =>
  row(ref)!.querySelector(`[data-fact="${kind}"]`)?.textContent

test("it asks the project on screen, and names the file the endpoints came from", async () => {
  await render()

  expect(fetchModels).toHaveBeenCalledWith("board")
  expect(container.textContent).toContain("models/default.yaml")
})

test("every endpoint is a block, with its models under it", async () => {
  await render()

  const blocks = [...container.querySelectorAll("[data-endpoint]")].map((e) =>
    e.getAttribute("data-endpoint"),
  )
  expect(blocks).toEqual(["ollama", "routed"])
  expect(row("ollama/qwen3.5:latest")).not.toBeNull()
  expect(row("routed/qwen/qwen3.8-flash")).not.toBeNull()
})

test("a published price is shown per million tokens, input then output", async () => {
  await render()

  const price = row("routed/qwen/qwen3.8-flash")!.querySelector(".models-price")!
  expect(price.textContent).toBe("$0.15 / $0.47")
  expect(price.getAttribute("data-price")).toBe("paid")
})

test("a local model says it runs here rather than showing a price of nothing", async () => {
  // Ollama does not charge per token, so there is no rate to report -- and a
  // zero would read as a rate somebody looked up.
  await render()

  const price = row("ollama/qwen3.5:latest")!.querySelector(".models-price")!
  expect(price.textContent).toBe("runs here")
  expect(price.getAttribute("data-price")).toBe("local")
})

test("an endpoint that charges but did not say leaves the price blank", async () => {
  // vLLM and LM Studio answer the same listing with no rates on it. A blank is
  // the honest answer; "free" would be a guess, and an expensive one.
  await render({
    ...REPORT,
    endpoints: [{ ...REPORT.endpoints[1], models: [{ ...ROUTED, price: null }] }],
  })

  const price = row("routed/qwen/qwen3.8-flash")!.querySelector(".models-price")!
  expect(price.textContent).toBe("")
  expect(price.getAttribute("data-price")).toBe("unknown")
})

test("what a local model costs is its size, and the window is readable", async () => {
  await render()

  expect(fact("ollama/qwen3.5:latest", "context")).toBe("262k")
  expect(fact("ollama/qwen3.5:latest", "size")).toBe("9.0B")
  expect(fact("ollama/qwen3.5:latest", "quant")).toBe("Q4_K_M")
  expect(fact("routed/qwen/qwen3.8-flash", "context")).toBe("1M")
})

test("capabilities are shown, except the one every model has", async () => {
  // Every entry says "completion". A column that is the same on every row is
  // not information.
  await render()

  const shown = [...row("ollama/qwen3.5:latest")!.querySelectorAll('[data-fact="can"]')]
  expect(shown.map((s) => s.textContent)).toEqual(["vision"])
})

test("only the models a role is on say so", async () => {
  await render()

  expect(row("ollama/qwen3.5:latest")!.querySelector(".models-using")!.textContent).toBe(
    "default",
  )
  expect(row("routed/qwen/qwen3.8-flash")!.querySelector(".models-using")).toBeNull()
})

test("an endpoint with nothing to ask says that, not that it is down", async () => {
  await render({
    ...REPORT,
    endpoints: [
      { name: "fake", type: "mock", askable: false, api_key_env: null, api_key_set: null, models: [] },
    ],
  })

  expect(container.textContent).toContain("nothing to ask")
})

test("an endpoint whose key is missing says so where the models would be", async () => {
  // The likeliest reason a list is empty, and the only one the reader can fix.
  await render({
    ...REPORT,
    endpoints: [
      {
        name: "claude",
        type: "anthropic",
        askable: true,
        api_key_env: "ANTHROPIC_API_KEY",
        api_key_set: false,
        models: [],
      },
    ],
  })

  expect(container.textContent).toContain("ANTHROPIC_API_KEY is not set")
})

test("a project with no models file says so instead of an empty list", async () => {
  await render({ binding: null, endpoints: [] })

  expect(container.textContent).toContain("no models file")
  expect(container.querySelector("[data-endpoint]")).toBeNull()
})

test("a daemon that did not answer is said out loud", async () => {
  await render(null)

  expect(container.textContent).toContain("could not be asked")
})
