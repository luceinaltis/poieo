/**
 * Writing a task, from the board.
 *
 * The panel opens on one question: what should it do. The project's model
 * answers in kind and, when it can, proposes a card; "use this draft" puts
 * that card on the fields below, which are also there for anyone who would
 * rather write it themselves. A prompt is the whole of the ordinary card: a
 * name left blank is taken from its first line. Where it works and when it
 * runs are chosen from lists that start on the defaults, under `more`.
 *
 * **Two presses, though, and no third field.** Saving a card starts a
 * shell-capable agent over the reader's own files within seconds -- that is
 * DESIGN.md's board and it stays the default -- but until the daemon could
 * switch a card on without being restarted there was no way to write one down
 * and look at it first except by going and finding the file. The quiet press
 * is second and plainer for the same reason the warning below it exists: the
 * consequence belongs to the loud one.
 *
 * **The folder is the project, unless narrowed.** A card made here may only
 * work inside the project the board is showing -- the daemon refuses anything
 * else -- so the whole project is the most a task can have, and the one
 * question left is whether to give it less. That is a choice for the few
 * tasks that need it and lives under `more`. What every task keeps is the
 * sentence above the button: it names the place the model's hands will touch
 * and says whether that can be undone, because the card starts running when
 * it is saved, and this is where a person finds that out.
 *
 * **What is not asked here.** How changes reach the project: a new task
 * starts under review, and letting it apply its own checked work is a
 * decision for a task that has run a few times, made in Task setup. And
 * steps: a task of several steps and conditions is drawn in the standalone
 * editor until the board hosts that canvas, because a form of drop-downs for
 * a flow was the heaviest thing on this panel and the one a first reader
 * could least make sense of.
 *
 * Shell UI, so it may read the API. It hangs off the board's own line under
 * the bar, because making a task is what the page is for, not something one
 * task does.
 */

import { useLayoutEffect, useRef, useState } from "react"

import { createTask } from "../api"
import type { MadeTask, TaskDraft } from "../api"
import { FolderPick } from "../FolderPick"
import { Refusal } from "../Refusal"
import { WHEN } from "./schedule"
import { slugOf, titleOf } from "./slug"
import { useAct } from "../useAct"
import { written } from "../connection"
import { Describe, startsWhen } from "./Describe"
import "./make.css"

/** How a card spells the project itself: relative to the tasks folder. */
const WHOLE_PROJECT = ".."

