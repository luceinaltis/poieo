import type { MemoryOverview } from "./types"

/**
 * The learner's next question, put against the window it will face.
 *
 * The daemon sizes the question in characters; the window is in tokens. The
 * conversion comes from the last pass that counted both, because the ratio
 * belongs to the model in use, and falls back to the usual four characters a
 * token before any pass has run. Either way the token figure is an estimate
 * and says so. With no window there is no ratio, and the size stands alone.
 */
export const ASSUMED_CHARS_PER_TOKEN = 4

export interface LearnerLoad {
  chars: number
  entries: number
  model: string | null
  context: number | null
  /** Estimated tokens of the next question; null when there is no window to compare against. */
  tokens: number | null
  /** Whether the conversion came from a pass that counted, not the assumption. */
  measured: boolean
}

export function learnerLoad(overview: MemoryOverview): LearnerLoad | null {
  const learner = overview.learner
  if (!learner) return null
  const counted = (overview.learning ?? []).find(
    (pass) => (pass.prompt_chars ?? 0) > 0 && (pass.prompt_tokens ?? 0) > 0,
  )
  const perToken = counted ? counted.prompt_chars! / counted.prompt_tokens! : ASSUMED_CHARS_PER_TOKEN
  return {
    chars: learner.prompt_chars,
    entries: learner.entries,
    model: learner.model,
    context: learner.context,
    tokens: learner.context === null ? null : Math.round(learner.prompt_chars / perToken),
    measured: Boolean(counted),
  }
}
