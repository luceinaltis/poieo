/**
 * Photograph the pose sheet.
 *
 *   node pose_shot.mjs out.png path/to/web-ui [page] [query]
 *
 * `page` picks the sheet: pose.html by default, bench.html for the whole
 * bench seen through the room's own camera. `query` is handed to it, e.g.
 * `axis=1,0,0` to shoot a candidate swing.
 *
 * Starts a vite dev server of its own, because the sheet is a dev-only page and
 * the daemon's build does not contain it. Playwright is not a dependency of the
 * app, so this is run from wherever it happens to be installed and told where
 * the web-ui lives. Waits for the page to say it has
 * finished drawing rather than for a timer, so a slow model load cannot produce
 * a blank sheet that looks like a broken rig.
 */

import { spawn } from "node:child_process"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { chromium } from "playwright"

const out = process.argv[2] ?? "pose.png"
// Not `page`: playwright's own page shadows it inside the run, and the
// request quietly became /tools/[object Object].
const sheet = process.argv[4] || "pose.html"
const query = process.argv[5] ? `?${process.argv[5]}` : ""
const root = process.argv[3]
  ? path.resolve(process.argv[3])
  : path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const PORT = 5199

const vite = spawn(
  process.platform === "win32" ? "npx.cmd" : "npx",
  ["vite", "--port", String(PORT), "--strictPort"],
  { cwd: root, stdio: "ignore", shell: process.platform === "win32" },
)

/** Kill the tree: npx sits between us and the server that holds the port. */
const stop = () => {
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(vite.pid), "/T", "/F"], { stdio: "ignore" })
  } else {
    vite.kill()
  }
}

;(async () => {
  const browser = await chromium.launch({
    args: ["--use-gl=angle", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
  })
  const page = await browser.newPage({ viewport: { width: 1560, height: 760 } })

  const problems = []
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()))
  page.on("pageerror", (e) => problems.push(String(e)))

  // The dev server needs a moment to bind; retry rather than guess how long.
  // `localhost`, not 127.0.0.1: vite listens on the IPv6 loopback, and a quiet
  // connection refusal here reads exactly like a model that failed to load.
  let arrived = false
  for (let tries = 0; tries < 40 && !arrived; tries++) {
    try {
      await page.goto(`http://localhost:${PORT}/tools/${sheet}${query}`)
      arrived = true
    } catch {
      await page.waitForTimeout(500)
    }
  }
  console.log(`  ${sheet}${query}`)
  if (!arrived) {
    console.log("  the dev server never answered")
    stop()
    process.exit(1)
  }

  try {
    await page.waitForSelector("body[data-ready]", { timeout: 30000 })
  } catch {
    console.log("  the sheet never finished drawing")
  }
  await page.screenshot({ path: out, fullPage: true })
  console.log(`  wrote ${out}`)
  for (const line of problems.slice(0, 6)) console.log(`    ${line.slice(0, 200)}`)

  await browser.close()
  stop()
  process.exit(0)
})()
