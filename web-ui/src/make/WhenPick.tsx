/**
 * When a task runs, chosen in a person's words -- the one control for it.
 *
 * The choices carry the card's own line; the last opens that line for
 * anything else. A line the choices do not have opens on it, so a card
 * written by hand with `every: 15m` shows 15m rather than a wrong choice.
 * The new-task panel and a task's setup both use this, so a schedule looks
 * the same where it is made and where it is changed.
 */

import { useState } from "react"

import { WHEN } from "./schedule"

export function WhenPick({
  value,
  disabled = false,
  onChange,
}: {
  /** The card's line: "" for the default, a choice's value, or anything a card takes. */
  value: string
  disabled?: boolean
  onChange(line: string): void
}) {
  // "Another time" opens the line the task has, written out, and changes
  // nothing until it is edited -- so opening it is never a silent reset.
  const [writing, setWriting] = useState(false)
  const offered = WHEN.some((choice) => choice.value === value && choice.value !== "custom")
  const custom = writing || !offered

  return (
    <>
      <select
        name="when"
        className="make-input"
        value={custom ? "custom" : value}
        disabled={disabled}
        onChange={(event) => {
          const picked = event.target.value
          setWriting(picked === "custom")
          if (picked !== "custom") onChange(picked)
        }}
      >
        {WHEN.map((choice) => (
          <option key={choice.value} value={choice.value}>
            {choice.label}
          </option>
        ))}
      </select>
      {custom ? (
        <input
          name="schedule"
          className="make-input"
          aria-label="When, as the card spells it"
          placeholder="30m, loop, manual, or a cron line like 0 2 * * *"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : null}
    </>
  )
}
