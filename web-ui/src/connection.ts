/**
 * When one task starts the next, as a person would say it.
 *
 * A card's `then:` holds a condition in the expression language; the board
 * offers the four a person asks for and writes each as the expression the
 * daemon reads. The task panel's connections and a chain the conversation
 * proposed share these words, so a condition reads the same in both places.
 * A condition written by hand is said by its label, or as written.
 */

import type { Connection } from "./api"

export const CONDITIONS = [
  { value: "always", label: "whenever it finishes" },
  { value: "succeeded", label: "if it succeeded" },
  { value: "failed", label: "if it failed" },
  { value: "says", label: "if its answer says…" },
] as const

export type Condition = (typeof CONDITIONS)[number]["value"]

/** A word as a condition can quote it: lower case, and nothing that ends the quote. */
export const wordOf = (text: string) => text.trim().toLowerCase().replace(/['\\]/g, "")

/** The condition and the word the board draws on the wire, as the card spells them. */
export function written(when: Condition, word: string): Pick<Connection, "when" | "label"> {
  if (when === "succeeded") return { when: "run.status == 'completed'", label: "succeeded" }
  if (when === "failed") return { when: "run.status == 'failed'", label: "failed" }
  if (when === "says") return { when: `'${wordOf(word)}' in str(run.outputs).lower()`, label: wordOf(word) }
  return { when: "true", label: null }
}

/** A condition in words, from the choice and its word. */
export function saidWhen(when: Condition, word: string): string {
  if (when === "says") return `if its answer says “${wordOf(word)}”`
  return CONDITIONS.find((choice) => choice.value === when)!.label
}

/** A connection's condition in words: one the board wrote, or the word it was given. */
export function said(arrow: Connection): string {
  if (arrow.when === "true") return saidWhen("always", "")
  if (arrow.when === "run.status == 'completed'") return saidWhen("succeeded", "")
  if (arrow.when === "run.status == 'failed'") return saidWhen("failed", "")
  const word = /^'(.*)' in str\(run\.outputs\)\.lower\(\)$/.exec(arrow.when)
  if (word) return saidWhen("says", word[1])
  return arrow.label ? `when “${arrow.label}”` : `when ${arrow.when}`
}

/**
 * The word a wire carries on the board. The listing sends a connection's
 * label, or its condition when it has none -- and the board's own conditions
 * are said here in the same words as the task panel, not as the expression.
 */
export function wireWord(label: string, when?: string): string {
  // A label that is not the condition repeated is one somebody chose -- a
  // word an answer must contain may well be "true" -- and is said as written.
  if (when !== undefined && label !== when) return label
  if (label === "true") return "always"
  if (label === "run.status == 'completed'") return "succeeded"
  if (label === "run.status == 'failed'") return "failed"
  const word = /^'(.*)' in str\(run\.outputs\)\.lower\(\)$/.exec(label)
  return word ? word[1] : label
}
