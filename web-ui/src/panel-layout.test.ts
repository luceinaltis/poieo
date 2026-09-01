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

test("a phone panel hides the rail and stage it covers", () => {
  expect(CSS).toContain(
    `.shell-rail[data-covered="true"],\n  .shell-stage[data-drawer="true"] {\n    visibility: hidden;\n  }`,
  )
})

test("a phone panel fills the foreground it owns", () => {
  expect(CSS).toContain(
    `@media (max-width: 720px) {\n  :root {\n    --panel-width: 100vw;\n  }`,
  )
})
