/**
 * Photograph the running page, so a change can be looked at.
 *
 *   node shot.js out.png [skin] [width] [height] [settleMs]
 *
 * Chooses the skin through localStorage before the page boots, waits for the
 * canvas to have drawn, then saves a screenshot. WebGL needs a real GPU path,
 * so the browser runs headed-but-offscreen rather than in headless-shell.
 */

const { chromium } = require("playwright")

const [, , out = "shot.png", skin = "atelier", w = "1200", h = "900", settle = "3000"] =
  process.argv

;(async () => {
  const browser = await chromium.launch({
    args: ["--use-gl=angle", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
  })
  const page = await browser.newPage({
    viewport: { width: Number(w), height: Number(h) },
    deviceScaleFactor: 1,
  })

  const problems = []
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text())
  })
  page.on("pageerror", (error) => problems.push(String(error)))

  await page.addInitScript((chosen) => {
    localStorage.setItem("poieo.skin", chosen)
    localStorage.removeItem("poieo.atelier.benches.v3")
  }, skin)

  await page.goto("http://127.0.0.1:8484/", { waitUntil: "networkidle" })
  await page.waitForTimeout(Number(settle))
  await page.screenshot({ path: out })

  console.log(`  wrote ${out}`)
  if (problems.length) {
    console.log("  page errors:")
    for (const line of problems.slice(0, 6)) console.log(`    ${line.slice(0, 200)}`)
  }
  await browser.close()
})()
