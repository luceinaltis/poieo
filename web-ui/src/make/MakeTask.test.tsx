/**
 * The form that writes a card.
 *
 * One question first, then a name and a prompt, which is DESIGN.md's second
 * principle as it now reads: the common case is small, and a task works in
 * the whole project unless it is narrowed under `more`. What the form still
 * defends is the moment before saving, which says plainly whose files are
 * about to change and whether that can be undone. That sentence is principle
 * 7's one exception to hiding the machinery, and it is the whole reason a
 * card may be created already running -- and the whole reason it may also be
 * created not running, which is the second press.
 */

import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const createTask = vi.hoisted(() => vi.fn<typeof import("../api").createTask>())
const fetchFolders = vi.hoisted(() => vi.fn<typeof import("../api").fetchFolders>())
const draftTask = vi.hoisted(() => vi.fn<typeof import("../api").draftTask>())
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  createTask,
  fetchFolders,
  draftTask,
}))

import { MakeTask } from "./MakeTask"

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  createTask.mockReset()
  createTask.mockResolvedValue({ ok: true, task: "tidy-up" })
  fetchFolders.mockReset()
  fetchFolders.mockResolvedValue([])
  draftTask.mockReset()
  host = document.createElement("div")
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

function show(props: Partial<Parameters<typeof MakeTask>[0]> = {}) {
  act(() => {
    root.render(
      <MakeTask
        project="board"
        keepsCopies={props.keepsCopies ?? true}
        onClose={props.onClose ?? (() => {})}
        onMade={props.onMade}
      />,
    )
  })
}

const field = (name: string) => host.querySelector<HTMLInputElement>(`[name="${name}"]`)!
const save = () => host.querySelector<HTMLButtonElement>('[data-do="make-task"]')!

function pick(name: string, value: string) {
  const select = host.querySelector<HTMLSelectElement>(`select[name="${name}"]`)!
  act(() => {
    select.value = value
    select.dispatchEvent(new Event("change", { bubbles: true }))
  })
}

