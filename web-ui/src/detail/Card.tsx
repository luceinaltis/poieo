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
 * `live` is the daemon's own answer about the edit, and it is repeated here
 * word for word: a prompt change is read by the next run, anything more waits
 * for a restart. Saying nothing was the alternative, and it teaches a person
 * that edits silently do not take.
 */

import { useState } from "react"

import { fetchCard, rewriteCard, setAside } from "../api"
import type { Card as CardFields, RewrittenCard, SetAside } from "../api"
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
  const [text, setText] = useState("")
  const [gone, setGone] = useState(false)
  const [saved, setSaved] = useState<RewrittenCard | null>(null)
  const [opened, setOpened] = useState(false)
  /** Two-step: the first press arms, the second acts, an edit stands it down. */
  const [armed, setArmed] = useState(false)
  const [rested, setRested] = useState<SetAside | null>(null)
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

  const save = () =>
    void act(async () => {
      const answer = await rewriteCard(project, task, text)
      if (answer.ok) {
        setWas(text)
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

          <div className="card-acts">
            <button
              type="button"
              className="card-save"
              data-do="save-card"
              disabled={busy || text === was || rested !== null}
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
              disabled={busy || rested !== null}
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
