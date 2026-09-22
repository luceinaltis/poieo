/**
 * A schedule, said. The form and the conversation's proposal card share
 * these words, so the same line reads the same in both places.
 */

import { expect, test } from "vitest"

import { WHEN, saidOf } from "./schedule"

test("a line the form offers is said in the form's words", () => {
  expect(saidOf("")).toBe("every hour")
  expect(saidOf("30m")).toBe("every 30 minutes")
  expect(saidOf("24h")).toBe("every day")
  expect(saidOf("0 2 * * *")).toBe("every night at 2")
  expect(saidOf("manual")).toBe("only when another task starts it")
})

test("any other line is said as the card spells it", () => {
  expect(saidOf("2h")).toBe("every 2h")
  expect(saidOf("loop")).toBe("loop")
  expect(saidOf("*/5 * * * *")).toBe("at */5 * * * *")
})

test("the choices end on the one that opens the line", () => {
  expect(WHEN[0]).toEqual({ value: "", label: "every hour" })
  expect(WHEN[WHEN.length - 1].value).toBe("custom")
})