export function MakeTask({
  project,
  keepsCopies,
  onClose,
  onMade,
  onModels,
  seed,
  taken = [],
}: {
  project: string
  /**
   * Whether a night made here could be thrown away in the morning.
   *
   * A property of the project, not of the folder being chosen: a card made
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
  /** The models panel, for a conversation the project has no model for. */
  onModels?(opener: HTMLElement): void
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
  const [folder, setFolder] = useState(seed?.folder ?? WHOLE_PROJECT)
  const [prompt, setPrompt] = useState(seed?.prompt ?? "")
  // Which of the choices above, or "custom" with the line written out.
  const [when, setWhen] = useState("")
  const [schedule, setSchedule] = useState("")
  const [made, setMade] = useState<string | null>(null)
  // Which of the two presses made it, so the confirmation says which happened.
  // The whole reason the second button exists is that "it starts on its own"
  // is a sentence with consequences, and it must not be said of a card that
  // did not.
  const [started, setStarted] = useState(true)
  // Whether the fields are out. They wait behind the one question until a
  // draft arrives to fill them or the person asks to write the card
  // themselves; a seed is a card already, so it opens on them.
  const [open, setOpen] = useState(Boolean(seed))
  // Whether the fields were last filled from the conversation above them,
  // so the form can say so.
  const [filled, setFilled] = useState(false)
  const { busy, refused, act } = useAct<MadeTask>(() => {})

  // Where the page goes when the fields come out on a press, and again each
  // time a draft lands on them: the fields into view, then focus on the
  // prompt. The press was "use this draft" at the bottom of a thread that
  // keeps its height, and what it filled was below the fold -- the name, the
  // sentence naming whose files change, the save -- so the person went
  // looking for what the press had done. The link that brings the fields out
  // by hand leaves the page in the same update, and a focused element
  // removed from under a keyboard drops focus to the page itself; the prompt
  // is where the person is now. Not on mount: a seeded panel is focused as
  // a whole by the shell, like every other panel.
  const fieldsRef = useRef<HTMLDivElement>(null)
  const promptRef = useRef<HTMLTextAreaElement>(null)
  const [revealed, setRevealed] = useState(0)
  const bringOut = () => {
    setOpen(true)
    setRevealed((times) => times + 1)
  }
  useLayoutEffect(() => {
    if (!revealed) return
    // The least movement that shows the whole of them: the thread above
    // scrolls away only as far as it must.
    fieldsRef.current?.scrollIntoView({ block: "nearest" })
    promptRef.current?.focus({ preventScroll: true })
  }, [revealed])

  // Several connected cards the model proposed, read over here rather than
  // on the fields: the fields are one card, and a chain is made together.
  const [chain, setChain] = useState<TaskDraft[] | null>(null)
  const [chainMade, setChainMade] = useState<{ names: string[]; started: boolean } | null>(null)
  const chainAct = useAct<MadeTask>(() => {})

  // Last card first, each written already connected to the one it starts:
  // the first task can then never finish a run before its followers exist.
  // The quiet press leaves only the first switched off -- a follower that is
  // off drops the handoff, and the first card is the one switch to throw.
  const makeChain = (enabled: boolean) => () =>
    void chainAct.act(async () => {
      if (!chain) return { ok: false }
      const slugs: string[] = []
      for (let at = chain.length - 1; at >= 0; at -= 1) {
        const draft = chain[at]
        const then = chain.flatMap((later, index) =>
          later.after && later.after.task === at
            ? [{ ...written(later.after.when, later.after.word), to: slugs[index] }]
            : [],
        )
        const answer = await createTask(
          project,
          draft.name,
          draft.folder || WHOLE_PROJECT,
          draft.prompt,
          at === 0 ? enabled : true,
          undefined,
          draft.schedule || undefined,
          then,
        )
        if (!answer.ok || !answer.task) {
          const done = slugs.filter(Boolean)
          const error = answer.error || "the daemon answered, but not with a task"
          return {
            ok: false,
            error: done.length ? `${error} — ${done.join(", ")} ${done.length > 1 ? "were" : "was"} made` : error,
          }
        }
        slugs[at] = answer.task
      }
      setChainMade({ names: slugs, started: enabled })
      setChain(null)
      onMade?.(slugs[0])
      return { ok: true, task: slugs[0] }
    })

  // A card the model proposed, onto the fields. The folder is taken only
  // when the draft names one, and the list keeps what the person had
  // otherwise. A schedule the choices do not have opens the line with it
  // written out.
  const fill = (draft: TaskDraft) => {
    setName(draft.name)
    if (draft.folder) setFolder(draft.folder)
    if (WHEN.some((choice) => choice.value === draft.schedule && choice.value !== "custom")) {
      setWhen(draft.schedule)
    } else {
      setWhen("custom")
      setSchedule(draft.schedule)
    }
    setPrompt(draft.prompt)
    setFilled(true)
    bringOut()
  }

  // The name the card will get: the one typed, or the first line of what it
  // does. In the daemon's own spelling of the filename for the collision, so
  // "Chores!" collides with "chores" exactly as it would on disk.
  const title = name.trim() || titleOf(prompt)
  const collides = Boolean(title) && taken.includes(slugOf(title))
  // Emptied, the list means the whole project again, not nowhere.
  const where = folder.trim() || WHOLE_PROJECT
  const line = when === "custom" ? schedule.trim() : when
  const ready = Boolean(title && prompt.trim()) && !collides

  const send = (enabled: boolean) => () =>
    void act(async () => {
      const args = [project, title, where, prompt.trim(), enabled] as const
      // Only what was said: a blank schedule is not sent, so a card made
      // without one reads exactly as it did before there was a choice.
      const answer = line ? await createTask(...args, undefined, line) : await createTask(...args)
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
        setFolder(WHOLE_PROJECT)
        setPrompt("")
        setWhen("")
        setSchedule("")
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

      {/* The one question, first and alone: what it produces is a filled
          form, and the form is still what gets saved. */}
      <Describe
        project={project}
        disabled={busy || chainAct.busy}
        onDraft={(draft) => {
          setChain(null)
          fill(draft)
        }}
        onChain={(drafts) => {
          setOpen(false)
          setChainMade(null)
          setChain(drafts)
        }}
        onModels={onModels}
      />

      {/* A chain, read over whole: which card runs when, and the same
          sentence every save says about whose files change -- every card
          here works inside this project. */}
      {chain ? (
        <section className="make-chain" aria-label="Connected tasks to make">
          <ol className="make-chain-list">
            {chain.map((draft, at) => (
              <li key={at}>
                <strong>{draft.name}</strong> <span className="make-chain-when">{startsWhen(chain, draft)}</span>
                <p className="make-chain-prompt">{draft.prompt}</p>
              </li>
            ))}
          </ol>
          <p className="make-note">Each connection starts a new run of the next task, with its own change to review.</p>
          <p className="make-warning">
            Saving and starting runs the first of these tasks. They will read and change files in this project.{" "}
            {keepsCopies ? (
              <>Their work is kept in private copies for you to accept or throw away.</>
            ) : (
              <strong className="make-undo">
                This project is not a git repository, so there is no copy — they change your files directly, and there
                is no undo.
              </strong>
            )}
          </p>
          {chainAct.refused ? <Refusal answer={chainAct.refused} /> : null}
          <div className="make-actions">
            <button type="button" className="make-save" data-do="make-chain" disabled={chainAct.busy} onClick={makeChain(true)}>
              {chainAct.busy ? "saving…" : "save and start"}
            </button>
            <button
              type="button"
              className="make-later"
              data-do="make-chain-off"
              disabled={chainAct.busy}
              onClick={makeChain(false)}
            >
              save without starting
            </button>
          </div>
        </section>
      ) : null}
      {chainMade ? (
        <p className="make-made">
          Made {chainMade.names.length} tasks, each connected to the next.{" "}
          {chainMade.started
            ? "The first starts on its own."
            : "The first is switched off — switch it on in its Task setup when it is ready."}
        </p>
      ) : null}

      {!open && !chain ? (
        <button type="button" className="make-byhand" data-do="write-by-hand" onClick={bringOut}>
          or write it yourself
        </button>
      ) : null}

      {/* Hidden rather than absent while they wait: a draft lands on fields
          that already exist, and nothing is lost by putting them away. */}
      <div className="make-fields" hidden={!open} ref={fieldsRef}>
        {filled ? <p className="make-note">Filled in from the conversation. Read it over, then save.</p> : null}

        <label className="make-field">
          prompt
          <textarea
            ref={promptRef}
            name="prompt"
            className="make-prompt"
            rows={6}
            placeholder="what to do, how to check it, and what to leave alone"
            value={prompt}
            disabled={busy}
            onChange={(event) => setPrompt(event.target.value)}
          />
        </label>

        {/* After the prompt, because it comes from the prompt: left blank,
            the placeholder shows the name the card will get. */}
        <label className="make-field">
          name
          <input
            name="name"
            className="make-input"
            placeholder={title || "from the first line of the prompt"}
            value={name}
            disabled={busy}
            onChange={(event) => setName(event.target.value)}
          />
        </label>

        {collides ? (
          <Refusal>this project already has a task called ‘{slugOf(title)}’</Refusal>
        ) : null}

        {/* What an ordinary card takes from defaults, folded, so the fields
            above are the whole card for most people: here for the few tasks
            that need less of the project or another rhythm. */}
        <details className="make-more">
          <summary>more · where it works, when</summary>
          <div className="make-more-body">
            <label className="make-field">
              works in
              {/* The choice, spelled out, standing on the whole project until
                  it is narrowed: `..` for the project itself was the one
                  thing a reader could not guess. */}
              <FolderPick project={project} value={where} disabled={busy} alone onPick={setFolder} />
            </label>

            {/* When it runs, as a person says it. The last choice opens the
                card's own line: an interval, the word loop, or a cron line.
                Jitter, a start rule or a run limit are still the file's. */}
            <label className="make-field">
              when
              <select
                name="when"
                className="make-input"
                value={when}
                disabled={busy}
                onChange={(event) => setWhen(event.target.value)}
              >
                {WHEN.map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {choice.label}
                  </option>
                ))}
              </select>
              {when === "custom" ? (
                <input
                  name="schedule"
                  className="make-input"
                  aria-label="When, as the card spells it"
                  placeholder="30m, loop, or a cron line like 0 2 * * *"
                  value={schedule}
                  disabled={busy}
                  onChange={(event) => setSchedule(event.target.value)}
                />
              ) : null}
            </label>
          </div>
        </details>

        {/* The one thing this panel says out loud. Everything else about a run
            is machinery and stays hidden; this is not, because it is the reader's
            own files.

            Two sentences, and the second is the one that was missing. Whose
            files change was already here; what becomes of the changes was not,
            and it is the half a reader cannot find out afterwards without
            having already started the task. The board carries the same fact on
            the card, but a card exists because somebody pressed this button. */}
        <p className="make-warning">
          Saving and starting runs this task. It will read and change files in{" "}
          {where === WHOLE_PROJECT ? (
            <>this project</>
          ) : (
            <>
              <code>{where}</code>
              {where.startsWith("/") || /^[A-Za-z]:/.test(where) ? null : (
                // A relative folder is read from the project's tasks folder,
                // not from the project root -- so the sentence that names
                // whose files change has to say which `work` it means.
                <>, read from this project’s tasks folder</>
              )}
            </>
          )}
          .{" "}
          {keepsCopies ? (
            // Said even though it is the good news: without it the other
            // wording reads as boilerplate about files rather than as the one
            // project where the morning cannot help.
            <>Its work is kept in a private copy for you to accept or throw away.</>
          ) : (
            <strong className="make-undo">
              This project is not a git repository, so there is no copy — it changes your files directly, and there is
              no undo.
            </strong>
          )}
        </p>

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
      </div>
    </aside>
  )
}
