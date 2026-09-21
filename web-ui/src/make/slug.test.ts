import { expect, test } from "vitest"

import { slugOf, titleOf } from "./slug"

test("a blank name is taken from the first line of the prompt, cut short", () => {
  // The first sentence when it comes soon enough; the first words otherwise;
  // and never the second line, which is where instructions get long.
  expect(titleOf("Run the tests. Fix one failure.")).toBe("Run the tests")
  expect(titleOf("매일 밤 테스트를 돌리고 실패하는 걸 하나만 고쳐줘")).toBe("매일 밤 테스트를 돌리고 실패하는 걸 하나만 고쳐줘")
  expect(titleOf("\n\n  Tidy the docs!\nThen stop.")).toBe("Tidy the docs")
  expect(
    titleOf("Look through every open issue in the tracker and pick the one that has waited longest without an answer"),
  ).toBe("Look through every open issue in the tracker and pick the")
  expect(titleOf("   ")).toBe("")
})

test("a title becomes the filename the daemon would give it", () => {
  // Mirrors the server's _slug, case for case: the point of warning early is
  // agreeing with the refusal that would come late.
  expect(slugOf("tidy up")).toBe("tidy-up")
  expect(slugOf("  Tidy   Up  ")).toBe("tidy-up")
  expect(slugOf("release_notes")).toBe("release_notes")
  expect(slugOf("v2.0 sweep")).toBe("v2-0-sweep")
})

test("a title in any script keeps its letters, as the daemon's does", () => {
  // The server slugs with unicode \w on purpose, so a Korean or Cyrillic
  // title can be a card at all. An ASCII-only mirror here would warn about
  // collisions that cannot happen and miss the ones that can.
  expect(slugOf("정리")).toBe("정리")
  expect(slugOf("уборка дома")).toBe("уборка-дома")
})

test("dependent marks fall exactly where the daemon drops them", () => {
  // The riskiest ground for a mirror: scripts whose vowels are combining
  // marks. Python's unicode word class drops Mc/Mn marks -- verified against
  // the server's regex directly -- and so must this, or Hindi and NFD titles
  // would warn about collisions the daemon does not see. If these ever fail,
  // the server moved and this mirror has to move with it.
  expect(slugOf("ते")).toBe("त") // ते -> त
  expect(slugOf("भारत")).toBe("भ-रत") // भारत
  expect(slugOf("café")).toBe("cafe") // NFD e + combining acute
  expect(slugOf("ไทย")).toBe("ไทย") // ไทย survives whole
})

test("a title with nothing usable slugs to nothing", () => {
  expect(slugOf("  ")).toBe("")
  expect(slugOf("!!!")).toBe("")
})
