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

import { fetchCard, rewriteCard } from "../api"
import type { RewrittenCard } from "../api"
import { useAct } from "../useAct"

export function Card({ project, task }: { project: string; task: string }) {
  const [was, setWas] = useState<string | null>(null)
  const [text, setText] = useState("")
  const [gone, setGone] = useState(false)
  const [saved, setSaved] = useState<RewrittenCard | null>(null)
  const [opened, setOpened] = useState(false)
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
  }

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
        <p className="card-refusal">The card could not be read. It may have moved on disk.</p>
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
            }}
          />

          {refused?.error ? (
            <p className="card-refusal" role="alert">
              {refused.error}
            </p>
          ) : null}

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

          <button
            type="button"
            className="card-save"
            data-do="save-card"
            disabled={busy || text === was}
            onClick={save}
          >
            {busy ? "saving…" : "save"}
          </button>
        </>
      )}
    </details>
  )
}
