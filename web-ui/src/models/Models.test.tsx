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
      label: "Ollama",
      askable: true,
      installed: true,
      api_key_env: null,
      api_key_set: null,
      models: [LOCAL],
    },
    {
      name: "routed",
      type: "openai_compatible",
      label: "OpenRouter",
      askable: true,
      installed: false,
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
      {
        name: "fake",
        type: "mock",
        label: null,
        askable: false,
        installed: false,
        api_key_env: null,
        api_key_set: null,
        models: [],
      },
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
        label: "Claude API",
        askable: true,
        installed: false,
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

test("a listing says how many, and whether they are here or merely offered", async () => {
  // The one thing the screenshot could not tell you: eight models on this disk
  // and four hundred on somebody's menu are the same-looking list.
  await render()

  const here = container.querySelector('[data-endpoint="ollama"] .models-count')!
  expect(here.textContent).toBe("1 on this machine")
  expect(here.getAttribute("data-listing")).toBe("here")

  const offered = container.querySelector('[data-endpoint="routed"] .models-count')!
  expect(offered.textContent).toBe("1 offered")
  expect(offered.getAttribute("data-listing")).toBe("offered")
})

/**
 * Type into the filter the way a person does.
 *
 * Through the prototype's own setter, because React installs a value tracker
 * on every controlled input and a plain assignment slips past it -- the event
 * fires and the component never sees a change. A `<select>` has no tracker,
 * which is why the project picker's test can set `.value` directly.
 */
async function type(text: string) {
  const box = container.querySelector<HTMLInputElement>(".models-filter")!
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!
  await act(async () => {
    set.call(box, text)
    box.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

test("filtering narrows the rows and says what it narrowed from", async () => {
  // A four-hundred-model catalogue is read by filtering it. The count has to
  // keep saying how many there really are, or the filter becomes the same
  // silent truncation it replaced.
  await render({
    ...REPORT,
    endpoints: [
      { ...REPORT.endpoints[0], models: [LOCAL, { ...LOCAL, id: "llama3.2:3b", ref: "ollama/llama3.2:3b" }] },
    ],
  })

  await type("llama")

  expect(row("ollama/llama3.2:3b")).not.toBeNull()
  expect(row("ollama/qwen3.5:latest")).toBeNull()
  expect(container.querySelector(".models-count")!.textContent).toBe(
    "1 of 2 on this machine",
  )
})

test("an endpoint with nothing matching leaves rather than reading as broken", async () => {
  await render()

  await type("qwen3.5")

  // `routed` has no match. Left in place it would show "no answer" under its
  // heading, which is a different and alarming thing.
  expect(container.querySelector('[data-endpoint="routed"]')).toBeNull()
  expect(container.querySelector('[data-endpoint="ollama"]')).not.toBeNull()
})

test("a filter that matches nothing at all says so", async () => {
  await render()

  await type("nothing-is-called-this")

  expect(container.textContent).toContain("nothing matches")
})

test("an endpoint is named by what a person recognises, not by its protocol", async () => {
  // `openai_compatible` is vLLM and SGLang and LM Studio and llama.cpp and
  // every hosted router at once.
  await render()

  expect(
    container.querySelector('[data-endpoint="routed"] .models-kind')!.textContent,
  ).toBe("OpenRouter")
})

test("an address nobody wrote down falls back to the protocol", async () => {
  await render({
    ...REPORT,
    endpoints: [{ ...REPORT.endpoints[1], label: null }],
  })

  expect(
    container.querySelector('[data-endpoint="routed"] .models-kind')!.textContent,
  ).toBe("openai_compatible")
})

/** A catalogue big enough to be worth folding, named the way one is. */
const CATALOGUE = {
  ...REPORT,
  endpoints: [
    {
      ...REPORT.endpoints[1],
      models: [
        ...Array.from({ length: 8 }, (_, n) => ({
          ...ROUTED,
          id: `deepseek/v${n}`,
          ref: `routed/deepseek/v${n}`,
        })),
        ...Array.from({ length: 5 }, (_, n) => ({
          ...ROUTED,
          id: `qwen/q${n}`,
          ref: `routed/qwen/q${n}`,
        })),
      ],
    },
  ],
}

const makers = () =>
  [...container.querySelectorAll("[data-maker]")].map((e) => e.getAttribute("data-maker"))

test("a big catalogue folds into a card per maker, biggest first", async () => {
  await render(CATALOGUE)

  expect(makers()).toEqual(["deepseek", "qwen"])
  expect(
    container.querySelector('[data-maker="deepseek"] .models-maker-count')!.textContent,
  ).toBe("8")
})

test("a card is shut until it is opened", async () => {
  await render(CATALOGUE)

  const card = container.querySelector<HTMLDetailsElement>('[data-maker="deepseek"]')!
  expect(card.open).toBe(false)
})

test("inside a maker's card the rows drop the prefix it already says", async () => {
  await render(CATALOGUE)

  const id = container.querySelector('[data-model="routed/deepseek/v0"] .models-id')!
  expect(id.textContent).toBe("v0")
  // The whole id stays reachable: it is the half of `ref` a reader copies out.
  expect(id.getAttribute("title")).toBe("deepseek/v0")
})

test("filtering opens the cards, because the matches are what was asked for", async () => {
  await render(CATALOGUE)

  await type("qwen")

  expect(makers()).toEqual(["qwen"])
  expect(
    container.querySelector<HTMLDetailsElement>('[data-maker="qwen"]')!.open,
  ).toBe(true)
})

test("a short listing stays flat, because folders holding one row each help nobody", async () => {
  // What is on a machine is named the way its owner pulled it -- `qwen3.5:latest`,
  // `hf.co/user/repo` -- where a leading segment is a host or nothing at all.
  await render()

  expect(makers()).toEqual([])
  expect(container.querySelector('[data-model="ollama/qwen3.5:latest"]')).not.toBeNull()
})
