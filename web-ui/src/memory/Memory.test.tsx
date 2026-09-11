import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { beforeEach, afterEach, expect, test, vi } from "vitest"

import {
  askMemory,
  fetchMemory,
  fetchMemoryEntry,
  keepMemory,
  putMemoryPage,
  searchMemory,
  setAsideMemory,
  settleMemorySuggestion,
} from "../api"
import { MEMORY_REFRESH_MS, Memory } from "./Memory"
import type { MemoryOverview } from "./types"

vi.mock("../api", () => ({
  fetchMemory: vi.fn(),
  fetchMemoryEntry: vi.fn(),
  searchMemory: vi.fn(),
  askMemory: vi.fn(),
  keepMemory: vi.fn(),
  putMemoryPage: vi.fn(),
  setAsideMemory: vi.fn(),
  settleMemorySuggestion: vi.fn(),
}))

vi.mock("./Constellation", () => ({
  Constellation: ({ onSelect }: { onSelect(slug: string): void }) => (
    <button type="button" data-testid="constellation" onClick={() => onSelect("windows-shell")}>
      constellation
    </button>
  ),
}))

const OVERVIEW: MemoryOverview = {
  revision: '"memory-one"',
  enabled: true,
  page: "Keep tests portable.",
  page_text: "<!-- trim -->\nKeep tests portable.",
  suggestion: null,
  learner: { prompt_chars: 1_550, entries: 2, model: "local/chat", context: null },
  stats: {
    page_chars: 20,
    page_budget: 4000,
    kept: 2,
    set_aside: 1,
    lookup: "fast",
    disagreements: [],
    second_look: [],
  },
  capabilities: { words: true, meaning: true, ask: true },
  graph: {
    nodes: [
      {
        slug: "windows-shell",
        preview: "Windows tests need a POSIX shell.",
        updated_at: "2026-08-31T00:00:00Z",
        scope: ["global"],
        anchors: [],
        standing: true,
        superseded_by: null,
        second_look: [],
        degree: 1,
      },
    ],
    edges: [],
    total_nodes: 1,
    total_edges: 0,
    truncated: false,
    edges_truncated: false,
  },
}

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  vi.mocked(fetchMemory).mockResolvedValue(OVERVIEW)
  vi.mocked(fetchMemoryEntry).mockResolvedValue({
    slug: "windows-shell",
    body: "Windows tests need a POSIX shell.",
    updated_at: "2026-08-31T00:00:00Z",
    mentions: [],
    scope: ["global"],
    anchors: [],
    source: [],
    valid_from: null,
    superseded_by: null,
    links: { depends_on: [], contradicts: [] },
    second_look: [],
    history: [],
  })
  vi.mocked(searchMemory).mockResolvedValue({
    ok: true,
    query: "Windows",
    mode: "words",
    results: [
      {
        slug: "windows-shell",
        preview: "Windows tests need a POSIX shell.",
        updated_at: "2026-08-31T00:00:00Z",
        standing: true,
        mode: "words",
        rank: 1,
      },
    ],
  })
  vi.mocked(askMemory).mockResolvedValue({
    ok: true,
    answer: "POSIX 셸이 필요합니다 [[windows-shell]].",
    citations: ["windows-shell"],
    evidence: [],
    model: "local/answerer",
    usage: null,
    degraded: null,
  })
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.useRealTimers()
  vi.clearAllMocks()
})

async function render() {
  await act(async () => root.render(<Memory project="board" />))
  await act(async () => {})
}

async function fill(selector: string, value: string) {
  const field = container.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector)!
  const proto = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(field, value)
    field.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

