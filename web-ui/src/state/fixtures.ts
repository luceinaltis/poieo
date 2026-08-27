/**
 * Real bytes, not hand-written ones.
 *
 * Captured by running `poieo daemon` against examples/bindings/mock.yaml and
 * copying the JSONL the store wrote. Keeping them verbatim is the point: if
 * the backend ever changes an event's shape, these stop matching and the
 * reducer's tests say so.
 *
 * The `run_summary` frames are assembled the way BroadcastStore publishes
 * them -- flat, with the summary's fields beside `type` and no `at` -- because
 * summaries go to index.jsonl and never appear in a run's own JSONL.
 *
 * The only edit made to the captured bytes: the agent node's workdir, which
 * was an absolute path on the capturing machine.
 */

import type { PoieoEvent } from "../types"

/** An agent node: turns, tool calls, and captured thinking. */
export const AGENT_RUN: PoieoEvent[] = [
  {
    "run_id": "20260822T072819-98a6708d",
    "type": "run_started",
    "at": "2026-08-22T07:28:19.836+00:00",
    "data": {
      "graph": "agent-task",
      "flow": "chores",
      "trigger": "loop",
      "iteration": 1,
      "binding": "mock",
      "input": {
        "workdir": "/scratch/fx-work"
      }
    }
  },
  {
    "run_id": "20260822T072819-98a6708d",
    "type": "node_started",
    "at": "2026-08-22T07:28:19.836+00:00",
    "node_id": "work",
    "data": {
      "type": "agent",
      "step": 1
    }
  },
  {
    "run_id": "20260822T072819-98a6708d",
    "type": "node_turn",
    "at": "2026-08-22T07:28:19.837+00:00",
    "node_id": "work",
    "data": {
      "turn": 1,
      "text": "",
      "thinking": "First see what is in this directory.",
      "tool_call_count": 1
    }
  },
  {
    "run_id": "20260822T072819-98a6708d",
    "type": "node_tool_call",
    "at": "2026-08-22T07:28:19.838+00:00",
    "node_id": "work",
    "data": {
      "turn": 1,
      "name": "list_dir",
      "arguments": "{}",
      "result": "(empty)",
      "error": false,
      "duration_ms": 0
    }
  },
  {
    "run_id": "20260822T072819-98a6708d",
    "type": "node_turn",
    "at": "2026-08-22T07:28:19.839+00:00",
    "node_id": "work",
    "data": {
      "turn": 2,
      "text": "",
      "thinking": "",
      "tool_call_count": 1
    }
  },
  {
    "run_id": "20260822T072819-98a6708d",
    "type": "node_tool_call",
    "at": "2026-08-22T07:28:19.840+00:00",
    "node_id": "work",
    "data": {
      "turn": 2,
      "name": "write_file",
      "arguments": "{\"path\": \"TODO.md\", \"content\": \"- write more tests\\n- add docs\\n- ship\\n\"}",
      "result": "wrote 37 characters to TODO.md",
      "error": false,
      "duration_ms": 0
    }
  },
  {
    "run_id": "20260822T072819-98a6708d",
    "type": "node_turn",
    "at": "2026-08-22T07:28:19.840+00:00",
    "node_id": "work",
    "data": {
      "turn": 3,
      "text": "Wrote TODO.md with three next steps.",
      "thinking": "",
      "tool_call_count": 0
    }
  },
  {
    "run_id": "20260822T072819-98a6708d",
    "type": "node_finished",
    "at": "2026-08-22T07:28:19.841+00:00",
    "node_id": "work",
    "data": {
      "step": 1,
      "next": null,
      "output": "Wrote TODO.md with three next steps.",
      "role": "flowState",
      "binding": "flowState -> fake:mock-model",
      "model": "mock-model",
      "usage": {
        "input_tokens": 0,
        "output_tokens": 6,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0
      },
      "stop_reason": "end_turn",
      "turns": 3,
      "tool_calls": 2
    }
  },
  {
    "run_id": "20260822T072819-98a6708d",
    "type": "run_finished",
    "at": "2026-08-22T07:28:19.842+00:00",
    "data": {
      "steps": 1,
      "usage": {
        "input_tokens": 0,
        "output_tokens": 6,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0
      },
      "path": [
        "work"
      ]
    }
  }
]

