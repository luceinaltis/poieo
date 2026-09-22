/**
 * When a task runs, as a person would say it.
 *
 * A card takes one line for it -- an interval such as `30m`, the word `loop`,
 * or a cron line such as `0 2 * * *` -- and the form offers the usual ones
 * as plain words, each carrying the line the card would take. Blank is the
 * card's own default, hourly. The last choice opens the line itself.
 *
 * The card the conversation proposes says its schedule in the same words,
 * so "every night at 2" on the form is never "at 0 2 * * *" three inches
 * above it. A line the list does not have is said as the card spells it.
 */

export const WHEN: { value: string; label: string }[] = [
  { value: "", label: "every hour" },
  { value: "30m", label: "every 30 minutes" },
  { value: "24h", label: "every day" },
  { value: "0 2 * * *", label: "every night at 2" },
  { value: "custom", label: "at another time…" },
]

/** A schedule line in the form's words when it has them, else as the card spells it. */
export function saidOf(schedule: string): string {
  const choice = WHEN.find((one) => one.value === schedule && one.value !== "custom")
  if (choice) return choice.label
  if (schedule === "loop") return "loop"
  return schedule.split(" ").length === 5 ? `at ${schedule}` : `every ${schedule}`
}