function type(name: string, value: string) {
  const input = field(name)
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(
      input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
      "value",
    )!.set!
    setter.call(input, value)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

test("it is one of the panels on the right edge, not a third geometry", () => {
  show()
  // Three panels share that edge and only one is ever open, so their width,
  // padding and box model have to agree. They were copied instead, and the
  // copies drifted -- one of them learned to count its own padding and the
  // other two did not, which chopped their contents on a narrow window.
  expect(host.querySelector("aside")?.classList.contains("panel")).toBe(true)
})

test("it asks for a prompt and a name, and the rest is chosen rather than typed", async () => {
  // Two fields to fill and nothing else to type: where it works and when it
  // runs are picked from lists that start on the defaults, so a card made
  // without touching them reads exactly as one made before there were lists.
  show()
  await act(async () => {})
  const named = [...host.querySelectorAll("[name]")].map((node) => node.getAttribute("name"))
  expect(named.sort()).toEqual(["folder-pick", "name", "prompt", "when"])
  expect(field("when").value).toBe("")
  expect(field("folder-pick").value).toBe("..")
})

test("how changes reach the project is not asked here", () => {
  // A new task starts under review. Letting it apply its own checked work is
  // a decision for a task that has run a few times, and Task setup is where
  // that is switched on -- so the panel neither asks nor sends it.
  show()
  expect(host.querySelector(".apply-settings")).toBeNull()
  type("prompt", "keep it healthy")
  act(() => save().click())
  expect(createTask).toHaveBeenCalledWith("board", "keep it healthy", "..", "keep it healthy", true)
})

test("a name left blank is taken from the first line of the prompt", async () => {
  show()
  type("prompt", "Run the tests. Fix one failure.\nLeave the rest alone.")
  // Shown before it is used: the placeholder is the name the card will get.
  expect(field("name").placeholder).toBe("Run the tests")
  expect(save().disabled).toBe(false)
  await act(async () => {
    save().click()
  })
  expect(createTask).toHaveBeenCalledWith("board", "Run the tests", "..", "Run the tests. Fix one failure.\nLeave the rest alone.", true)
})

test("a name taken from the prompt collides like a typed one", () => {
  act(() => {
    root.render(<MakeTask project="board" keepsCopies={true} onClose={() => {}} taken={["tidy-up"]} />)
  })
  type("prompt", "Tidy up! Then stop.")
  expect(host.textContent).toContain("already has a task called ‘tidy-up’")
  expect(save().disabled).toBe(true)
})

test("the folder starts on the whole project and can be narrowed from the list", async () => {
  // A card made here may only work inside this project, so the whole project
  // is the most a task can have, and the field starts there: `..`, which the
  // list spells as "this project". Narrowing is the choice, not naming.
  fetchFolders.mockResolvedValue([
    { path: "..", name: "this project" },
    { path: "../work", name: "work" },
  ])
  show()
  await act(async () => {})

  expect(field("folder-pick").value).toBe("..")
  expect(host.textContent).toContain("files in this project")

  pick("folder-pick", "../work")
  expect(field("folder-pick").value).toBe("../work")
  expect(host.textContent).toContain("../work")

  pick("folder-pick", "..")
  expect(host.textContent).toContain("files in this project")
})

test("the fields wait behind the question until a draft comes or the person asks for them", () => {
  // One question first. The fields are put away rather than absent, so a
  // draft lands on fields that already exist.
  show()
  const fields = () => host.querySelector<HTMLElement>(".make-fields")!
  expect(fields().hidden).toBe(true)
  expect(host.querySelector('[data-do="make-task"]')).not.toBeNull()

  // Pressed from the keyboard, the link goes away under the focus. The
  // prompt is where the person is now, so that is where focus lands.
  const link = host.querySelector<HTMLButtonElement>('[data-do="write-by-hand"]')!
  act(() => link.focus())
  act(() => link.click())
  expect(fields().hidden).toBe(false)
  expect(host.querySelector('[data-do="write-by-hand"]')).toBeNull()
  expect(document.activeElement).toBe(field("prompt"))
})

test("a seed is a card already, so the panel opens on the fields", () => {
  act(() => {
    root.render(
      <MakeTask
        project="board"
        keepsCopies={true}
        onClose={() => {}}
        seed={{ name: "Chores", folder: "../work", prompt: "tidy" }}
      />,
    )
  })
  expect(host.querySelector<HTMLElement>(".make-fields")!.hidden).toBe(false)
  // The seed's folder, shown even though the daemon offered no list: the
  // list is the field here, and a field cannot hide what it holds.
  expect(field("folder-pick").value).toBe("../work")
  expect(host.textContent).toContain("../work")
})

test("with nothing to offer, the task still works in the whole project", async () => {
  show()
  await act(async () => {})
  expect(field("folder-pick").value).toBe("..")
  expect(host.querySelector('select[name="folder-pick"] option')?.textContent).toBe("this project")
})

test("when it runs is chosen, and a blank choice is not sent", async () => {
  // A person says "every night", not "0 2 * * *". The choices carry the
  // card's own line; the last one opens that line for anything else. Blank
  // means the card says nothing and takes its default, exactly as before.
  show()
  type("name", "nightly")
  type("prompt", "look around")
  expect(host.querySelector('input[name="schedule"]')).toBeNull()
  pick("when", "0 2 * * *")

  await act(async () => {
    save().click()
  })
  expect(createTask).toHaveBeenCalledWith("board", "nightly", "..", "look around", true, undefined, "0 2 * * *")
  expect(field("when").value).toBe("")

  type("name", "often")
  type("prompt", "look again")
  pick("when", "custom")
  type("schedule", "15m")
  await act(async () => {
    save().click()
  })
  expect(createTask).toHaveBeenLastCalledWith("board", "often", "..", "look again", true, undefined, "15m")
})

test("a name and a prompt are the whole card, and it works in the whole project unless narrowed", async () => {
  show()
  type("name", "tidy up")
  expect(save().disabled).toBe(true)
  type("prompt", "look around")
  expect(save().disabled).toBe(false)

  await act(async () => {
    save().click()
  })
  expect(createTask).toHaveBeenCalledWith("board", "tidy up", "..", "look around", true)
})

test("it says whose files are about to change before the button is pressed", async () => {
  fetchFolders.mockResolvedValue([
    { path: "..", name: "this project" },
    { path: "../work", name: "work" },
  ])
  show()
  await act(async () => {})
  // Principle 7's one exception: the machinery stays hidden, the moment the
  // reader's own files are about to change does not -- and it is said before
  // anything is typed, because the whole project is what a fresh card gets.
  expect(host.textContent).toContain("files in this project")
  pick("folder-pick", "../work")
  expect(host.textContent).toContain("../work")
  expect(host.textContent?.toLowerCase()).toContain("files")
})

test("it says the work can be thrown away, where that is true", () => {
  show({ keepsCopies: true })

  // The reassuring half, and it is not decoration: it is what makes the
  // other half legible as the exception it is.
  expect(host.textContent).toContain("private copy")
  expect(host.textContent).not.toContain("no undo")
})

test("it says there is nothing to undo, before the button that starts it", () => {
  show({ keepsCopies: false })

  // The board says this too, on the card -- but by then the task exists and
  // has been running. This is the moment the reader chooses, and until now
  // the only place to find out was afterwards.
  expect(host.textContent).toContain("no undo")
  expect(host.textContent).toContain("not a git repository")
  expect(host.textContent).not.toContain("private copy")
})

test("a saved card is sent as the three things, and says so in place", async () => {
  show()
  type("name", "tidy up")
  type("prompt", "look around")

  await act(async () => {
    save().click()
  })

  expect(createTask).toHaveBeenCalledWith("board", "tidy up", "..", "look around", true)
  // Said here, not by closing. Closing was the first shape, and it unmounted
  // the panel in the same batch that set the confirmation -- so a save gave
  // no sign at all that anything had happened.
  expect(host.textContent).toContain("tidy-up")
  // And cleared, because the next card is a different card.
  expect(field("prompt").value).toBe("")
})

test("a made card is handed up by the name the daemon filed it under", async () => {
  // So the shell can open it the moment the board has it. The daemon's
  // spelling, not the typed one: that is the key the stage files it under.
  const onMade = vi.fn()
  show({ onMade })
  type("name", "tidy up")
  type("prompt", "look around")

  await act(async () => {
    save().click()
  })

  expect(onMade).toHaveBeenCalledWith("tidy-up")
})

test("a refusal is shown and the form keeps what was typed", async () => {
  createTask.mockResolvedValue({ ok: false, error: "the folder it would work in is not there" })
  show()
  type("name", "tidy up")
  type("prompt", "look around")

  await act(async () => {
    save().click()
  })

  expect(host.textContent).toContain("is not there")
  // Retyping three fields to fix one of them is the refusal happening twice.
  expect(field("prompt").value).toBe("look around")
})


test("a refusal with nothing to say still says something", async () => {
  // `ok: false` and no sentence is a shape the API produces: `post` builds its
  // answer from `response.ok` spread with a body that may have failed to parse
  // to `{}`. Four of the five writing surfaces fall back to a sentence; this
  // one showed a disabled button, a form that would not clear, and no reason.
  createTask.mockResolvedValue({ ok: false })
  show()
  type("name", "tidy up")
  type("prompt", "look around")

  await act(async () => {
    save().click()
  })

  expect(host.textContent).toContain("didn't work")
})

test("an answer with no task is a refusal, not a card", async () => {
  // A 2xx whose body did not parse arrives as {ok: true} and nothing else.
  // Taken as made it would clear the form over a card that may not exist, and
  // the next press would either duplicate it or be refused.
  createTask.mockResolvedValue({ ok: true })
  show()
  type("name", "tidy up")
  type("prompt", "look around")

  await act(async () => {
    save().click()
  })

  expect(host.textContent).toContain("not with a task")
  expect(field("prompt").value).toBe("look around")
})

test("a relative folder says which folder it is relative to", async () => {
  // The server reads it from the project's tasks folder, not the project
  // root. The sentence naming whose files change has to say which `work`.
  // Such a folder reaches this panel by seed, from a card written by hand.
  const seeded = (folder: string) =>
    act(() => {
      root.render(
        <MakeTask project="board" keepsCopies={true} onClose={() => {}} seed={{ name: "x", folder, prompt: "y" }} />,
      )
    })
  seeded("work")
  expect(host.textContent).toContain("tasks folder")

  act(() => root.unmount())
  root = createRoot(host)
  seeded("/tmp/elsewhere")
  expect(host.textContent).not.toContain("tasks folder")
})

test("the quiet press writes a card that does not start", async () => {
  // Saving a card starts a shell-capable agent over the reader's own files
  // within seconds. That stays the default; what was missing was any way to
  // write one down and look at it first without going and finding the file.
  show()
  type("name", "later")
  type("prompt", "go")

  await act(async () => {
    host.querySelector<HTMLElement>('[data-do="make-task-off"]')!.click()
  })

  expect(createTask).toHaveBeenCalledWith("board", "later", "..", "go", false)
  // And the confirmation says which of the two happened: "it starts on its
  // own" is a sentence with consequences, and must not be said of a card that
  // did not.
  expect(host.textContent).toContain("switched off")
  expect(host.textContent).not.toContain("starts on its own")
})

async function describe(text: string) {
  const box = host.querySelector<HTMLTextAreaElement>('textarea[aria-label="Describe the work"]')!
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(box, text)
    box.dispatchEvent(new Event("input", { bubbles: true }))
  })
  await act(async () => host.querySelector<HTMLButtonElement>('[data-do="describe"]')!.click())
}