/** Six llm/router steps carrying a draft between two roles. */
export const LLM_RUN: PoieoEvent[] = [
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "run_started",
    "at": "2026-08-22T07:28:05.855+00:00",
    "data": {
      "graph": "draft-review",
      "flow": "revision",
      "trigger": "loop",
      "iteration": 1,
      "binding": "mock",
      "input": {
        "brief": "Why a workflow engine should not know which model it runs on."
      }
    }
  },
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "node_started",
    "at": "2026-08-22T07:28:05.857+00:00",
    "node_id": "draft",
    "data": {
      "type": "llm",
      "step": 1
    }
  },
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "node_finished",
    "at": "2026-08-22T07:28:05.858+00:00",
    "node_id": "draft",
    "data": {
      "step": 1,
      "next": "review",
      "output": "A first draft that is merely adequate.",
      "role": "writer",
      "binding": "writer -> fake:mock-model",
      "model": "mock-model",
      "usage": {
        "input_tokens": 0,
        "output_tokens": 7,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0
      },
      "stop_reason": "end_turn"
    }
  },
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "node_started",
    "at": "2026-08-22T07:28:05.858+00:00",
    "node_id": "review",
    "data": {
      "type": "llm",
      "step": 2
    }
  },
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "node_finished",
    "at": "2026-08-22T07:28:05.859+00:00",
    "node_id": "review",
    "data": {
      "step": 2,
      "next": "gate",
      "output": {
        "approved": false,
        "feedback": "The middle clause is limp."
      },
      "role": "critic",
      "binding": "critic -> fake:mock-model",
      "model": "mock-model",
      "usage": {
        "input_tokens": 0,
        "output_tokens": 8,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0
      },
      "stop_reason": "end_turn"
    }
  },
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "node_started",
    "at": "2026-08-22T07:28:05.860+00:00",
    "node_id": "gate",
    "data": {
      "type": "router",
      "step": 3
    }
  },
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "node_finished",
    "at": "2026-08-22T07:28:05.860+00:00",
    "node_id": "gate",
    "data": {
      "step": 3,
      "next": "revise",
      "output": "default",
      "matched": null,
      "label": "default"
    }
  },
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "node_started",
    "at": "2026-08-22T07:28:05.861+00:00",
    "node_id": "revise",
    "data": {
      "type": "llm",
      "step": 4
    }
  },
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "node_finished",
    "at": "2026-08-22T07:28:05.861+00:00",
    "node_id": "revise",
    "data": {
      "step": 4,
      "next": "review",
      "output": "A revised draft, now with a verb that earns its keep.",
      "role": "writer",
      "binding": "writer -> fake:mock-model",
      "model": "mock-model",
      "usage": {
        "input_tokens": 0,
        "output_tokens": 11,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0
      },
      "stop_reason": "end_turn"
    }
  },
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "node_started",
    "at": "2026-08-22T07:28:05.862+00:00",
    "node_id": "review",
    "data": {
      "type": "llm",
      "step": 5
    }
  },
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "node_finished",
    "at": "2026-08-22T07:28:05.863+00:00",
    "node_id": "review",
    "data": {
      "step": 5,
      "next": "gate",
      "output": {
        "approved": true,
        "feedback": "Good."
      },
      "role": "critic",
      "binding": "critic -> fake:mock-model",
      "model": "mock-model",
      "usage": {
        "input_tokens": 0,
        "output_tokens": 4,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0
      },
      "stop_reason": "end_turn"
    }
  },
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "node_started",
    "at": "2026-08-22T07:28:05.863+00:00",
    "node_id": "gate",
    "data": {
      "type": "router",
      "step": 6
    }
  },
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "node_finished",
    "at": "2026-08-22T07:28:05.864+00:00",
    "node_id": "gate",
    "data": {
      "step": 6,
      "next": null,
      "output": "approved",
      "matched": 0,
      "condition": "review.approved",
      "label": "approved"
    }
  },
  {
    "run_id": "20260822T072805-f3ba4128",
    "type": "run_finished",
    "at": "2026-08-22T07:28:05.864+00:00",
    "data": {
      "steps": 6,
      "usage": {
        "input_tokens": 0,
        "output_tokens": 30,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0
      },
      "path": [
        "draft",
        "review",
        "gate",
        "revise",
        "review",
        "gate"
      ]
    }
  }
]

/** A run that died in its first node. */
export const FAILED_RUN: PoieoEvent[] = [
  {
    "run_id": "20260822T072805-bcbbb588",
    "type": "run_started",
    "at": "2026-08-22T07:28:05.866+00:00",
    "data": {
      "graph": "agent-task",
      "flow": "chores",
      "trigger": "loop",
      "iteration": 1,
      "binding": "mock",
      "input": {
        "workdir": "/tmp/fx-work"
      }
    }
  },
  {
    "run_id": "20260822T072805-bcbbb588",
    "type": "node_started",
    "at": "2026-08-22T07:28:05.867+00:00",
    "node_id": "work",
    "data": {
      "type": "agent",
      "step": 1
    }
  },
  {
    "run_id": "20260822T072805-bcbbb588",
    "type": "run_failed",
    "at": "2026-08-22T07:28:05.868+00:00",
    "node_id": "work",
    "data": {
      "error": "NodeError: node 'work': workdir does not exist: \\tmp\\fx-work"
    }
  }
]

export const AGENT_SUMMARY: PoieoEvent = {
  "type": "run_summary",
  "run_id": "20260822T072819-98a6708d",
  "flow": "chores",
  "graph": "agent-task",
  "status": "completed",
  "started_at": "2026-08-22T07:28:19.836+00:00",
  "finished_at": "2026-08-22T07:28:19.842+00:00",
  "steps": 1,
  "iteration": 1,
  "usage": {
    "input_tokens": 0,
    "output_tokens": 6,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0
  },
  "error": null
}

export const LLM_SUMMARY: PoieoEvent = {
  "type": "run_summary",
  "run_id": "20260822T072805-f3ba4128",
  "flow": "revision",
  "graph": "draft-review",
  "status": "completed",
  "started_at": "2026-08-22T07:28:05.855+00:00",
  "finished_at": "2026-08-22T07:28:05.864+00:00",
  "steps": 6,
  "iteration": 1,
  "usage": {
    "input_tokens": 0,
    "output_tokens": 30,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0
  },
  "error": null
}

export const FAILED_SUMMARY: PoieoEvent = {
  "type": "run_summary",
  "run_id": "20260822T072805-bcbbb588",
  "flow": "chores",
  "graph": "agent-task",
  "status": "failed",
  "started_at": "2026-08-22T07:28:05.866+00:00",
  "finished_at": "2026-08-22T07:28:05.868+00:00",
  "steps": 1,
  "iteration": 1,
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0
  },
  "error": "NodeError: node 'work': workdir does not exist: \\tmp\\fx-work"
}
