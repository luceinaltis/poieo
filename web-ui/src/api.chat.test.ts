/**
 * The chat call reads the answer as it is written.
 *
 * The daemon answers the chat route as a stream of frames when asked for
 * one: each piece of thinking and text as it arrives, then the whole reply,
 * or an error frame once the stream has begun. The page hears the pieces
 * and keeps the whole, and a daemon that answers whole -- an older one, or
 * any refusal -- comes back the same way, so the panel has one path.
 */

import { afterEach, expect, test, vi } from "vitest"

import { chat } from "./api"

function streamingFetch(frames: string[], contentType = "text/event-stream") {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) controller.enqueue(new TextEncoder().encode(frame))
      controller.close()
    },
  })
  const fetchStub = vi.fn(async (_path: string, _init?: RequestInit) => ({
    ok: true,
    status: 200,
    headers: { get: (name: string) => (name === "content-type" ? contentType : null) },
    body,
    json: async () => ({ ok: true, reply: "whole" }),
  }))
  vi.stubGlobal("fetch", fetchStub)
  return fetchStub
}

afterEach(() => {
  vi.unstubAllGlobals()
})

test("chat asks for the answer as it is written, hears each piece, and keeps the whole", async () => {
  // Frames may be split across chunks, and one chunk may hold several.
  const fetchStub = streamingFetch([
    'data: {"type":"thinking","text":"hm"}\n\n',
    'data: {"type":"text","text":"Fo"}\n\ndata: {"type":"te',
    'xt","text":"ur."}\n\n',
    'data: {"type":"done","reply":"Four.","thinking":"hm","model":"fake/m1","usage":null,"cut_short":false}\n\n',
  ])
  const pieces: unknown[] = []

  const answer = await chat("board", [{ role: "user", content: "2 + 2?" }], (piece) => pieces.push(piece))

  expect(pieces).toEqual([{ thinking: "hm" }, { text: "Fo" }, { text: "ur." }])
  expect(answer).toEqual({
    ok: true,
    reply: "Four.",
    thinking: "hm",
    model: "fake/m1",
    usage: null,
    cut_short: false,
  })
  const init = fetchStub.mock.calls[0][1] as RequestInit
  expect(init.headers).toMatchObject({ accept: "text/event-stream" })
})

test("a stream that ends in an error frame is a refusal", async () => {
  streamingFetch([
    'data: {"type":"text","text":"Fo"}\n\n',
    'data: {"type":"error","error":"the model did not answer"}\n\n',
  ])

  expect(await chat("board", [{ role: "user", content: "x" }])).toEqual({
    ok: false,
    error: "the model did not answer",
  })
})

test("a daemon that answers whole rather than as a stream is the whole", async () => {
  streamingFetch([], "application/json")

  expect(await chat("board", [{ role: "user", content: "x" }])).toEqual({ ok: true, reply: "whole" })
})
