# poieo, improving poieo

The thing the front page promises, wired up: pin the work down as flows and
let them turn while you are away. Five cards take one idea from *nobody has
built this yet* to *there is a pull request with a review on it*.

```
   scout ──proposed──▶ shape ──worth building──▶ build ──opened──▶ review ──clean──▶ land
     ▲                   │                         ▲                  │              (off)
     └─────too big───────┘                         └────findings──────┘
```

| card | what it does | reversible? |
|---|---|---|
| `scout` | reads the roadmap and the plans, proposes one small thing | reads only |
| `shape` | judges the proposal before anything is written | reads only |
| `build` | writes the test, makes it pass, runs the gate, opens the PR | a branch and a PR |
| `review` | reads the diff as though someone else wrote it, comments | a comment |
| `land` | merges it | **no** — off by default |

## Point it at a checkout

Every card's `folder:` is `../../..`, which is the checkout this example lives
in. **Runs will change that checkout.** They will not touch your working tree:
the folder is a git repository, so each run works in a private copy and lands
as one change on a `poieo/<flow>` branch, which you read as a diff and accept
or throw away. Point it somewhere else by editing `folder:` in the five cards.

## Start it

```bash
poieo daemon examples/improving-poieo/poieo.yaml
```

Two warnings at startup are expected and are the design saying so out loud:

- `review hands off to 'land', which is disabled` — yes; see below
- `handoffs form a cycle: build -> review -> build` — yes; a finding goes back
  to be fixed, and the chain depth limit bounds it

Only `scout` has a schedule. Everything after it runs because the card before
it handed over, which is why the board reads as a line rather than five
unrelated timers.

## Why `land` is off

Everything before it is reversible: a branch you delete, a pull request you
close, a private copy you throw away. Merging is not, and it is the only card
that changes something other people can see.

`AGENTS.md` says a human decides when a change touches a public interface,
deletes a test, adds a dependency, or moves how credentials are loaded. The
`review` card is told to answer `HOLD` on all four so they never reach `land`
— but **that guard is a prompt, and a prompt is not a fence.** Turn `land` on
when you have watched the four cards above it behave and you believe the
review. Until then the chain ends at a reviewed pull request waiting for you,
which is a good place for it to end.

## The models

`models.yaml` names four roles, and they are not the same size of job:

- `reader` — reads a roadmap, judges a proposal, says whether a suite went
  green. Short answers about text already in front of it. A small local model
  does this all day for nothing.
- `builder` — writes the change. Has to hold a codebase's conventions, write a
  failing test first, and keep a forty-turn session coherent.
- `reviewer` — reads a diff for what a green suite cannot tell you.
  Deliberately not the same model as `builder`: a reviewer that is the thing
  that wrote the code is a rubber stamp.

Everything ships pointing at a local model so this example can be read and
started with no account anywhere. Be honest with yourself about the last two —
a 9B will propose and judge all day and will not write a change that passes a
test-first gate. `models.yaml` has the block to uncomment when you want them
bigger, and the graphs do not change when you do.

## What it costs

Measured on this project against a cheap cloud model, one real code change —
find a missing guard, add it, write two tests, run the suite — was about 3,800
input and 700 output tokens. On a `$0.075/$0.25` per-million model that is
roughly **$0.0005 a change**, and a bigger codebase costs more because a
forty-turn agent resends its conversation every turn: input, not output, is
what grows.

The lever that matters most is `max_turns` in `build.graph.yaml`, then how
often `scout` fires. Two hours is the default here on purpose.
