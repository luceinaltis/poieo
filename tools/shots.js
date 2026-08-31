/**
 * Photograph a running board, for the README and the site.
 *
 *   node tools/shots.js <base-url> <out-dir> <task-to-open>
 *
 * Run it through tools/shots.py, which builds the project it photographs and
 * starts the daemon; on its own this only knows how to point a browser at one.
 *
 * playwright is not a dependency of anything here and is not installed by the
 * gate -- this is a tool that makes pictures by hand, run perhaps twice a
 * year. `npm install --no-save playwright` before it, as web-ui/tools/shot.js
 * has always expected.
 */

const { chromium } = require("playwright")
const path = require("node:path")
const { pathToFileURL } = require("node:url")

const [, , base = "http://127.0.0.1:8484", out = "site/img", open] = process.argv

// Which task to open for the third picture. No default: an absent name would
// click whatever the empty string matched first, and the picture would be of
// some other task with nothing to review.
if (!open) {
  console.error("usage: node tools/shots.js <base-url> <out-dir> <task-to-open>")
  process.exit(2)
}

// One frame per picture, because the board is answering a different question
// in each: the cards want a column rather than a column in a field, and the
// drawer needs width or it clips its own diff.
const CARDS = { width: 820, height: 900 }
const OPENED = { width: 1440, height: 900 }

async function shot(browser, { skin, file, settle, size, then }) {
  const page = await browser.newPage({
    viewport: size,
    // Twice the pixels, so the picture stays sharp on the screens people read
    // a README on. Everything below is in CSS pixels regardless.
    deviceScaleFactor: 2,
    // The board prints times through the browser's locale, and a screenshot
    // with one reader's language in it is a screenshot about that reader.
    locale: "en-US",
  })
  const problems = []
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()))
  page.on("pageerror", (e) => problems.push(String(e)))

  await page.addInitScript((chosen) => localStorage.setItem("poieo.skin", chosen), skin)
  await page.goto(base + "/", { waitUntil: "networkidle" })
  await page.waitForTimeout(settle)
  if (then) await then(page)
  // PNG for boards of small text, JPEG for anything photographic, decided by
  // the extension the caller asked for.
  const jpeg = file.endsWith(".jpg")
  await page.screenshot({ path: `${out}/${file}`, ...(jpeg ? { type: "jpeg", quality: 88 } : {}) })
  await page.close()

  console.log(`  ${file}${problems.length ? `  (console: ${problems[0]})` : ""}`)
  return problems
}

async function social(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 640 } })
  const problems = []
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()))
  page.on("pageerror", (e) => problems.push(String(e)))

  const source = pathToFileURL(path.resolve(__dirname, "../site/social.html")).href
  await page.goto(source, { waitUntil: "networkidle" })
  await page.screenshot({ path: `${out}/social.png` })
  await page.close()

  console.log(`  social.png${problems.length ? `  (console: ${problems[0]})` : ""}`)
  return problems
}

;(async () => {
  const browser = await chromium.launch()

  const problems = []

  // finally, or a click that finds nothing leaves a browser running with
  // nobody holding its handle -- and the next run of this tool inherits it.
  // (The atelier workshop is not just unphotographed now, it is removed.)
  try {
    // The board once the seeded runs have finished. The long settle is the
    // wait for the runs the orchestrator set going to end.
    problems.push(...(await shot(browser, { skin: "basic", file: "board.png", size: CARDS, settle: 16000 })))

    // One task, opened: its runs, what it said, and the change waiting.
    problems.push(...(await shot(browser, {
      skin: "basic",
      file: "task.png",
      size: OPENED,
      settle: 2500,
      then: async (page) => {
        await page.getByText(open, { exact: true }).first().click()
        await page.waitForTimeout(1500)
      },
    })))

    problems.push(...(await social(browser)))
  } finally {
    await browser.close()
  }

  if (problems.length) {
    console.error(`\n${problems.length} console error(s); the pictures may not be what you meant:`)
    for (const problem of problems.slice(0, 5)) console.error(`  ${problem}`)
    process.exit(1)
  }
})().catch((error) => {
  // A click that found nothing, a board that stopped answering: without this
  // the failure arrives as an unhandled rejection, which buries the one line
  // saying what happened under a stack from inside playwright.
  console.error(`could not take the pictures: ${error.message ?? error}`)
  process.exit(1)
})
