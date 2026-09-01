import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { beforeEach, afterEach, expect, test, vi } from "vitest"

import { askMemory, fetchMemory, fetchMemoryEntry, searchMemory } from "../api"
import { MEMORY_REFRESH_MS, Memory } from "./Memory"
import type { MemoryOverview } from "./types"

vi.mock("../api", () => ({
  fetchMemory: vi.fn(),
  fetchMemoryEntry: vi.fn(),
  searchMemory: vi.fn(),
  askMemory: vi.fn(),
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
