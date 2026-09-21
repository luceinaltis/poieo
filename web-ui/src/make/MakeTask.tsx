/**
 * Writing a task, from the board.
 *
 * A name, the folder it works in, and a prompt remain the ordinary form.
 * "Write as steps" grows that prompt into connected instructions and
 * conditions, saved as the same graph the runtime reads from a file. Above
 * the fields, the work can be said in one's own words instead: the project's
 * model answers, and the card it proposes fills the same three fields for
 * the person to check -- nothing is saved that the person did not press.
 *
 * **Two presses, though, and no third field.** Saving a card starts a
 * shell-capable agent over the reader's own files within seconds -- that is
 * DESIGN.md's board and it stays the default -- but until the daemon could
 * switch a card on without being restarted there was no way to write one down
 * and look at it first except by going and finding the file. The quiet press
 * is second and plainer for the same reason the warning below it exists: the
 * consequence belongs to the loud one.
 *
 * **The folder is required and has no default.** It is the one thing the
 * model's hands will touch, so a guess there would fill in the single moment
 * principle 7 keeps out of the machinery it otherwise hides. A draft from the
 * conversation may put a folder in the field, but only one inside the project
 * and only when the person's own words named it, and the field stays theirs
 * to change. That is also why the sentence above the button names the folder
 * rather than describing it: the card starts running when it is saved, and
 * this is where a person finds that out.
 *
 * Shell UI, so it may read the API. It hangs off the rail beside `models`
 * because making a task is what the page is for, not something one task does.
 */

import { useState } from "react"

import { createTask } from "../api"
import { ApplySettings, applicationOf, applicationReady, draftOf } from "../ApplySettings"
import type { MadeTask, TaskDraft } from "../api"
import { FolderPick } from "../FolderPick"
import { Refusal } from "../Refusal"
import { slugOf } from "./slug"
import { useAct } from "../useAct"
import { Describe } from "./Describe"
import { StepEditor } from "./StepEditor"
import { graphOf, newStep, stepProblems } from "./steps"
import type { StepDraft } from "./steps"
import "./make.css"

