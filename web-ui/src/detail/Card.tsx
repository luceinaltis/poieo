/**
 * The card behind a task, opened for rewriting.
 *
 * The loop this exists for is the one a person actually runs: watch a night,
 * sharpen the prompt, watch the next. Until now the middle step meant leaving
 * the board to find a file on disk -- for a task whose card the board itself
 * may have written.
 *
 * The editor holds the file, not a form: the card is the user's own YAML,
 * comments and all, and a form would re-serialise it into something they did
 * not write. Shut it costs nothing -- no fetch until somebody opens it -- and
 * open it is deliberately plain: one textarea, one save.
 *
 * Renaming is the one control here that does not edit the card: the filename
 * is the task's identity, so it moves the file and leaves the body byte for
 * byte. It is a name that goes over, not a filename -- the daemon spells it,
 * and refuses one that reads like a path or one the folder already uses.
 *
 * `live` is the daemon's own answer about the edit, and it is repeated here
 * word for word: a prompt change is read by the next run, anything more waits
 * for a restart. Saying nothing was the alternative, and it teaches a person
 * that edits silently do not take.
 */

import { useState } from "react"

import { fetchCard, renameCard, rewriteCard, setAside } from "../api"
import type { Card as CardFields, RenamedCard, RewrittenCard, SetAside } from "../api"
import { Refusal } from "../Refusal"
import { useAct } from "../useAct"

