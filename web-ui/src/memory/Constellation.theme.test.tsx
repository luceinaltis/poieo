import { act } from "react"
import { createRoot } from "react-dom/client"
import { expect, test, vi } from "vitest"
import { ThemeSwitch } from "../shell/ThemeSwitch"
import { Constellation } from "./Constellation"
import type { MemoryGraph } from "./types"

test("a visible memory graph repaints in the chosen theme without losing its zoom", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const style = document.createElement("style")
  style.textContent = `
    html { --ground: #100e0c; --text: #f0e7d9; --line: #7d7164; --dim: #a0958a;
      --ember: #d8a657; --stop: #e08a74; --paused: #7f9bb5; --paused-text: #9db4c9; }
    html[data-theme="light"] { --ground: #f8f5ef; --text: #221e18; }
  `
  document.head.append(style)
  localStorage.setItem("poieo.theme", "dark")
  vi.stubGlobal("matchMedia", () => ({ matches: true }))
  const labels: Array<{ text: string; color: string; x: number; y: number }> = []
  // jsdom has no canvas. Record its drawing output; do not replace the graph
  // or theme switch, whose interaction is what this test exercises.
  const drawing: Record<string | symbol, unknown> = {
    createRadialGradient: () => ({ addColorStop() {} }),
    fillText(text: string, x: number, y: number) {
      labels.push({ text, x, y, color: String(drawing.fillStyle) })
    },
  }
  const context = new Proxy(drawing, {
    get(target, key) { return key in target ? target[key] : () => {} },
  }) as unknown as CanvasRenderingContext2D
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context)
  vi.spyOn(HTMLCanvasElement.prototype, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 800, 600))
  const graph: MemoryGraph = {
    nodes: ["one", "two"].map((slug) => ({
      slug, preview: "", updated_at: "2026-01-01T00:00:00Z", scope: [], anchors: [],
      standing: true, superseded_by: null, second_look: [], degree: 0,
    })),
    edges: [], total_nodes: 2, total_edges: 0, truncated: false, edges_truncated: false,
  }
  const host = document.createElement("div")
  document.body.append(host)
  const root = createRoot(host)
  const latest = () => labels[labels.length - 1]
  try {
    await act(async () => root.render(<>
      <ThemeSwitch />
      <Constellation graph={graph} highlighted={new Set()} cited={new Set()} selected="two" onSelect={() => {}} />
    </>))
    await vi.waitFor(() => expect(latest()?.color).toBe("#f0e7d9"))
    const initial = { x: latest().x, y: latest().y }
    host.querySelector("canvas")!.dispatchEvent(new WheelEvent("wheel", { deltaY: -200, cancelable: true }))
    await vi.waitFor(() => expect({ x: latest().x, y: latest().y }).not.toEqual(initial))
    const zoomed = { x: latest().x, y: latest().y }
    await act(async () => host.querySelector("button")!.click())
    await vi.waitFor(() => expect(latest().color).toBe("#221e18"))
    expect({ x: latest().x, y: latest().y }).toEqual(zoomed)
    expect(host.querySelector("canvas")?.getAttribute("aria-label")).toContain("2 memories")
  } finally {
    await act(async () => root.unmount())
    host.remove()
    style.remove()
    localStorage.clear()
    delete document.documentElement.dataset.theme
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  }
})