test("a card the conversation proposed brings the fields out filled, and a folder it did not name stays as it was", async () => {
  // The fields are what get saved, so a draft lands on them rather than
  // beside them -- and a draft that did not name a folder does not touch the
  // one the person had, whether that is the whole project or a narrowing.
  draftTask.mockResolvedValue({
    ok: true,
    reply: "Here is a card.",
    draft: { name: "nightly", folder: "", prompt: "Run the tests.", schedule: "0 2 * * *" },
    model: "fake/m1",
  })
  fetchFolders.mockResolvedValue([
    { path: "..", name: "this project" },
    { path: "../work", name: "work" },
    { path: "../docs", name: "docs" },
  ])
  show()
  await act(async () => {})
  expect(host.querySelector<HTMLElement>(".make-fields")!.hidden).toBe(true)
  pick("folder-pick", "../work")
  await describe("run the tests every night")
  await act(async () => host.querySelector<HTMLButtonElement>('[data-do="use-draft"]')!.click())

  expect(host.querySelector<HTMLElement>(".make-fields")!.hidden).toBe(false)
  expect(field("name").value).toBe("nightly")
  expect(field("prompt").value).toBe("Run the tests.")
  // A schedule the choices have is chosen; the line stays closed.
  expect(field("when").value).toBe("0 2 * * *")
  expect(host.querySelector('input[name="schedule"]')).toBeNull()
  expect(field("folder-pick").value).toBe("../work")
  expect(host.textContent).toContain("Filled in from the conversation")
  expect(save().disabled).toBe(false)

  // A draft that names a folder the project has fills that too, and a
  // schedule the choices lack opens the line with it written out.
  draftTask.mockResolvedValue({
    ok: true,
    reply: "Or this.",
    draft: { name: "docs", folder: "../docs", prompt: "Tidy the docs.", schedule: "2h" },
    model: "fake/m1",
  })
  await describe("in docs instead")
  const offered = host.querySelectorAll<HTMLButtonElement>('[data-do="use-draft"]')
  await act(async () => offered[offered.length - 1].click())
  expect(field("folder-pick").value).toBe("../docs")
  expect(field("when").value).toBe("custom")
  expect(field("schedule").value).toBe("2h")
})

test("a draft naming a folder the list lacks shows it as one more choice", async () => {
  // The daemon offered nothing here, and the draft still names a folder
  // inside the project: the list is the field, so it shows what it holds.
  draftTask.mockResolvedValue({
    ok: true,
    reply: "Here.",
    draft: { name: "nightly", folder: "../work", prompt: "Run the tests.", schedule: "" },
    model: "fake/m1",
  })
  show()
  await describe("run the tests")
  await act(async () => host.querySelector<HTMLButtonElement>('[data-do="use-draft"]')!.click())

  expect(field("folder-pick").value).toBe("../work")
  expect(host.textContent).toContain("../work")
  expect(field("name").value).toBe("nightly")
})
