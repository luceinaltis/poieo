import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const fetchCard = vi.hoisted(() => vi.fn())
const rewriteCard = vi.hoisted(() => vi.fn())
const setAside = vi.hoisted(() => vi.fn())

vi.mock("../api", () => ({ fetchCard, rewriteCard, setAside }))

import { Card } from "./Card"

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  fetchCard.mockReset()
  rewriteCard.mockReset()
  setAside.mockReset()
  onSetAside.mockReset()
  fetchCard.mockResolvedValue({
    task: "chores",
    text: "name: Chores\nfolder: ../work\nprompt: tidy\n",
    name: "Chores",
    folder: "../work",
    prompt: "tidy",
  })
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

const onSetAside = vi.fn()
const onAlike = vi.fn()

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

test("a card carrying more than the three fields still opens as a file", async () => {
  fetchCard.mockResolvedValue({
    task: "chores",
    text: "name: Chores\nfolder: ../work\nprompt: tidy\nevery: 15m\n",
    name: "Chores",
    folder: "../work",
    prompt: "tidy",
    plain: false,
  })
  await open()

  expect(container.querySelector(".card-text")).not.toBeNull()
  expect(container.querySelector(".card-field-prompt")).toBeNull()
})
