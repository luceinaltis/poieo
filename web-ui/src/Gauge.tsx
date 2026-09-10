import "./gauge.css"

/**
 * One ratio against a limit, drawn the same way everywhere it appears: a
 * label, a thin track, and the numbers beside it. The fill's colour carries
 * how close to the limit the value is, and a word says the same thing, so the
 * state is never colour alone. Without a limit there is no ratio to draw and
 * the value stands on its own -- an unknown limit is not a limit of zero.
 */

export type GaugeLevel = "ok" | "near" | "over" | "unbounded"

export const NEAR_SHARE = 0.8

export function gaugeLevel(used: number, limit: number | null): GaugeLevel {
  if (limit === null || limit <= 0) return "unbounded"
  const share = used / limit
  if (share >= 1) return "over"
  if (share >= NEAR_SHARE) return "near"
  return "ok"
}

/** 1,284 stays exact; 12,900 reads as 12.9k; 1,200,000 as 1.2M. */
export function compact(value: number): string {
  if (value >= 1_000_000) return `${trim((value / 1_000_000).toFixed(1))}M`
  if (value >= 10_000) return `${trim((value / 1_000).toFixed(1))}k`
  return value.toLocaleString("en-US")
}

function trim(fixed: string): string {
  return fixed.replace(/\.0$/, "")
}

const WORD: Record<GaugeLevel, string | null> = {
  ok: null,
  near: "near the limit",
  over: "over the limit",
  unbounded: null,
}

export function Gauge({
  label,
  used,
  limit,
  unit,
  estimate = false,
  title,
}: {
  label: string
  used: number
  limit: number | null
  unit: string
  /** The value is derived rather than counted; it is marked so a reader knows. */
  estimate?: boolean
  title?: string
}) {
  const level = gaugeLevel(used, limit)
  const value = `${estimate ? "≈" : ""}${compact(used)}${limit !== null && limit > 0 ? ` / ${compact(limit)}` : ""} ${unit}`
  const word = WORD[level]
  const said = `${label}: ${estimate ? "about " : ""}${compact(used)}${limit !== null && limit > 0 ? ` of ${compact(limit)}` : ""} ${unit}${word ? `, ${word}` : ""}`
  return (
    <span className="gauge" data-gauge={label} data-level={level} role="img" aria-label={said} title={title ?? said}>
      <span className="gauge-label">{label}</span>
      {level === "unbounded" ? null : (
        <span className="gauge-track">
          <span className="gauge-fill" style={{ width: `${Math.min(100, Math.round((used / (limit as number)) * 100))}%` }} />
        </span>
      )}
      <span className="gauge-value">{value}</span>
      {word ? <span className="gauge-word">{word}</span> : null}
    </span>
  )
}