export function Card({
  project,
  task,
  onSetAside,
  onAlike,
}: {
  project: string
  task: string
  /** The board's chance to refresh: the task it lists just stopped scheduling. */
  onSetAside?(): void
  /** "Make one like it": the three fields, parsed, for the make panel to open on. */
  onAlike?(seed: { name: string; folder: string; prompt: string }): void
}) {
  const [was, setWas] = useState<string | null>(null)
  const [fields, setFields] = useState<CardFields | null>(null)
  /** The form's three values, alive only for a plain card. */
  const [name, setName] = useState("")
  const [folder, setFolder] = useState("")
  const [prompt, setPrompt] = useState("")
  const [text, setText] = useState("")
  const [gone, setGone] = useState(false)
  const [saved, setSaved] = useState<RewrittenCard | null>(null)
  const [opened, setOpened] = useState(false)
  /** Two-step: the first press arms, the second acts, an edit stands it down. */
  const [armed, setArmed] = useState(false)
  const [rested, setRested] = useState<SetAside | null>(null)
  /** The filename the task would have. Starts as the one it has. */
  const [renameTo, setRenameTo] = useState(task)
  const [renamed, setRenamed] = useState<RenamedCard | null>(null)
  const { busy, refused, act } = useAct<RewrittenCard>(() => {})

  const open = async () => {
    if (opened) return
    setOpened(true)
    const card = await fetchCard(project, task)
    if (card === null) {
      setGone(true)
      return
    }
    setWas(card.text)
    setText(card.text)
    setFields(card)
    setName(card.name)
    setFolder(card.folder ?? "")
    setPrompt(card.prompt ?? "")
  }

  const putAside = () =>
    void act(async () => {
      const answer = (await setAside(project, task)) as RewrittenCard & SetAside
      setArmed(false)
      if (answer.ok) {
        setRested(answer)
        onSetAside?.()
      }
      return answer
    })

  const rename = () =>
    void act(async () => {
      const answer = (await renameCard(project, task, renameTo)) as RewrittenCard &
        RenamedCard
      setArmed(false)
      if (answer.ok) {
        setSaved(null)
        setRenamed(answer)
      }
      return answer
    })

  /** The file this fold is editing is no longer where it was. */
  const moved = rested !== null || renamed !== null
  const plain = fields?.plain === true
  // Same rule both modes: nothing changed, nothing to save.
  const untouched = plain
    ? name === fields.name && folder === (fields.folder ?? "") && prompt === (fields.prompt ?? "")
    : text === was

  const save = () =>
    void act(async () => {
      const answer = await rewriteCard(project, task, plain ? { name, folder, prompt } : text)
      if (answer.ok) {
        if (plain && fields) setFields({ ...fields, name, folder, prompt })
        else setWas(text)
        setSaved(answer)
      } else {
        setSaved(null)
      }
      return answer
    })

  return (
    <details className="drawer-card">
      <summary className="card-open" onClick={() => void open()}>
        card
      </summary>

      {gone ? (
        <Refusal>The card could not be read. It may have moved on disk.</Refusal>
      ) : was === null ? null : (
        <>
          {plain ? (
            /* The person filled a form to make this card; handing them YAML
               to edit it would be giving the form and then taking it away.
               Values only -- the daemon owns the spelling, through the same
               dump make uses. A card carrying more than the three fields
               falls through to the file below, because a form must never
               drop what it cannot show. */
            <div className="card-form">
              <label className="card-field">
                name
                <input
                  className="card-field-name"
                  value={name}
                  disabled={busy}
                  onChange={(event) => {
                    setName(event.target.value)
                    setSaved(null)
                    setArmed(false)
                  }}
                />
              </label>
              <label className="card-field">
                folder
                <input
                  className="card-field-folder"
                  value={folder}
                  disabled={busy}
                  onChange={(event) => {
                    setFolder(event.target.value)
                    setSaved(null)
                    setArmed(false)
                  }}
                />
              </label>
              <label className="card-field">
                prompt
                <textarea
                  className="card-field-prompt"
                  rows={Math.min(12, Math.max(4, prompt.split("\n").length + 1))}
                  value={prompt}
                  disabled={busy}
                  onChange={(event) => {
                    setPrompt(event.target.value)
                    setSaved(null)
                    // Reaching for the words is deciding to keep the task.
                    setArmed(false)
                  }}
                />
              </label>
            </div>
          ) : (
            <textarea
              className="card-text"
              rows={Math.min(16, Math.max(6, text.split("\n").length + 1))}
              value={text}
              disabled={busy}
              spellCheck={false}
              onChange={(event) => {
                setText(event.target.value)
                setSaved(null)
                // Reaching for the words is deciding to keep the task.
                setArmed(false)
              }}
            />
          )}

          {refused ? <Refusal answer={refused} /> : null}

          {saved ? (
            saved.live ? (
              <p className="card-saved">Saved. The next run reads this.</p>
            ) : (
              <p className="card-saved card-waits">
                Saved — but this changed more than the prompt, and the rest only
                takes effect when the daemon restarts.
              </p>
            )
          ) : null}

          {rested ? (
            <p className="card-saved card-waits">
              Set aside — the file is kept at <code>{rested.kept}</code>. The
              schedule has stopped; the task leaves the board when the daemon
              restarts, and putting the file back is putting the task back.
            </p>
          ) : null}

          {renamed ? (
            <p className="card-saved card-waits">
              Renamed — the card is now <code>{renamed.task}</code>. The schedule
              has stopped under the old name; this fold still points at the file
              that moved, so go on from the new task, which the daemon picks up
              on its own.
            </p>
          ) : null}

          {/* The filename is the task's identity, so this moves the file and
              edits nothing in it -- the `name:` field above is the card's own
              title and stays whatever it says. A name, not a filename: the
              daemon spells it, and refuses one that reads like a path. */}
          <div className="card-rename">
            <label className="card-field">
              rename to
              <input
                className="card-rename-to"
                value={renameTo}
                disabled={busy || moved}
                onChange={(event) => {
                  setRenameTo(event.target.value)
                  // Reaching for a new name is deciding to keep the task.
                  setArmed(false)
                }}
              />
            </label>
            <button
              type="button"
              className="card-rename-do"
              data-do="rename"
              disabled={busy || moved || renameTo.trim() === "" || renameTo === task}
              onClick={rename}
            >
              rename
            </button>
          </div>

          <div className="card-acts">
            <button
              type="button"
              className="card-save"
              data-do="save-card"
              disabled={busy || untouched || moved}
              onClick={save}
            >
              {busy ? "saving…" : "save"}
            </button>

            {onAlike && fields ? (
              <button
                type="button"
                className="card-alike"
                data-do="make-alike"
                disabled={busy}
                onClick={() =>
                  onAlike({
                    name: fields.name,
                    folder: fields.folder ?? "",
                    prompt: fields.prompt ?? "",
                  })
                }
              >
                make one like it
              </button>
            ) : null}

            {/* Two presses on purpose: the first only changes this button's
                word, so nothing destructive rides on a stray click. An edit
                in the textarea stands it down again. */}
            <button
              type="button"
              className="card-aside"
              data-do="set-aside"
              data-armed={String(armed)}
              disabled={busy || moved}
              onClick={() => (armed ? putAside() : setArmed(true))}
            >
              {armed ? "sure? set it aside" : "set aside"}
            </button>
          </div>
        </>
      )}
    </details>
  )
}
