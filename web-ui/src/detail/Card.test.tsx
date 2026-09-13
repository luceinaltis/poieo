import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const fetchCard = vi.hoisted(() => vi.fn<typeof import("../api").fetchCard>())
const rewriteCard = vi.hoisted(() => vi.fn<typeof import("../api").rewriteCard>())
const setAside = vi.hoisted(() => vi.fn<typeof import("../api").setAside>())
const fetchFolders = vi.hoisted(() => vi.fn<typeof import("../api").fetchFolders>())

// The reads and the two writes this file already covers are stubs; everything
// else stays the real module, so the rename test below watches the request the
// daemon would actually receive rather than a mock agreeing with itself.
vi.mock("../api", async () => ({
  ...(await vi.importActual<typeof import("../api")>("../api")),
  fetchCard,
  rewriteCard,
  setAside,
  fetchFolders,
}))

import { Card } from "./Card"

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  fetchCard.mockReset()
  rewriteCard.mockReset()
  setAside.mockReset()
  fetchFolders.mockReset()
  fetchFolders.mockResolvedValue([])
  onSetAside.mockReset()
  fetchCard.mockResolvedValue({
    task: "chores",
    text: "name: Chores\nfolder: ../work\nprompt: tidy\n",
    name: "Chores",
    folder: "../work",
    prompt: "tidy",
    plain: false,
    enabled: true,
  })
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  // Whatever a test stubbed on the global, including a failed one: a leaked
  // fetch stub would be answered by the next file's test, not this one's.
  vi.unstubAllGlobals()
})

const onSetAside = vi.fn()
const onAlike = vi.fn()

test("a task can explicitly allow automatic application with checks", async () => {
  fetchCard.mockResolvedValue({ task: "chores", text: "prompt: tidy\n", name: "Chores", folder: "../work",
    prompt: "tidy", plain: true, enabled: true, keeps_copies: true })
  rewriteCard.mockResolvedValue({ ok: true, live: true })
  await open()
  await act(async () => container.querySelector<HTMLElement>(".apply-settings summary")!.click())
  await act(async () => container.querySelector<HTMLInputElement>('input[value="auto"]')!.click())
  expect(container.querySelector<HTMLButtonElement>('[data-do="save-card"]')!.disabled).toBe(true)
  await act(async () => {
    const area = container.querySelector<HTMLTextAreaElement>('[name="application-checks"]')!
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(area, "npm test")
    area.dispatchEvent(new Event("input", { bubbles: true }))
  })
  await save()
  expect(rewriteCard).toHaveBeenCalledWith("board", "chores", expect.objectContaining({
    apply: { mode: "auto", paths: [], checks: ["npm test"], timeout: 120 },
  }))
})

async function render() {
  onAlike.mockReset()
  await act(async () => {
    root.render(
      <Card project="board" task="chores" onSetAside={onSetAside} onAlike={onAlike} />,
    )
  })
}

async function open() {
  await render()
  await act(async () => {
    container.querySelector<HTMLElement>(".card-open")!.click()
  })
}

function editor(): HTMLTextAreaElement {
  return container.querySelector<HTMLTextAreaElement>(".card-text")!
}