async function enter(value: string) {
  const input = container.querySelector<HTMLInputElement>('[aria-label="Search memory"]')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

test("memory is a searchable place with three explicit modes", async () => {
  await render()

  expect(container.querySelector('[data-testid="constellation"]')).not.toBeNull()
  expect(container.textContent).toContain("2 kept")
  expect(container.querySelector('[data-mode="words"]')!.getAttribute("aria-pressed")).toBe("true")
  expect(container.querySelector('[data-mode="meaning"]')).not.toBeNull()
  expect(container.querySelector('[data-mode="ask"]')).not.toBeNull()
  expect(container.textContent).toContain("relationships form regions")
})

test("word search lists evidence and opens the selected memory", async () => {
  await render()
  await enter("Windows")
  await act(async () => container.querySelector<HTMLFormElement>("form")!.requestSubmit())

  expect(searchMemory).toHaveBeenCalledWith("board", "Windows", "words", true)
  expect(container.textContent).toContain("Windows tests need a POSIX shell.")
  await act(async () => {
    container.querySelector<HTMLElement>('[data-result="windows-shell"]')!.click()
  })
  expect(fetchMemoryEntry).toHaveBeenCalledWith("board", "windows-shell")
})

test("a late detail response cannot cross into another project", async () => {
  let finish!: (entry: Awaited<ReturnType<typeof fetchMemoryEntry>>) => void
  vi.mocked(fetchMemoryEntry).mockImplementationOnce(
    () => new Promise((resolve) => {
      finish = resolve
    }),
  )
  await render()
  await act(async () => container.querySelector<HTMLElement>('[data-testid="constellation"]')!.click())

  await act(async () => root.render(<Memory project="another" />))
  await act(async () => finish({
    slug: "windows-shell",
    body: "This belongs to the previous project.",
    updated_at: "2026-08-31T00:00:00Z",
    mentions: [],
    scope: [],
    anchors: [],
    source: [],
    valid_from: null,
    superseded_by: null,
    links: { depends_on: [], contradicts: [] },
    second_look: [],
    history: [],
  }))

  expect(container.querySelector('[data-memory="windows-shell"]')).toBeNull()
})

test("ask shows the answer and makes its citation selectable", async () => {
  await render()
  await act(async () => container.querySelector<HTMLElement>('[data-mode="ask"]')!.click())
  await enter("왜 깨지나요?")
  await act(async () => container.querySelector<HTMLFormElement>("form")!.requestSubmit())

  expect(askMemory).toHaveBeenCalledWith("board", "왜 깨지나요?", true)
  expect(container.textContent).toContain("POSIX 셸이 필요합니다")
  const citation = container.querySelector<HTMLElement>('[data-citation="windows-shell"]')!
  expect(citation).not.toBeNull()
})

test("changing the set-aside scope clears evidence from the old scope", async () => {
  await render()
  await enter("Windows")
  await act(async () => container.querySelector<HTMLFormElement>("form")!.requestSubmit())
  expect(container.querySelector('[data-result="windows-shell"]')).not.toBeNull()

  await act(async () => container.querySelector<HTMLInputElement>('.memory-past input')!.click())

  expect(container.querySelector('[data-result="windows-shell"]')).toBeNull()
  expect(container.textContent).toContain("Search, ask, or select a point")
})

test("changing search mode clears evidence from the previous mode", async () => {
  await render()
  await enter("Windows")
  await act(async () => container.querySelector<HTMLFormElement>("form")!.requestSubmit())
  expect(container.querySelector('[data-result="windows-shell"]')).not.toBeNull()

  await act(async () => container.querySelector<HTMLElement>('[data-mode="ask"]')!.click())

  expect(container.querySelector('[data-result="windows-shell"]')).toBeNull()
  expect(container.textContent).toContain("Search, ask, or select a point")
})

test("an open memory place refreshes after the learning interval", async () => {
  vi.useFakeTimers()
  vi.mocked(fetchMemory)
    .mockResolvedValueOnce(OVERVIEW)
    .mockResolvedValueOnce({
      ...OVERVIEW,
      stats: { ...OVERVIEW.stats!, kept: 3 },
    })
  await render()

  await act(async () => {
    await vi.advanceTimersByTimeAsync(MEMORY_REFRESH_MS)
  })

  expect(fetchMemory).toHaveBeenCalledTimes(2)
  expect(fetchMemory).toHaveBeenLastCalledWith("board", '"memory-one"')
  expect(container.textContent).toContain("3 kept")
})

test("an unconfigured model mode is disabled instead of silently falling back", async () => {
  vi.mocked(fetchMemory).mockResolvedValue({
    ...OVERVIEW,
    capabilities: { words: true, meaning: false, ask: false },
  })
  await render()

  expect(container.querySelector<HTMLButtonElement>('[data-mode="meaning"]')!.disabled).toBe(true)
  expect(container.querySelector<HTMLButtonElement>('[data-mode="ask"]')!.disabled).toBe(true)
  expect(container.textContent).toContain("meaning needs memory_embedder")
  expect(container.textContent).toContain("ask needs memory_searcher")
})

test("entry detail names directed relationships and keeps its history", async () => {
  vi.mocked(fetchMemoryEntry).mockResolvedValueOnce({
    slug: "windows-shell",
    body: "Windows tests need a POSIX shell.",
    updated_at: "2026-08-31T00:00:00Z",
    mentions: ["command-env"],
    scope: ["global"],
    anchors: [],
    source: ["person"],
    valid_from: "2026-08-30",
    superseded_by: "portable-shell",
    links: { depends_on: ["command-env"], contradicts: ["cmd-shell"] },
    second_look: [],
    history: [
      {
        at: "2026-08-30T00:00:00Z",
        writer: "person",
        did: "updated",
        slug: "windows-shell",
      },
    ],
  })
  await render()
  await act(async () => container.querySelector<HTMLElement>('[data-testid="constellation"]')!.click())

  expect(container.textContent).toContain("mentions →")
  expect(container.textContent).toContain("depends on →")
  expect(container.textContent).toContain("disagrees with ↔")
  expect(container.textContent).toContain("set aside for →")
  expect(container.textContent).toContain("history (1)")
  expect(container.querySelector('[data-related="command-env"]')).not.toBeNull()
  expect(container.querySelector('time[datetime="2026-08-30"]')?.textContent).toBe("2026-08-30")
})

test("a dangling mention keeps the current memory and explains why it did not open", async () => {
  vi.mocked(fetchMemoryEntry)
    .mockResolvedValueOnce({
      slug: "windows-shell",
      body: "Windows tests need a POSIX shell.",
      updated_at: "2026-08-31T00:00:00Z",
      mentions: ["missing-rule"],
      scope: ["global"],
      anchors: [],
      source: [],
      valid_from: null,
      superseded_by: null,
      links: { depends_on: [], contradicts: [] },
      second_look: [],
      history: [],
    })
    .mockResolvedValueOnce(null)
  await render()
  await act(async () => container.querySelector<HTMLElement>('[data-testid="constellation"]')!.click())

  await act(async () => container.querySelector<HTMLElement>('[data-related="missing-rule"]')!.click())

  expect(container.querySelector('[data-memory="windows-shell"]')).not.toBeNull()
  expect(container.textContent).toContain("The memory named missing-rule is not available.")
})

test("a project with no long memory explains the empty place", async () => {
  vi.mocked(fetchMemory).mockResolvedValue({
    enabled: false,
    page: null,
    page_text: "",
    suggestion: null,
    stats: null,
    capabilities: { words: false, meaning: false, ask: false },
    graph: {
      nodes: [],
      edges: [],
      total_nodes: 0,
      total_edges: 0,
      truncated: false,
      edges_truncated: false,
    },
  })
  await render()

  expect(container.textContent).toContain("This project keeps no long memory")
  expect(container.querySelector("form")).toBeNull()
})

// -- a person's writes ---------------------------------------------------------

test("a person edits the page as written and the place rereads itself", async () => {
  vi.mocked(putMemoryPage).mockResolvedValue({ ok: true })
  await render()

  await act(async () => container.querySelector<HTMLElement>('[data-do="edit-page"]')!.click())
  expect(container.querySelector<HTMLTextAreaElement>('[aria-label="Page"]')!.value).toBe(
    "<!-- trim -->\nKeep tests portable.",
  )
  await fill('[aria-label="Page"]', "Keep tests portable.\nDates are ISO.")
  await act(async () => container.querySelector<HTMLFormElement>("form.memory-page-edit")!.requestSubmit())

  expect(putMemoryPage).toHaveBeenCalledWith("board", "Keep tests portable.\nDates are ISO.")
  expect(fetchMemory).toHaveBeenCalledTimes(2)
  expect(container.querySelector('[aria-label="Page"]')).toBeNull()
})

test("the last pass's suggestion can land on the page or be let go", async () => {
  vi.mocked(fetchMemory).mockResolvedValue({ ...OVERVIEW, suggestion: "Require ISO dates." })
  vi.mocked(settleMemorySuggestion).mockResolvedValue({ ok: true, suggestion: "Require ISO dates." })
  await render()

  expect(container.textContent).toContain("Require ISO dates.")
  await act(async () => container.querySelector<HTMLElement>('[data-do="accept-suggestion"]')!.click())
  expect(settleMemorySuggestion).toHaveBeenCalledWith("board", true)
  await act(async () => container.querySelector<HTMLElement>('[data-do="dismiss-suggestion"]')!.click())
  expect(settleMemorySuggestion).toHaveBeenLastCalledWith("board", false)
  expect(fetchMemory).toHaveBeenCalledTimes(3)
})

test("a person keeps a memory from the board and it opens", async () => {
  vi.mocked(keepMemory).mockResolvedValue({ ok: true, slug: "feeds-order" })
  await render()

  await fill('[aria-label="Memory name"]', "feeds-order")
  await fill('[aria-label="What stays true"]', "Feeds are imported oldest first.")
  await act(async () => container.querySelector<HTMLFormElement>("form.memory-keep")!.requestSubmit())

  expect(keepMemory).toHaveBeenCalledWith("board", "feeds-order", "Feeds are imported oldest first.")
  expect(fetchMemory).toHaveBeenCalledTimes(2)
  expect(fetchMemoryEntry).toHaveBeenCalledWith("board", "feeds-order")
  expect(container.querySelector<HTMLInputElement>('[aria-label="Memory name"]')!.value).toBe("")
})

test("a standing memory can be set aside for its replacement", async () => {
  vi.mocked(setAsideMemory).mockResolvedValue({ ok: true })
  await render()
  await act(async () => container.querySelector<HTMLElement>('[data-testid="constellation"]')!.click())

  await fill('[aria-label="Replaced by"]', "portable-shell")
  await act(async () => container.querySelector<HTMLFormElement>("form.memory-set-aside")!.requestSubmit())

  expect(setAsideMemory).toHaveBeenCalledWith("board", "windows-shell", "portable-shell")
  expect(fetchMemoryEntry).toHaveBeenLastCalledWith("board", "windows-shell")
  expect(fetchMemory).toHaveBeenCalledTimes(2)
})

test("a refused write stays visible as a result and rereads nothing", async () => {
  vi.mocked(keepMemory).mockResolvedValue({
    ok: false,
    error: "'leaner': depends_on names 'ghost', and no such entry exists",
  })
  await render()

  await fill('[aria-label="Memory name"]', "leaner")
  await fill('[aria-label="What stays true"]', "Leans on air.")
  await act(async () => container.querySelector<HTMLFormElement>("form.memory-keep")!.requestSubmit())

  expect(container.textContent).toContain("no such entry exists")
  expect(fetchMemory).toHaveBeenCalledTimes(1)
  expect(container.querySelector<HTMLInputElement>('[aria-label="Memory name"]')!.value).toBe("leaner")
})

test("a source run whose record still names its task opens that run", async () => {
  const onOpenRun = vi.fn()
  vi.mocked(fetchMemoryEntry).mockResolvedValueOnce({
    slug: "windows-shell",
    body: "Windows tests need a POSIX shell.",
    updated_at: "2026-08-31T00:00:00Z",
    mentions: [],
    scope: ["global"],
    anchors: [],
    source: ["20260824T010000-aaaaaaaa", "20260824T020000-bbbbbbbb"],
    sources: [
      { run_id: "20260824T010000-aaaaaaaa", task: "importer" },
      { run_id: "20260824T020000-bbbbbbbb", task: null },
    ],
    valid_from: null,
    superseded_by: null,
    links: { depends_on: [], contradicts: [] },
    second_look: [],
    history: [],
  })
  await act(async () => root.render(<Memory project="board" onOpenRun={onOpenRun} />))
  await act(async () => {})
  await act(async () => container.querySelector<HTMLElement>('[data-testid="constellation"]')!.click())

  const known = container.querySelector<HTMLElement>('[data-source="20260824T010000-aaaaaaaa"]')!
  expect(known.tagName).toBe("BUTTON")
  await act(async () => known.click())
  expect(onOpenRun).toHaveBeenCalledWith("importer", "20260824T010000-aaaaaaaa")

  // The other record is gone with runs/, so the id is said but goes nowhere.
  const gone = container.querySelector<HTMLElement>('[data-source="20260824T020000-bbbbbbbb"]')!
  expect(gone.tagName).not.toBe("BUTTON")
  expect(gone.textContent).toContain("20260824T020000-bbbbbbbb")
})

test("arriving with a memory in focus opens it without a search", async () => {
  await act(async () => root.render(<Memory project="board" focus={{ slug: "windows-shell" }} />))
  await act(async () => {})

  expect(fetchMemoryEntry).toHaveBeenCalledWith("board", "windows-shell")
  expect(container.querySelector('[data-memory="windows-shell"]')).not.toBeNull()
  expect(searchMemory).not.toHaveBeenCalled()
})

test("recent learning says what each pass kept, set aside, let go, or why it failed", async () => {
  vi.mocked(fetchMemory).mockResolvedValue({
    ...OVERVIEW,
    learning: [
      {
        at: "2026-09-02T03:00:00+00:00",
        read: 3,
        upto: null,
        kept: [],
        set_aside: [],
        dropped: [],
        error: "ValueError: the answer holds no JSON object",
        page: null,
        let_go: [],
      },
      {
        at: "2026-09-01T03:00:00+00:00",
        read: 2,
        upto: "20260901T010000-aaaaaaaa",
        kept: ["windows-shell"],
        set_aside: ["old-shell"],
        dropped: ["'bad slug': not a plain slug"],
        error: null,
        page: null,
        let_go: [],
      },
    ],
  })
  await render()

  const learning = container.querySelector<HTMLDetailsElement>(".memory-learning")!
  expect(learning).not.toBeNull()
  const passes = learning.querySelectorAll("li")
  expect(passes).toHaveLength(2)
  expect(passes[0].getAttribute("data-failed")).toBe("true")
  expect(passes[0].textContent).toContain("the answer holds no JSON object")
  expect(passes[1].textContent).toContain("read 2 records")
  expect(passes[1].textContent).toContain("'bad slug': not a plain slug")
  expect(passes[1].querySelector('[data-related="old-shell"]')).not.toBeNull()

  await act(async () => passes[1].querySelector<HTMLElement>('[data-related="windows-shell"]')!.click())
  expect(fetchMemoryEntry).toHaveBeenCalledWith("board", "windows-shell")
})

test("a memory with no passes yet draws no learning section", async () => {
  await render()
  expect(container.querySelector(".memory-learning")).toBeNull()
})


// -- how much room memory takes ---------------------------------------------

test("the caption puts the page and the learner's next question against their limits", async () => {
  vi.mocked(fetchMemory).mockResolvedValue({
    ...OVERVIEW,
    stats: { ...OVERVIEW.stats!, page_chars: 3_300, page_budget: 4_000 },
    learner: { prompt_chars: 26_000, entries: 40, model: "local/learner", context: 8_000 },
  })
  await render()

  const page = container.querySelector<HTMLElement>('[data-gauge="page"]')!
  expect(page.dataset.level).toBe("near")
  expect(page.textContent).toContain("3,300 / 4,000 chars")
  const learner = container.querySelector<HTMLElement>('[data-gauge="learner"]')!
  // Four characters a token until a pass has counted: 26,000 characters is about 6,500 tokens.
  expect(learner.textContent).toContain("≈6,500 / 8,000 tokens")
  expect(learner.dataset.level).toBe("near")
  expect(learner.getAttribute("title")).toContain("assuming four characters a token")
})

test("with no window declared the learner's question is shown as it was measured", async () => {
  await render()

  const learner = container.querySelector<HTMLElement>('[data-gauge="learner"]')!
  expect(learner.dataset.level).toBe("unbounded")
  expect(learner.textContent).toContain("1,550 chars")
  expect(learner.querySelector(".gauge-track")).toBeNull()
})

test("once a pass has counted, the learner's question is converted at that pass's own ratio", async () => {
  vi.mocked(fetchMemory).mockResolvedValue({
    ...OVERVIEW,
    learner: { prompt_chars: 3_000, entries: 12, model: "local/learner", context: 8_000 },
    learning: [
      {
        at: "2026-09-10T03:00:00+00:00",
        read: 3,
        upto: "c",
        kept: [],
        set_aside: [],
        dropped: [],
        error: null,
        page: null,
        let_go: [],
        prompt_chars: 1_500,
        prompt_tokens: 500,
        context: 8_000,
      },
    ],
  })
  await render()

  const learner = container.querySelector<HTMLElement>('[data-gauge="learner"]')!
  // Three characters a token, as that pass measured: 3,000 characters is about 1,000 tokens.
  expect(learner.textContent).toContain("≈1,000 / 8,000 tokens")
  expect(learner.dataset.level).toBe("ok")
  expect(learner.getAttribute("title")).toContain("as the last pass counted")
})

test("the page editor counts the draft as a run reads it and never refuses to save", async () => {
  vi.mocked(putMemoryPage).mockResolvedValue({ ok: true })
  vi.mocked(fetchMemory).mockResolvedValue({
    ...OVERVIEW,
    stats: { ...OVERVIEW.stats!, page_chars: 20, page_budget: 40 },
  })
  await render()
  await act(async () => container.querySelector<HTMLElement>('[data-do="edit-page"]')!.click())

  const gauge = () => container.querySelector<HTMLElement>('.memory-page-edit [data-gauge="as a run reads it"]')!
  // The fixture's page is a comment and then "Keep tests portable.": the comment does not count.
  expect(gauge().textContent).toContain("20 / 40 chars")
  expect(gauge().dataset.level).toBe("ok")

  await fill('[aria-label="Page"]', "<!-- trim -->\nKeep tests portable. Dates are ISO. Never push.")
  expect(gauge().textContent).toContain("47 / 40 chars")
  expect(gauge().dataset.level).toBe("over")
  expect(gauge().textContent).toContain("over the limit")
  expect(container.querySelector<HTMLButtonElement>('[data-do="save-page"]')!.disabled).toBe(false)
})
