import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const fetchModels = vi.hoisted(() => vi.fn())
const pickModel = vi.hoisted(() => vi.fn())
const addEngine = vi.hoisted(() => vi.fn())
const fetchUndeclared = vi.hoisted(() => vi.fn())
vi.mock("../api", () => ({ fetchModels, pickModel, addEngine, fetchUndeclared }))

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
  roles: ["default"],
  endpoints: [
    {
      name: "ollama",
      type: "ollama",
      label: "Ollama",
      askable: true,
      installed: true,
      here: true,
      host: "localhost:11434",
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
      here: false,
      host: "openrouter.ai",
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
  pickModel.mockReset()
  pickModel.mockResolvedValue({ ok: true, status: "using" })
  addEngine.mockReset()
  addEngine.mockResolvedValue({ ok: true, status: "added" })
  fetchUndeclared.mockReset()
  fetchUndeclared.mockResolvedValue([])
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

async function render(report: unknown = REPORT, undeclared: unknown[] = []) {
  fetchModels.mockResolvedValue(report)
  fetchUndeclared.mockResolvedValue(undeclared)
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

test("a local model reads local rather than showing a price of nothing", async () => {
  // Ollama does not charge per token, so there is no rate to report -- and a
  // zero would read as a rate somebody looked up.
  await render()

  const price = row("ollama/qwen3.5:latest")!.querySelector(".models-price")!
  expect(price.textContent).toBe("local")
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
  await render({ binding: null, roles: [], endpoints: [] })

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

test("what an endpoint is leads; the name in the file comes second", async () => {
  // Reading a config back to somebody is not telling them what is there. The
  // key is what its author believed when they typed it; the label is what
  // answered.
  await render()

  const block = container.querySelector('[data-endpoint="routed"]')!
  expect(block.querySelector(".models-endpoint-name")!.textContent).toBe("OpenRouter")
  expect(block.querySelector(".models-kind")!.textContent).toBe("routed")
})

test("when nothing answered the question, the file's name is all there is", async () => {
  await render({
    ...REPORT,
    endpoints: [{ ...REPORT.endpoints[1], label: null }],
  })

  const block = container.querySelector('[data-endpoint="routed"]')!
  expect(block.querySelector(".models-endpoint-name")!.textContent).toBe("routed")
  expect(block.querySelector(".models-kind")!.textContent).toBe("openai_compatible")
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

// -- pointing a role at another model ---------------------------------------

const WITH_ROLES = { ...REPORT, roles: ["default", "reader"] }

test("clicking a model uses it, for everything by default", async () => {
  await render()

  await act(async () => row("routed/qwen/qwen3.8-flash")!.querySelector<HTMLElement>("[data-do='use']")!.click())

  expect(pickModel).toHaveBeenCalledWith("board", "routed/qwen/qwen3.8-flash", "default")
})

test("a project whose file names one role is not asked which", async () => {
  // A picker with one option in it is furniture -- the rule the project picker
  // in the bar already follows.
  await render()

  expect(container.querySelector(".models-role")).toBeNull()
})

test("where there is a choice, the click goes to the role that was chosen", async () => {
  await render(WITH_ROLES)

  await act(async () => {
    const pick = container.querySelector<HTMLSelectElement>(".models-role")!
    pick.value = "reader"
    pick.dispatchEvent(new Event("change", { bubbles: true }))
  })
  await act(async () => row("ollama/qwen3.5:latest")!.querySelector<HTMLElement>("[data-do='use']")!.click())

  expect(pickModel).toHaveBeenCalledWith("board", "ollama/qwen3.5:latest", "reader")
})

test("a double click cannot post twice", async () => {
  let release: (value: unknown) => void = () => {}
  pickModel.mockReturnValue(new Promise((resolve) => (release = resolve)))
  await render()

  const button = () => row("ollama/qwen3.5:latest")!.querySelector<HTMLElement>("[data-do='use']")!
  await act(async () => button().click())
  expect(button().hasAttribute("disabled")).toBe(true)
  await act(async () => button().click())

  expect(pickModel).toHaveBeenCalledTimes(1)
  await act(async () => release({ ok: true, status: "using" }))
})

test("a refusal is shown with the models the endpoint does say it has", async () => {
  pickModel.mockResolvedValue({
    ok: false,
    error: "'local' does not serve 'qwen9.9'",
    models: ["qwen3.5:latest", "llama3.2:3b"],
  })
  await render()

  await act(async () => row("ollama/qwen3.5:latest")!.querySelector<HTMLElement>("[data-do='use']")!.click())

  expect(container.textContent).toContain("does not serve")
  expect(container.textContent).toContain("qwen3.5:latest, llama3.2:3b")
})

test("a refusal names the endpoints that are declared", async () => {
  pickModel.mockResolvedValue({
    ok: false,
    error: "this project declares no endpoint 'nowhere'",
    providers: ["ollama", "routed"],
  })
  await render()

  await act(async () => row("ollama/qwen3.5:latest")!.querySelector<HTMLElement>("[data-do='use']")!.click())

  expect(container.textContent).toContain("declares: ollama, routed")
})

test("a successful use reads the panel again, so the marks move", async () => {
  // `used_by` is on the report, not in the click -- the panel has to ask again
  // or the row a reader just bound goes on saying somebody else has it.
  await render()
  expect(fetchModels).toHaveBeenCalledTimes(1)

  await act(async () => row("ollama/qwen3.5:latest")!.querySelector<HTMLElement>("[data-do='use']")!.click())

  expect(fetchModels).toHaveBeenCalledTimes(2)
})

test("a role the file stopped naming is not left selected", async () => {
  await render(WITH_ROLES)
  await act(async () => {
    const pick = container.querySelector<HTMLSelectElement>(".models-role")!
    pick.value = "reader"
    pick.dispatchEvent(new Event("change", { bubbles: true }))
  })

  // Somebody edits the file and `reader` goes away. The read that follows the
  // next write is where the panel finds out, and it must not leave a click
  // pointed at a role that is no longer there.
  fetchModels.mockResolvedValue(REPORT)
  const use = () => row("ollama/qwen3.5:latest")!.querySelector<HTMLElement>("[data-do='use']")!
  await act(async () => use().click())
  expect(pickModel).toHaveBeenLastCalledWith("board", "ollama/qwen3.5:latest", "reader")

  await act(async () => use().click())

  expect(pickModel).toHaveBeenLastCalledWith("board", "ollama/qwen3.5:latest", "default")
})

// -- engines running here that this project has never used -------------------

const LMSTUDIO = [
  {
    name: "lmstudio",
    label: "LM Studio",
    type: "openai_compatible",
    models: ["qwen3-4b", "gemma-3-12b"],
  },
]

const offer = (name: string) =>
  container.querySelector<HTMLElement>(`[data-offer="${name}"]`)

test("an engine answering here that this project cannot reach is offered by name", async () => {
  await render(REPORT, LMSTUDIO)

  expect(offer("lmstudio")!.textContent).toContain("LM Studio")
  // What it has, so the offer says what taking it would be worth.
  expect(offer("lmstudio")!.textContent).toContain("2")
})

test("nothing is drawn when there is nothing running that this project misses", async () => {
  // The usual case, and it must cost the reader no screen at all -- a standing
  // button whose answer is almost always "nothing new" teaches people to
  // ignore it.
  await render()

  expect(container.querySelector("[data-offer]")).toBeNull()
})

test("taking an offer names the engine back, and nothing else", async () => {
  await render(REPORT, LMSTUDIO)

  await act(async () => offer("lmstudio")!.querySelector<HTMLElement>("[data-do='add']")!.click())

  expect(addEngine).toHaveBeenCalledWith("board", { engine: "lmstudio" })
})

test("a refusal to add is shown in the daemon's words", async () => {
  addEngine.mockResolvedValue({
    ok: false,
    error: "'lmstudio' is not answering on this machine",
  })
  await render(REPORT, LMSTUDIO)

  await act(async () => offer("lmstudio")!.querySelector<HTMLElement>("[data-do='add']")!.click())

  expect(container.textContent).toContain("not answering")
})

test("adding an engine reads the panel again, so its models appear", async () => {
  await render(REPORT, LMSTUDIO)
  expect(fetchModels).toHaveBeenCalledTimes(1)

  await act(async () => offer("lmstudio")!.querySelector<HTMLElement>("[data-do='add']")!.click())

  expect(fetchModels).toHaveBeenCalledTimes(2)
})

// -- asking again ------------------------------------------------------------

test("the refresh button asks every endpoint again", async () => {
  // The panel reads once, when it opens. Pull a model in a terminal with it
  // open and the list is stale, and closing and reopening was the only way.
  await render()
  expect(fetchModels).toHaveBeenCalledTimes(1)

  await act(async () => container.querySelector<HTMLElement>("[data-do='refresh']")!.click())

  expect(fetchModels).toHaveBeenCalledTimes(2)
})

test("the list stays on screen while it is being asked again", async () => {
  // Blanking to "asking…" on every refresh makes the panel flash, and the
  // thing a reader is comparing against is the list they already have.
  await render()
  fetchModels.mockReturnValue(new Promise(() => {}))

  await act(async () => container.querySelector<HTMLElement>("[data-do='refresh']")!.click())

  expect(row("ollama/qwen3.5:latest")).not.toBeNull()
  expect(container.textContent).not.toContain("asking…")
})

test("the catalogue draws without waiting for the search for new engines", async () => {
  // Why these are two requests. Looking for an engine means asking ports that
  // may have nothing on them, and a closed one costs a whole timeout -- so a
  // catalogue carrying the answer would take a second and a half to draw a
  // list it already had every part of.
  fetchModels.mockResolvedValue(REPORT)
  fetchUndeclared.mockReturnValue(new Promise(() => {}))

  await act(async () => {
    root.render(<Models project="board" onClose={() => {}} />)
  })

  expect(row("ollama/qwen3.5:latest")).not.toBeNull()
  expect(container.querySelector("[data-offer]")).toBeNull()
})

test("asking again looks for new engines too, not only for new models", async () => {
  await render(REPORT, LMSTUDIO)
  expect(fetchUndeclared).toHaveBeenCalledTimes(1)

  await act(async () => container.querySelector<HTMLElement>("[data-do='refresh']")!.click())

  expect(fetchUndeclared).toHaveBeenCalledTimes(2)
})

// -- what a reader sees first ------------------------------------------------
//
// Measured on a real board before this existed: the metered catalogue's 396
// models pushed the eight on this machine 1786px down, and the offer 2181px --
// three screens below a 729px panel. The list was in the binding file's order,
// which is provenance, not an answer to "what can I run".

test("what is on this machine is listed before a catalogue", async () => {
  // In the file's order, which is what the report carries: `poieo init` writes
  // the metered endpoint wherever it was declared, and provenance is not an
  // answer to "what can I run".
  await render({ ...REPORT, endpoints: [REPORT.endpoints[1], REPORT.endpoints[0]] })

  const blocks = [...container.querySelectorAll("[data-endpoint]")].map((e) =>
    e.getAttribute("data-endpoint"),
  )
  expect(blocks).toEqual(["ollama", "routed"])
})

test("two endpoints of the same kind keep the order their file put them in", async () => {
  // The rule is one step, not a sort: reordering beyond "here before a menu"
  // would hide the reader's own arrangement from them.
  const second = { ...REPORT.endpoints[1], name: "other" }
  await render({ ...REPORT, endpoints: [REPORT.endpoints[1], second] })

  const blocks = [...container.querySelectorAll("[data-endpoint]")].map((e) =>
    e.getAttribute("data-endpoint"),
  )
  expect(blocks).toEqual(["routed", "other"])
})

test("an offer is above the lists, not under them", async () => {
  // It is the one piece of news on the panel. Under a 396-model catalogue it
  // was the last thing a reader would ever find.
  await render(REPORT, LMSTUDIO)

  const first = container.querySelector("[data-offer], [data-endpoint]")
  expect(first!.getAttribute("data-offer")).toBe("lmstudio")
})

test("a filter that hides every model leaves the offer standing", async () => {
  // The filter is about models; an offer is about an engine that has none of
  // them yet, so a search that missed says nothing about it.
  await render(REPORT, LMSTUDIO)

  await act(async () => {
    const box = container.querySelector<HTMLInputElement>(".models-filter")!
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!
    set.call(box, "nothing-matches-this")
    box.dispatchEvent(new Event("input", { bubbles: true }))
  })

  expect(container.querySelector("[data-offer]")).not.toBeNull()
  expect(container.textContent).toContain("nothing matches")
})

// -- this machine, or somebody else's ----------------------------------------

const OFFICE = {
  name: "office",
  type: "ollama",
  label: "Ollama",
  askable: true,
  installed: true,
  here: false,
  host: "192.168.1.50:11434",
  api_key_env: null,
  api_key_set: null,
  models: [{ ...LOCAL, id: "qwen3.5:32b", ref: "office/qwen3.5:32b", used_by: [] }],
}

const TWO_OLLAMAS = { ...REPORT, endpoints: [REPORT.endpoints[0], OFFICE] }

test("a listing on another host does not claim to be on this machine", async () => {
  await render(TWO_OLLAMAS)

  const here = container.querySelector('[data-endpoint="ollama"] .models-count')!
  const there = container.querySelector('[data-endpoint="office"] .models-count')!
  expect(here.textContent).toBe("1 on this machine")
  expect(there.textContent).toBe("1 on that machine")
  expect(there.getAttribute("data-listing")).toBe("elsewhere")
})

test("two endpoints of one kind are told apart by the machine they are on", async () => {
  // Both are "Ollama" and `poieo config` would name both `ollama`. Without the
  // address there is nothing on screen that separates them.
  await render(TWO_OLLAMAS)

  expect(
    container.querySelector('[data-endpoint="office"] .models-host')!.textContent,
  ).toBe("192.168.1.50:11434")
})

test("a model on another host is not priced as local", async () => {
  await render(TWO_OLLAMAS)

  const price = row("office/qwen3.5:32b")!.querySelector(".models-price")!
  expect(price.textContent).toBe("self-hosted")
  expect(price.getAttribute("data-price")).toBe("self-hosted")
})

test("this machine comes before another host, and both before a menu", async () => {
  await render({ ...REPORT, endpoints: [REPORT.endpoints[1], OFFICE, REPORT.endpoints[0]] })

  const blocks = [...container.querySelectorAll("[data-endpoint]")].map((e) =>
    e.getAttribute("data-endpoint"),
  )
  expect(blocks).toEqual(["ollama", "office", "routed"])
})

test("an endpoint with no address says nothing about a machine", async () => {
  await render({
    ...REPORT,
    endpoints: [
      { ...REPORT.endpoints[0], name: "fake", type: "mock", label: null, askable: false,
        installed: false, here: null, host: null, models: [] },
    ],
  })

  expect(container.querySelector(".models-host")).toBeNull()
})

// -- an edit the running daemon did not take ---------------------------------

test("a change the daemon would not take is said, with its reason", async () => {
  // The worst shape a write can have: the file changed, the answer said it
  // worked, and the panel redrew the old model because the daemon kept the
  // last good spec. Silence there reads as "nothing happened".
  pickModel.mockResolvedValue({
    ok: true,
    status: "using",
    ref: "routed/qwen/flash",
    adopted: false,
    why: "task 'chores': provider 'routed': $OPENROUTER_API_KEY is not set",
  })
  await render()

  await act(async () => row("ollama/qwen3.5:latest")!.querySelector<HTMLElement>("[data-do='use']")!.click())

  const note = container.querySelector("[data-do='not-taken']")!
  expect(note.textContent).toContain("OPENROUTER_API_KEY")
  expect(note.textContent).toContain("models/default.yaml")
})

test("an endpoint the daemon would not take is said, with its reason", async () => {
  // The same shape on the other write. `add` swallowed the refusal entirely:
  // the file gained the endpoint, the panel went on offering it, and pressing
  // the offer again answered "this project already reaches it".
  addEngine.mockResolvedValue({
    ok: true,
    status: "added",
    engine: "lmstudio",
    models: ["qwen3-4b"],
    adopted: false,
    why: "task 'chores': provider 'routed': $OPENROUTER_API_KEY is not set",
  })
  await render(REPORT, LMSTUDIO)

  await act(async () => offer("lmstudio")!.querySelector<HTMLElement>("[data-do='add']")!.click())

  const note = container.querySelector("[data-do='not-taken']")!
  expect(note.textContent).toContain("OPENROUTER_API_KEY")
  expect(note.textContent).toContain("lmstudio")
  expect(note.textContent).toContain("models/default.yaml")
  // The consequence, which is not `use`'s: nothing was pointed anywhere and
  // there is no previous model, but the panel will go on offering this.
  expect(note.textContent).toContain("go on offering")
  expect(note.textContent).not.toContain("previous model")
  // And the daemon's message is ended, so the sentence after it starts.
  expect(note.textContent).toContain("is not set. ")
})

test("an ordinary change says nothing extra", async () => {
  await render()

  await act(async () => row("ollama/qwen3.5:latest")!.querySelector<HTMLElement>("[data-do='use']")!.click())

  expect(container.querySelector("[data-do='not-taken']")).toBeNull()
})

// -- an engine at an address the board was not told about --------------------

const value = (el: HTMLInputElement, text: string) => {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!
  set.call(el, text)
  el.dispatchEvent(new Event("input", { bubbles: true }))
}

test("an address is all a reader has to type", async () => {
  // Not a form asking them to classify their own server: which backend it is
  // comes from asking it, and the name from what it says it is.
  await render()

  await act(async () => value(container.querySelector<HTMLInputElement>("[data-do='url']")!, "http://gpu-box:8001"))
  await act(async () => container.querySelector<HTMLElement>("[data-do='add-at']")!.click())

  expect(addEngine).toHaveBeenCalledWith("board", { url: "http://gpu-box:8001" })
})

test("a name and a key variable go along when they are given", async () => {
  await render()

  await act(async () => {
    value(container.querySelector<HTMLInputElement>("[data-do='url']")!, "http://gpu-box:8001")
    value(container.querySelector<HTMLInputElement>("[data-do='url-name']")!, "office")
    value(container.querySelector<HTMLInputElement>("[data-do='url-key-env']")!, "OFFICE_TOKEN")
  })
  await act(async () => container.querySelector<HTMLElement>("[data-do='add-at']")!.click())

  expect(addEngine).toHaveBeenCalledWith("board", {
    url: "http://gpu-box:8001",
    name: "office",
    key_env: "OFFICE_TOKEN",
  })
})

test("the form never asks for a key, only for the variable holding one", async () => {
  // The rule this panel has followed since it was one screen: a variable's
  // name is not a secret and a key is, and the web takes neither a key nor a
  // password field it could be typed into.
  await render()

  const fields = [...container.querySelectorAll(".models-at input")]
  expect(fields.some((f) => f.getAttribute("type") === "password")).toBe(false)
  expect(container.textContent).not.toContain("API key")
})

test("an empty address does not send anything", async () => {
  await render()

  await act(async () => container.querySelector<HTMLElement>("[data-do='add-at']")!.click())

  expect(addEngine).not.toHaveBeenCalled()
})

test("a refusal from an address is shown where it was typed", async () => {
  addEngine.mockResolvedValue({ ok: false, error: "nothing usable answered at http://nowhere:9999" })
  await render()

  await act(async () => value(container.querySelector<HTMLInputElement>("[data-do='url']")!, "http://nowhere:9999"))
  await act(async () => container.querySelector<HTMLElement>("[data-do='add-at']")!.click())

  expect(container.textContent).toContain("nothing usable answered")
})