async function type(text: string) {
  await act(async () => {
    const box = editor()
    const write = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!
    write.call(box, text)
    box.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

async function save() {
  await act(async () => {
    container.querySelector<HTMLElement>('[data-do="save-card"]')!.click()
  })
}

test("shut, the card costs nothing: no fetch until somebody opens it", async () => {
  await render()
  expect(fetchCard).not.toHaveBeenCalled()

  await act(async () => {
    container.querySelector<HTMLElement>(".card-open")!.click()
  })
  expect(fetchCard).toHaveBeenCalledWith("board", "chores")
  expect(editor().value).toContain("tidy")
})

test("task setup exposes whether its disclosure is open", async () => {
  await render()
  const disclosure = container.querySelector<HTMLElement>(".card-open")!

  expect(disclosure.textContent).toBe("Task setup")
  expect(disclosure.getAttribute("aria-expanded")).toBe("false")

  await act(async () => disclosure.click())
  expect(disclosure.getAttribute("aria-expanded")).toBe("true")
})

test("saving sends the text as it stands, and says the next run reads it", async () => {
  rewriteCard.mockResolvedValue({ ok: true, task: "chores", live: true })
  await open()
  await type("name: Chores\nfolder: ../work\nprompt: sharper\n")
  await save()

  expect(rewriteCard).toHaveBeenCalledWith(
    "board",
    "chores",
    "name: Chores\nfolder: ../work\nprompt: sharper\n",
  )
  expect(container.textContent).toContain("next run")
})

test("an edit the daemon will not adopt says so instead of pretending", async () => {
  // The route answers live:false when more than the prompt changed -- the
  // daemon refuses to half-adopt, and the person deserves the same sentence
  // the log gets.
  rewriteCard.mockResolvedValue({ ok: true, task: "chores", live: false })
  await open()
  await type("name: Chores\nfolder: ../elsewhere\nprompt: tidy\n")
  await save()

  expect(container.textContent).toContain("restart")
})

test("a refusal is shown and the text stays for a second try", async () => {
  rewriteCard.mockResolvedValue({ ok: false, error: "the folder it would work in is not there" })
  await open()
  await type("name: Chores\nfolder: ../gone\nprompt: tidy\n")
  await save()

  expect(container.querySelector('[role="alert"]')!.textContent).toContain("not there")
  expect(editor().value).toContain("../gone")
  // ...and no half of the success wording beside it: "Saved -- but" under a
  // refusal is two sentences disagreeing about what just happened.
  expect(container.textContent).not.toContain("Saved")
})

test("a refusal with nothing to say still says something", async () => {
  // `ok: false` and no sentence is a shape `post` produces from a body that
  // did not parse. Guarded on `refused.error`, this surface showed a disabled
  // button and no reason -- the same defect the make form had, written again
  // in a new file while that one was being fixed.
  rewriteCard.mockResolvedValue({ ok: false })
  await open()
  await type("name: Chores\nfolder: ../work\nprompt: tidy the hallway\n")
  await save()

  expect(container.querySelector('[role="alert"]')!.textContent).toContain("didn't work")
})

test("closing and reopening does not fetch the card again over an edit", async () => {
  await open()
  await type("name: Chores\nfolder: ../work\nprompt: half-finished thought")
  await act(async () => container.querySelector<HTMLElement>(".card-open")!.click())
  await act(async () => container.querySelector<HTMLElement>(".card-open")!.click())

  expect(fetchCard).toHaveBeenCalledTimes(1)
  expect(editor().value).toContain("half-finished thought")
})

test("nothing changed, nothing to save", async () => {
  await open()
  const button = container.querySelector<HTMLButtonElement>('[data-do="save-card"]')!
  expect(button.disabled).toBe(true)

  await type("name: Chores\nfolder: ../work\nprompt: reworded\n")
  expect(button.disabled).toBe(false)
})

test("a card the daemon cannot hand back says so rather than an empty editor", async () => {
  fetchCard.mockResolvedValue(null)
  await open()
  expect(container.textContent).toContain("could not be read")
  expect(container.querySelector(".card-text")).toBeNull()
})

test("set aside asks twice, and the second press is the one that acts", async () => {
  setAside.mockResolvedValue({ ok: true, task: "chores", kept: "cards/.set-aside/chores.yaml" })
  await open()

  const button = () => container.querySelector<HTMLElement>('[data-do="set-aside"]')!
  await act(async () => button().click())
  // First press arms it; nothing has left the machine.
  expect(setAside).not.toHaveBeenCalled()
  expect(button().textContent).toContain("sure")

  await act(async () => button().click())
  expect(setAside).toHaveBeenCalledWith("board", "chores")
  // The sentence says where the file went and what a restart does.
  expect(container.textContent).toContain(".set-aside")
  expect(container.textContent).toContain("restart")
  expect(onSetAside).toHaveBeenCalled()
})

test("an armed set-aside stands down if the person edits instead", async () => {
  await open()
  const button = () => container.querySelector<HTMLElement>('[data-do="set-aside"]')!
  await act(async () => button().click())
  await type("name: Chores\nfolder: ../work\nprompt: second thoughts")

  expect(button().textContent).not.toContain("sure")
  expect(setAside).not.toHaveBeenCalled()
})

test("a refused set-aside says why and does not claim the file moved", async () => {
  setAside.mockResolvedValue({ ok: false, error: "the card could not be moved" })
  await open()
  const button = () => container.querySelector<HTMLElement>('[data-do="set-aside"]')!
  await act(async () => button().click())
  await act(async () => button().click())

  expect(container.querySelector('[role="alert"]')!.textContent).toContain("could not be moved")
  expect(container.textContent).not.toContain("restart")
})

test("make one like it hands the three fields up, not the yaml", async () => {
  // The make panel asks for name, folder and prompt; handing it raw YAML
  // would mean parsing it twice. The fields came parsed from the daemon.
  await open()
  await act(async () => {
    container.querySelector<HTMLElement>('[data-do="make-alike"]')!.click()
  })

  expect(onAlike).toHaveBeenCalledWith({
    name: "Chores",
    folder: "../work",
    prompt: "tidy",
  })
})

test("a plain card opens as the three fields, not as a file", async () => {
  // The person filled a form to make this card; handing them YAML to edit
  // it would be giving the form and then taking it away. Values only -- the
  // daemon owns the spelling, through the same dump make uses.
  fetchCard.mockResolvedValue({
    task: "chores",
    text: "name: Chores\nfolder: ../work\nprompt: tidy\n",
    name: "Chores",
    folder: "../work",
    prompt: "tidy",
    plain: true,
    enabled: true,
  })
  rewriteCard.mockResolvedValue({ ok: true, task: "chores", live: true })
  await open()

  expect(container.querySelector(".card-text")).toBeNull()
  const prompt = container.querySelector<HTMLTextAreaElement>(".card-field-prompt")!
  expect(prompt.value).toBe("tidy")
  expect(container.querySelector<HTMLInputElement>(".card-field-name")!.value).toBe("Chores")
  expect(container.querySelector<HTMLInputElement>(".card-field-folder")!.value).toBe("../work")

  // Nothing changed, nothing to save -- same rule as the file mode.
  const save = () => container.querySelector<HTMLButtonElement>('[data-do="save-card"]')!
  expect(save().disabled).toBe(true)

  await act(async () => {
    const write = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!
    write.call(prompt, "sharper")
    prompt.dispatchEvent(new Event("input", { bubbles: true }))
  })
  expect(save().disabled).toBe(false)
  await act(async () => save().click())

  // Fields go over the wire; the daemon spells the file.
  expect(rewriteCard).toHaveBeenCalledWith("board", "chores", {
    name: "Chores",
    folder: "../work",
    prompt: "sharper",
  })
  expect(container.textContent).toContain("next run")
})

test("a switched-off plain card carries its switch, and saving sends the flip", async () => {
  // "Save without starting" says "start it from there" of the board, and the
  // form was the only place on the board that could -- and it had no switch.
  fetchCard.mockResolvedValue({
    task: "chores",
    text: "name: Chores\nfolder: ../work\nprompt: tidy\nenabled: false\n",
    name: "Chores",
    folder: "../work",
    prompt: "tidy",
    plain: true,
    enabled: false,
  })
  rewriteCard.mockResolvedValue({ ok: true, task: "chores", live: true })
  await open()

  const on = () => container.querySelector<HTMLInputElement>(".card-field-switch")!
  const save = () => container.querySelector<HTMLButtonElement>('[data-do="save-card"]')!
  expect(on().checked).toBe(false)
  expect(save().disabled).toBe(true)

  await act(async () => on().click())
  expect(on().checked).toBe(true)
  expect(save().disabled).toBe(false)

  // Back where it was is nothing to save, the rule every other field follows.
  await act(async () => on().click())
  expect(save().disabled).toBe(true)
  await act(async () => on().click())
  await act(async () => save().click())

  // The switch rides with the three fields only when it moved: absent means
  // unchanged to the daemon, and a prompt tweak must not send one either way.
  expect(rewriteCard).toHaveBeenCalledWith("board", "chores", {
    name: "Chores",
    folder: "../work",
    prompt: "tidy",
    enabled: true,
  })
  expect(container.textContent).toContain("switched on")
  expect(container.textContent).not.toContain("next run")

  // Saved is the new baseline: the switch does not read as an edit again.
  expect(save().disabled).toBe(true)
})

test("a switch flipped beside a moved folder does not talk over the restart", async () => {
  // The daemon says `live: false` of a save that moved the folder, whatever
  // else rode along. The switch line is said beside that, never instead.
  fetchCard.mockResolvedValue({
    task: "chores",
    text: "name: Chores' + esc + 'folder: ../work' + esc + 'prompt: tidy' + esc + 'enabled: false' + esc + '",
    name: "Chores",
    folder: "../work",
    prompt: "tidy",
    plain: true,
    enabled: false,
  })
  rewriteCard.mockResolvedValue({ ok: true, task: "chores", live: false })
  await open()

  await act(async () => container.querySelector<HTMLInputElement>(".card-field-switch")!.click())
  await act(async () => {
    const folder = container.querySelector<HTMLInputElement>(".card-field-folder")!
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(folder, "../other")
    folder.dispatchEvent(new Event("input", { bubbles: true }))
  })
  await act(async () => container.querySelector<HTMLButtonElement>('[data-do="save-card"]')!.click())

  expect(rewriteCard).toHaveBeenCalledWith("board", "chores", {
    name: "Chores",
    folder: "../other",
    prompt: "tidy",
    enabled: true,
  })
  expect(container.textContent).toContain("Switched on")
  expect(container.textContent).toContain("restarts")
})

test("a card edited as a file has no switch: the file already says it", async () => {
  await open()
  expect(container.querySelector(".card-field-switch")).toBeNull()
})

test("a plain card's folder can be chosen from the project", async () => {
  fetchCard.mockResolvedValue({
    task: "chores",
    text: "name: Chores\nfolder: ../work\nprompt: tidy\n",
    name: "Chores",
    folder: "../work",
    prompt: "tidy",
    plain: true,
    enabled: true,
  })
  fetchFolders.mockResolvedValue([
    { path: "..", name: "this project" },
    { path: "../work", name: "work" },
  ])
  rewriteCard.mockResolvedValue({ ok: true, task: "chores", live: false })
  await open()
  await act(async () => {})

  const pick = container.querySelector<HTMLSelectElement>('select[name="folder-pick"]')!
  // Opens on the folder the card has, when the list has it.
  expect(pick.value).toBe("../work")
  const save = () => container.querySelector<HTMLButtonElement>('[data-do="save-card"]')!
  expect(save().disabled).toBe(true)

  await act(async () => {
    pick.value = ".."
    pick.dispatchEvent(new Event("change", { bubbles: true }))
  })
  expect(container.querySelector<HTMLInputElement>(".card-field-folder")!.value).toBe("..")
  expect(save().disabled).toBe(false)
  await act(async () => save().click())
  expect(rewriteCard).toHaveBeenCalledWith("board", "chores", {
    name: "Chores",
    folder: "..",
    prompt: "tidy",
  })
})

test("a plain card shows its schedule, and a changed one is sent and waits for a restart", async () => {
  fetchCard.mockResolvedValue({
    task: "chores",
    text: "name: Chores\nfolder: ../work\nprompt: tidy\nevery: 15m\n",
    name: "Chores",
    folder: "../work",
    prompt: "tidy",
    plain: true,
    enabled: true,
    schedule: "15m",
  })
  rewriteCard.mockResolvedValue({ ok: true, task: "chores", live: false })
  await open()

  const schedule = () => container.querySelector<HTMLInputElement>(".card-field-schedule")!
  expect(schedule().value).toBe("15m")
  const save = () => container.querySelector<HTMLButtonElement>('[data-do="save-card"]')!
  expect(save().disabled).toBe(true)

  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(schedule(), "0 2 * * *")
    schedule().dispatchEvent(new Event("input", { bubbles: true }))
  })
  expect(save().disabled).toBe(false)
  await act(async () => save().click())

  expect(rewriteCard).toHaveBeenCalledWith("board", "chores", {
    name: "Chores",
    folder: "../work",
    prompt: "tidy",
    schedule: "0 2 * * *",
  })
  expect(container.textContent).toContain("restarts")
})

test("a card carrying more than the three fields still opens as a file", async () => {
  fetchCard.mockResolvedValue({
    task: "chores",
    text: "name: Chores\nfolder: ../work\nprompt: tidy\nevery: 15m\n",
    name: "Chores",
    folder: "../work",
    prompt: "tidy",
    plain: false,
    enabled: true,
  })
  await open()

  expect(container.querySelector(".card-text")).not.toBeNull()
  expect(container.querySelector(".card-field-prompt")).toBeNull()
})

test("renaming sends the new name to the card's own route, and nothing else", async () => {
  // The filename is the task's identity, so this is a PATCH of the file's
  // name and no edit inside it -- asserted on the request itself, because a
  // caller that agreed with a mock about the wrong URL is the failure that
  // left this half unbuilt.
  const fetchStub = vi.fn<typeof fetch>(async () =>
    new Response(
      JSON.stringify({ ok: true, task: "errands", path: "cards/errands.yaml" }),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  )
  vi.stubGlobal("fetch", fetchStub)
  await open()

  await act(async () => {
    const box = container.querySelector<HTMLInputElement>(".card-rename-to")!
    const write = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!
    write.call(box, "Errands")
    box.dispatchEvent(new Event("input", { bubbles: true }))
  })
  await act(async () => {
    container.querySelector<HTMLElement>('[data-do="rename"]')!.click()
  })

  expect(fetchStub).toHaveBeenCalledTimes(1)
  const [path, init] = fetchStub.mock.calls[0]
  expect(path).toBe("/api/projects/board/tasks/chores")
  expect(init?.method).toBe("PATCH")
  if (typeof init?.body !== "string") throw new TypeError("expected a JSON request body")
  expect(JSON.parse(init.body)).toEqual({ name: "Errands" })
  // The daemon's own spelling of the new name, not the one that was typed.
  expect(container.textContent).toContain("errands")

  // And the fold stops offering to write into a file that has moved. Every
  // write on this panel addresses the card by its old name, so one sent after
  // the rename would answer 404 -- or, worse, land on a card somebody else
  // has since made under it. Asserted rather than assumed: put the guard back
  // to the one set aside alone raises and every other line here still passes,
  // which is exactly how it reached review without a test.
  expect(
    container.querySelector<HTMLButtonElement>('[data-do="save-card"]')!.disabled,
  ).toBe(true)
  expect(
    container.querySelector<HTMLButtonElement>('[data-do="set-aside"]')!.disabled,
  ).toBe(true)
})

test("a card is not renamed to the name it already has", async () => {
  await open()
  const button = () => container.querySelector<HTMLButtonElement>('[data-do="rename"]')!
  expect(button().disabled).toBe(true)
})
