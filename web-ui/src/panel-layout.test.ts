/// <reference types="node" />

/** The shared panel owns the foreground when it covers the stage on a phone. */

import { readFileSync } from "node:fs"
import { expect, test } from "vitest"

const CSS = ["src/index.css", "src/app.css"]
  .map((path) => readFileSync(path, "utf8"))
  .join("\n")
  .replace(/\r\n/g, "\n")

test("a panel sits above a sticky view", () => {
  expect(CSS).toMatch(/\.panel\s*\{[^}]*z-index:\s*2/s)
})

test("a phone panel hides the stage it covers, and starts under the bar's second row", () => {
  expect(CSS).toContain(
    `.shell-stage[data-drawer="true"] {\n    margin-right: 0;\n    visibility: hidden;\n  }`,
  )
  // Below a laptop's width the bar wraps into two rows, and the panel is
  // pinned to `--bar-height`, so the two-row height is named where the
  // wrapping is allowed -- and nowhere else, or a one-row bar would grow a
  // second row under a stage that reserved one.
  expect(CSS).toMatch(/@media \(max-width: 900px\) \{\n  :root \{\n    --bar-height: [\d.]+rem;/)
  const oneRowBar = CSS.match(/^\.shell-bar \{[^}]*\}/m)![0]
  expect(oneRowBar).not.toContain("flex-wrap")
})

test("a phone panel fills the foreground it owns", () => {
  expect(CSS).toMatch(/@media \(max-width: 720px\) \{\n  :root \{[^}]*--panel-width: 100vw;/)
})

test("the page's type follows the screen's width, and the shell follows the type", () => {
  // A 2000px screen at 100% showed the whole board in the middle of nowhere,
  // with type sized for a laptop. The root size grows with the width, and
  // the bar, the stage's header line and the panel are in rem so they grow
  // with it rather than staying the one fixed thing on the page.
  expect(CSS).toMatch(/html\s*\{[^}]*font-size:\s*clamp\(16px,[^)]*vw[^)]*,\s*22px\)/s)
  expect(CSS).toMatch(/--bar-height:\s*[\d.]+rem/)
  expect(CSS).toMatch(/--stage-head:\s*[\d.]+rem/)
  expect(CSS).toMatch(/--panel-width:\s*min\([\d.]+rem,\s*100vw\)/)
})

test("the board's own type is pinned, so the fit alone magnifies it", () => {
  // The board is laid out in px and magnified by its fit exactly as far as
  // the root type grew. Left to inherit that root size as well, its words
  // grew twice over and the warning line on every card ran off the edge.
  const board = readFileSync("src/skins/basic/basic.css", "utf8").replace(/\r\n/g, "\n")
  expect(board).toMatch(/\.basic\s*\{[^}]*font-size:\s*16px/s)
})