export function MakeTask({
  project,
  keepsCopies,
  onClose,
  onMade,
  seed,
  taken = [],
}: {
  project: string
  /**
   * Whether a night made here could be thrown away in the morning.
   *
   * A property of the project, not of the folder being typed: a card made
   * here works inside the project, and a folder inside a work tree is in that
   * work tree. So it is answered before there is a path to answer about.
   */
  keepsCopies: boolean
  onClose(): void
  /**
   * A card was written, under the name the daemon filed it under. The shell
   * opens it the moment the board has it; until then the panel stays and
   * says what it made.
   */
  onMade?(task: string): void
  /**
   * "Make one like it": the fields of an existing card, to start from.
   *
   * A starting point and nothing more -- the panel is keyed on it, so a
   * fresh seed is a fresh form, and everything stays editable.
   */
  seed?: { name: string; folder: string; prompt: string }
  /**
   * The filenames this project's tasks already answer to.
   *
   * The daemon would refuse a collision with a 409 after save; the board
   * already holds the list, so the sentence comes while the name is still
   * being typed. Advisory only -- the daemon's refusal stays the authority.
   */
  taken?: string[]
}) {
  const [name, setName] = useState(seed?.name ?? "")
  const [folder, setFolder] = useState(seed?.folder ?? "")
  const [prompt, setPrompt] = useState(seed?.prompt ?? "")
  const [steps, setSteps] = useState<StepDraft[] | null>(null)
  /** One line, or nothing: the card then takes its hourly default. */
  const [schedule, setSchedule] = useState("")
  const [application, setApplication] = useState(draftOf())
  const [made, setMade] = useState<string | null>(null)
  // Which of the two presses made it, so the confirmation says which happened.
  // The whole reason the second button exists is that "it starts on its own"
  // is a sentence with consequences, and it must not be said of a card that
  // did not.
  const [started, setStarted] = useState(true)
  // Whether the fields were last filled from the conversation above them,
  // so the form can say so -- and say what still has to be looked at.
  const [filled, setFilled] = useState(false)
  const { busy, refused, act } = useAct<MadeTask>(() => {})

  // A card the model proposed, onto the fields. The folder is taken only
  // when the draft names one, and the field keeps what the person typed
  // otherwise; the prompt lands in the first step once the form has become
  // steps, since that step is where the prompt went when it did.
  const fill = (draft: TaskDraft) => {
    setName(draft.name)
    if (draft.folder) setFolder(draft.folder)
    setSchedule(draft.schedule)
    setSteps((current) =>
      current ? current.map((step, index) => (index === 0 ? { ...step, text: draft.prompt } : step)) : current,
    )
    if (!steps) setPrompt(draft.prompt)
    setFilled(true)
  }

  // In the daemon's own spelling of the filename, so "Chores!" collides with
  // "chores" exactly as it would on disk.
  const collides = taken.includes(slugOf(name))
  const problems = steps ? stepProblems(steps) : []
  const ready = Boolean(name.trim() && folder.trim() && (steps ? steps.length && !problems.length : prompt.trim())) && !collides && applicationReady(application)

  const send = (enabled: boolean) => () =>
    void act(async () => {
      const configured = JSON.stringify(application) !== JSON.stringify(draftOf())
      const args = [project, name.trim(), folder.trim(), steps ? graphOf(name.trim(), steps) : prompt.trim(), enabled] as const
      // Only what was said: a blank schedule is not sent, so a card made
      // without one reads exactly as it did before there was a field.
      const when = schedule.trim()
      const answer = when
        ? await createTask(...args, configured ? applicationOf(application) : undefined, when)
        : configured
          ? await createTask(...args, applicationOf(application))
          : await createTask(...args)
      // `ok` alone is not enough: a 2xx whose body did not parse arrives as
      // {ok: true} with no task, and treating that as made would clear the
      // form over a card that may not exist -- and a second press would
      // either duplicate it or be refused.
      if (answer.ok && !answer.task) {
        return { ok: false, error: "the daemon answered, but not with a task" }
      }
      if (answer.ok && answer.task) {
        setMade(answer.task)
        // Cleared rather than closed. Closing was the first shape and it made
        // the confirmation unreachable -- the panel unmounted in the same
        // batch that set it, so a save gave no sign at all. The shell takes
        // over from here: the daemon looks at the folder as soon as the card
        // is written and says "ask again", and the card opens in its drawer
        // the moment the listing carries it. Until then this line stands.
        onMade?.(answer.task)
        setName("")
        setFolder("")
        setPrompt("")
        setSchedule("")
        setSteps(null)
        setApplication(draftOf())
        setFilled(false)
        setStarted(enabled)
      }
      return answer
    })

  return (
    <aside className="panel make" aria-label="New task">
      <header className="make-head">
        <h2 className="make-title">New task</h2>
        <button type="button" className="make-close" onClick={onClose}>
          close
        </button>
      </header>

      {/* Above the fields, not beside the save: what it produces is a filled
          form, and the form is still what gets saved. */}
      <Describe project={project} disabled={busy} onDraft={fill} />
      {filled ? (
        <p className="make-note">Filled in from the conversation. Check the folder, then save.</p>
      ) : null}

      <label className="make-field">
        name
        <input
          name="name"
          className="make-input"
          value={name}
          disabled={busy}
          onChange={(event) => setName(event.target.value)}
        />
      </label>

      {collides ? (
        <Refusal>this project already has a task called ‘{slugOf(name)}’</Refusal>
      ) : null}

      <label className="make-field">
        folder
        <input
          name="folder"
          className="make-input"
          placeholder="../a-folder"
          value={folder}
          disabled={busy}
          onChange={(event) => setFolder(event.target.value)}
        />
        {/* The choice, spelled out. `..` for the project itself was the one
            thing a reader could not guess, and the field still fills in
            nothing on its own. */}
        <FolderPick project={project} value={folder} disabled={busy} onPick={setFolder} />
      </label>

      {steps ? <StepEditor steps={steps} onChange={setSteps} disabled={busy} /> : <>
      <label className="make-field">
        prompt
        <textarea
          name="prompt"
          className="make-prompt"
          rows={6}
          value={prompt}
          disabled={busy}
          onChange={(event) => setPrompt(event.target.value)}
        />
      </label>
      <button type="button" className="step-start" disabled={busy}
        onClick={() => setSteps([newStep([], "agent", prompt)])}>Write as steps</button>
      </>}

      {/* The short form's schedule, as one line: an interval, the word loop,
          or a cron line. Left blank the card says nothing and runs hourly,
          which is what every card made here did before there was a field.
          Jitter, a start rule or a run limit are still the file's. */}
      <label className="make-field">
        every
        <input
          name="schedule"
          className="make-input"
          placeholder="1h unless said — 30m, loop, or a cron line like 0 2 * * *"
          value={schedule}
          disabled={busy}
          onChange={(event) => setSchedule(event.target.value)}
        />
      </label>

      {problems.length > 0 && <ul className="step-problems" aria-label="Steps to fix">
        {problems.map(problem => <li key={problem}>{problem}</li>)}
      </ul>}

      <ApplySettings value={application} onChange={setApplication} disabled={busy} keepsCopies={keepsCopies} />

      {/* The one thing this panel says out loud. Everything else about a run
          is machinery and stays hidden; this is not, because it is the reader's
          own files.

          Two sentences, and the second is the one that was missing. Whose
          files change was already here; what becomes of the changes was not,
          and it is the half a reader cannot find out afterwards without
          having already started the task. The board carries the same fact on
          the card, but a card exists because somebody pressed this button. */}
      {folder.trim() ? (
        <p className="make-warning">
          Saving and starting runs this task. It will read and change files in{" "}
          <code>{folder.trim()}</code>
          {folder.trim().startsWith("/") || /^[A-Za-z]:/.test(folder.trim()) ? null : (
            // A relative folder is read from the project's tasks folder, not
            // from the project root -- so the sentence that names whose files
            // change has to say which `work` it means.
            <>, read from this project’s tasks folder</>
          )}
          .{" "}
          {application.mode === "auto" ? (
            <>The selected folder needs Git. Its work is kept in a private copy, checked,
              then applied within your allowed files.</>
          ) : keepsCopies ? (
            // Said even though it is the good news: without it the other
            // wording reads as boilerplate about files rather than as the one
            // project where the morning cannot help.
            <>Its work is kept in a private copy for you to accept or throw away.</>
          ) : (
            <strong className="make-undo">
              This project is not a git repository, so there is no copy — it changes your files
              directly, and there is no undo.
            </strong>
          )}
        </p>
      ) : (
        <p className="make-note">
          A task works in one folder, and there is no default for it.
        </p>
      )}

      {refused ? <Refusal answer={refused} /> : null}

      {made ? (
        <p className="make-made">
          Made “{made}”.{" "}
          {started
            ? "It starts on its own."
            : "It is switched off — switch it on in its Task setup when it is ready."}
        </p>
      ) : null}

      {/* Two presses, and the quiet one is second and plainer. Saving a card
          starts a shell-capable agent over the reader's own files within
          seconds, which is DESIGN.md's board and stays the default; what was
          missing was any way to write one down and look at it first without
          going and finding the file. */}
      <div className="make-actions">
        <button
          type="button"
          className="make-save"
          data-do="make-task"
          disabled={!ready || busy}
          onClick={send(true)}
        >
          {busy ? "saving…" : "save and start"}
        </button>
        <button
          type="button"
          className="make-later"
          data-do="make-task-off"
          disabled={!ready || busy}
          onClick={send(false)}
        >
          save without starting
        </button>
      </div>
    </aside>
  )
}
