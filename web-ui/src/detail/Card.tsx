/**
 * The card behind a task, loaded only when opened and rewritable in place.
 *
 * Plain cards keep the form used to create them. Richer YAML stays as text so
 * comments and fields the form cannot represent survive. Renaming moves the
 * identity file without rewriting its contents.
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
  const [isOpen, setIsOpen] = useState(false)
  const [originalText, setOriginalText] = useState<string | null>(null)
  const [cardFields, setCardFields] = useState<CardFields | null>(null)
  /** The form's three values, alive only for a plain card. */
  const [name, setName] = useState("")
  const [folder, setFolder] = useState("")
  const [prompt, setPrompt] = useState("")
  const [text, setText] = useState("")
  const [isMissing, setIsMissing] = useState(false)
  const [saveResult, setSaveResult] = useState<RewrittenCard | null>(null)
  const [hasRequestedCard, setHasRequestedCard] = useState(false)
  /** Two-step: the first press arms, the second acts, an edit stands it down. */
  const [isSetAsideArmed, setIsSetAsideArmed] = useState(false)
  const [setAsideResult, setSetAsideResult] = useState<SetAside | null>(null)
  /** The filename the task would have. Starts as the one it has. */
  const [newTaskName, setNewTaskName] = useState(task)
  const [renameResult, setRenameResult] = useState<RenamedCard | null>(null)
  const { busy, refused, act } = useAct<RewrittenCard>(() => {})

  const loadCard = async () => {
    if (hasRequestedCard) return
    setHasRequestedCard(true)
    const card = await fetchCard(project, task)
    if (card === null) {
      setIsMissing(true)
      return
    }
    setOriginalText(card.text)
    setText(card.text)
    setCardFields(card)
    setName(card.name)
    setFolder(card.folder ?? "")
    setPrompt(card.prompt ?? "")
  }

  const setCardAside = () =>
    void act(async () => {
      const answer = (await setAside(project, task)) as RewrittenCard & SetAside
      setIsSetAsideArmed(false)
      if (answer.ok) {
        setSetAsideResult(answer)
        onSetAside?.()
      }
      return answer
    })

  const renameTaskCard = () =>
    void act(async () => {
      const answer = (await renameCard(project, task, newTaskName)) as RewrittenCard &
        RenamedCard
      setIsSetAsideArmed(false)
      if (answer.ok) {
        setSaveResult(null)
        setRenameResult(answer)
      }
      return answer
    })

  /** The file this fold is editing is no longer where it was. */
  const isCardMoved = setAsideResult !== null || renameResult !== null
  const isPlainCard = cardFields?.plain === true
  // Same rule both modes: nothing changed, nothing to save.
  const isUnchanged = isPlainCard
    ? name === cardFields.name &&
      folder === (cardFields.folder ?? "") &&
      prompt === (cardFields.prompt ?? "")
    : text === originalText

  const saveCard = () =>
    void act(async () => {
      const answer = await rewriteCard(
        project,
        task,
        isPlainCard ? { name, folder, prompt } : text,
      )
      if (answer.ok) {
        if (isPlainCard && cardFields) {
          setCardFields({ ...cardFields, name, folder, prompt })
        } else {
          setOriginalText(text)
        }
        setSaveResult(answer)
      } else {
        setSaveResult(null)
      }
      return answer
    })

  return (
    <details className="drawer-card" onToggle={(event) => setIsOpen(event.currentTarget.open)}>
      <summary
        className="card-open"
        aria-expanded={isOpen}
        onClick={() => void loadCard()}
      >
        Task setup
      </summary>

      {isMissing ? (
        <Refusal>The card could not be read. It may have moved on disk.</Refusal>
      ) : originalText === null ? null : (
        <>
          {isPlainCard ? (
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
                    setSaveResult(null)
                    setIsSetAsideArmed(false)
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
                    setSaveResult(null)
                    setIsSetAsideArmed(false)
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
                    setSaveResult(null)
                    // Reaching for the words is deciding to keep the task.
                    setIsSetAsideArmed(false)
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
                setSaveResult(null)
                // Reaching for the words is deciding to keep the task.
                setIsSetAsideArmed(false)
              }}
            />
          )}

          {refused ? <Refusal answer={refused} /> : null}

          {saveResult ? (
            saveResult.live ? (
              <p className="card-saved">Saved. The next run reads this.</p>
            ) : (
              <p className="card-saved card-waits">
                Saved — but this changed more than the prompt, and the rest only
                takes effect when the daemon restarts.
              </p>
            )
          ) : null}

          {setAsideResult ? (
            <p className="card-saved card-waits">
              Set aside — the file is kept at <code>{setAsideResult.kept}</code>. The
              schedule has stopped; the task leaves the board when the daemon
              restarts, and putting the file back is putting the task back.
            </p>
          ) : null}

          {renameResult ? (
            <p className="card-saved card-waits">
              Renamed — the card is now <code>{renameResult.task}</code>. The schedule
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
                value={newTaskName}
                disabled={busy || isCardMoved}
                onChange={(event) => {
                  setNewTaskName(event.target.value)
                  // Reaching for a new name is deciding to keep the task.
                  setIsSetAsideArmed(false)
                }}
              />
            </label>
            <button
              type="button"
              className="card-rename-do"
              data-do="rename"
              disabled={
                busy || isCardMoved || newTaskName.trim() === "" || newTaskName === task
              }
              onClick={renameTaskCard}
            >
              rename
            </button>
          </div>

          <div className="card-acts">
            <button
              type="button"
              className="card-save"
              data-do="save-card"
              disabled={busy || isUnchanged || isCardMoved}
              onClick={saveCard}
            >
              {busy ? "saving…" : "save"}
            </button>

            {onAlike && cardFields ? (
              <button
                type="button"
                className="card-alike"
                data-do="make-alike"
                disabled={busy}
                onClick={() =>
                  onAlike({
                    name: cardFields.name,
                    folder: cardFields.folder ?? "",
                    prompt: cardFields.prompt ?? "",
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
              data-armed={String(isSetAsideArmed)}
              disabled={busy || isCardMoved}
              onClick={() =>
                isSetAsideArmed ? setCardAside() : setIsSetAsideArmed(true)
              }
            >
              {isSetAsideArmed ? "sure? set it aside" : "set aside"}
            </button>
          </div>
        </>
      )}
    </details>
  )
}
