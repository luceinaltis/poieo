/**
 * Film one swing, frame by frame, so the motion can be judged instead of guessed.
 *
 *   node film.js out.png [frames] [stepFrames]
 *
 * The page's clock is taken over, so requestAnimationFrame only fires when we
 * say. The renderer advances its own animation a fixed step per frame, so N
 * ticks is N steps of the swing regardless of how long the screenshot took --
 * and the flow's state cannot change underneath us between shots.
 */

const { chromium } = require("playwright")

const [, , out = "film.png", count = "6", step = "9"] = process.argv
const FRAMES = Number(count)
const STEP = Number(step)

;(async () => {
  const browser = await chromium.launch({
    args: ["--use-gl=angle", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
  })
  // Twice the pixels in the crop, so a small figure can still be judged.
  const page = await browser.newPage({
    viewport: { width: 900, height: 700 },
    deviceScaleFactor: 2,
  })

  await page.addInitScript(() => {
    localStorage.setItem("poieo.skin", "atelier")
    localStorage.removeItem("poieo.atelier.benches.v3")
  })

  await page.goto("http://127.0.0.1:8484/", { waitUntil: "networkidle" })

  // Wait for a bench that is actually working; a still smith films badly.
  await page.waitForFunction(
    () => [...document.querySelectorAll(".atelier-tag")].some(
      (tag) => tag.dataset.status === "running",
    ),
    null,
    { timeout: 30000 },
  )

  const busy = await page.evaluate(() => {
    const tag = [...document.querySelectorAll(".atelier-tag")].find(
      (t) => t.dataset.status === "running",
    )
    const box = tag.getBoundingClientRect()
    return { x: box.left + box.width / 2, y: box.top }
  })

  // From here the page only moves when we advance it.
  await page.clock.install()
  // Pausing has to be forward of wherever the page's clock already is.
  await page.clock.pauseAt(new Date(Date.now() + 1000))

  const shots = []
  for (let i = 0; i < FRAMES; i += 1) {
    await page.clock.runFor(STEP * 16)
    const clip = {
      x: Math.max(0, busy.x - 150),
      y: Math.max(0, busy.y - 300),
      width: 300,
      height: 320,
    }
    shots.push(await page.screenshot({ clip }))
  }

  const sharp = shots.length
  console.log(`  ${sharp} frames, ${STEP} ticks apart`)

  // Stitch without an image library: write them out and let Pillow join them.
  const fs = require("fs")
  shots.forEach((buffer, index) => fs.writeFileSync(`frame-${index}.png`, buffer))
  fs.writeFileSync("frames.json", JSON.stringify({ count: shots.length, out }))

  await browser.close()
})()
