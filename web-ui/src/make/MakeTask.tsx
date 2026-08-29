/**
 * Writing a task, from the board.
 *
 * Three fields and no fourth: a name, the folder it works in, and its prompt.
 * That is DESIGN.md's second principle, and everything else -- which model,
 * how often, where output lands -- stays on a default until somebody opens the
 * file to change it.
 *
 * **The folder is required and never filled in.** It is the one thing the
 * model's hands will touch, so a default there would fill in the single moment
 * principle 7 keeps out of the machinery it otherwise hides. That is also why
 * the sentence above the button names the folder rather than describing it:
 * the card starts running when it is saved, and this is where a person finds
 * that out.
 *
 * Shell UI, so it may read the API. It hangs off the rail beside `models`
 * because making a task is what the page is for, not something one task does.
 */

import { useState } from "react"

import { createTask } from "../api"
import type { MadeTask } from "../api"
import { useAct } from "../useAct"
import "./make.css"

export function MakeTask({
  project,
  onClose,
  onMade,
}: {
  project: string
  onClose(): void
  onMade(task: string): void
}) {
  const [name, setName] = useState("")
  const [folder, setFolder] = useState("")
  const [prompt, setPrompt] = useState("")
  const [made, setMade] = useState<string | null>(null)
  const { busy, refused, act } = useAct<MadeTask>(() => {})

  const ready = Boolean(name.trim() && folder.trim() && prompt.trim())

  const send = () =>
    void act(async () => {
      const answer = await createTask(project, name.trim(), folder.trim(), prompt.trim())
      if (answer.ok && answer.task) {
        setMade(answer.task)
        onMade(answer.task)
      }
      return answer
    })

  return (
    <aside className="make" aria-label="New task">
      <header className="make-head">
        <h2 className="make-title">New task</h2>
        <button type="button" className="make-close" onClick={onClose}>
          close
        </button>
      </header>

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
      </label>

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

      {/* The one thing this panel says out loud. Everything else about a run
          is machinery and stays hidden; this is not, because it is the reader's
          own files. */}
      {folder.trim() ? (
        <p className="make-warning">
          Saving starts this task. It will read and change files in{" "}
          <code>{folder.trim()}</code>.
        </p>
      ) : (
        <p className="make-note">
          A task works in one folder, and there is no default for it.
        </p>
      )}

      {refused?.error ? (
        <p className="make-refusal" role="alert">
          {refused.error}
        </p>
      ) : null}

      {made ? <p className="make-made">Made “{made}”. It starts on its own.</p> : null}

      <button
        type="button"
        className="make-save"
        data-do="make-task"
        disabled={!ready || busy}
        onClick={send}
      >
        {busy ? "saving…" : "save"}
      </button>
    </aside>
  )
}
