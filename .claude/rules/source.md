---
paths:
  - "src/poieo/**"
  - "src/poieo/**/*"
---

# Before you reshape this code

The habits this codebase keeps — the ones generic good taste would not predict, and
the reason each exists — are in **[docs/conventions.md](../../docs/conventions.md)**.
Read it before changing the shape of anything here.

This file is an adapter, not a rule. It exists so Claude Code raises the pointer at
the moment you open the source; the rules themselves are vendor-neutral and live in
`docs/`, where any agent or person finds them through the index. Nothing that an
agent must know belongs in this folder — a copy here is a copy that goes stale.
