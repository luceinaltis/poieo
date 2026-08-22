# Container Isolation Design

**Date:** 2026-08-22 (revised 2026-08-23)
**Status:** Approved for planning
**Roadmap:** the last unfilled cell in DESIGN.md's safety boundaries

## Goal

A task can be told to keep its hands inside a box. When it is, **the model
cannot reach anything on the machine except the folder it was given** — not by
a shell command, not by an absolute path, not by a symlink.

Today the fence is path checking, and `tools/shell.py` says so in its own
docstring:

> The command's cwd is pinned to the workdir; the command itself can still name
> absolute paths — that boundary needs an OS sandbox, which the local executor
> does not claim to be.

This slice builds that sandbox. It is opt-in, per task, and everything without
it behaves exactly as it does today.

## Where this sits

The checkpoint slice protects the files *inside* the working directory: the
model works in a private copy, and a night's work arrives as a change to accept
or discard. This slice protects everything *outside* it. Neither substitutes
for the other, and together they are what makes "leave it running overnight" a
reasonable thing to say.

| boundary | before | after |
|---|---|---|
| file tools (`read_file`, `write_file`, `list_dir`, `glob_files`) | confined by `resolve_path` | unchanged |
| `run_command` | **the whole machine** | the working directory, and nothing else |

## What the field does

Surveyed before choosing, because the shape of this problem is well explored.
Two axes matter.

**What goes inside the box.** Three answers exist: the whole harness (Claude
Code dev containers, Docker Sandboxes microVMs — the user runs the agent
*inside*), a split where the controller stays on the host and an execution
server lives in the container (OpenHands), or only the tool calls (Codex CLI,
whose main process "runs unsandboxed; only the shell commands it executes for
the AI are sandboxed").

poieo takes the third. The first needs no product support at all — a user who
wants it runs `poieo` in a container today. The second is a protocol and a
server to maintain, and buys nothing while file tools are already confined.

**How long a box lives.** Nobody starts a container per command; at ~200ms
measured on this machine, it would dominate. Codex CLI *does* sandbox per
command, but only because Landlock and Seatbelt cost nearly nothing — the
mechanism decides the granularity you can afford. Container users keep one
alive across many commands: OpenHands per conversation, SWE-agent per
benchmark instance.

poieo's shape is different from both. A conversation ends; a benchmark instance
is meant to be reproducible. **A poieo task is designed to accumulate** — its
journal is re-read before every run, and its private working copy persists
across runs. A box that resets hourly would be the one part of a task that
refuses to remember.

So: **a box is kept between runs, and shared by whatever tasks want the same
one.** See *Lifetime* below for both halves of that.

## Decisions already made (with the user)

- **Only the shell moves into the container.** File tools are already confined
  to the workdir by `resolve_path`, symlinks included; putting them through
  `docker exec` would add encoding, quoting, and ownership bugs to code whose
  blast radius is already correct. The hole is `run_command`, so `run_command`
  is what gets a box.
- **The workdir is bind-mounted, not copied.** Host file tools and the
  container shell must see the same bytes at the same instant, or the model
  writes a file it then cannot compile.
- **Isolation is a property of the task, not of the graph.** DESIGN.md: "*A
  task can opt into container isolation*". A graph that named Docker would stop
  being portable — the same graph has to run on a laptop without Docker and on
  a server with it, which is exactly what principle 1 protects.
- **No silent fallback.** If a task asks for isolation and Docker is not there,
  the run fails and says so. Quietly running unsandboxed would turn a safety
  feature into a lie at the worst possible moment.
- **The network is off by default.** The reason to opt into a box is a smaller
  blast radius, and a container with a network can still post the workdir
  somewhere. A task that needs to install packages says so, in one line.
- **No image is guessed.** Opting in means naming an image. There is no
  universal "agent image", and inventing one would mean maintaining it.

## Out of scope

- Isolating file tools. A later slice if the shell one proves out.
- Any backend other than Docker. Podman, gVisor, Firecracker and the OS-level
  primitives (Landlock, Seatbelt, restricted tokens) are the same seam again.
  The factory makes each of them one module and one branch; none of them is
  this slice.
- Building images. poieo runs an image the user names; it does not write
  Dockerfiles and it does not `docker build`.
- Resource ceilings (cpu, memory, pids). A different axis from reachability,
  and DESIGN.md's Time boundary already caps wall clock.
- Isolating the *model*. The provider call goes out from the host as it always
  has. This slice is about the hands, not the mouth.
- Windows containers. The image is a Linux image; on Windows that means Docker
  Desktop's Linux engine, which is the normal configuration.

## Vocabulary

DESIGN.md principle 7 fixes the user's whole model at three words — **task**,
**work**, **change** — and says machinery does not appear in the interface.

**Isolation does not become a fourth word.** It is an adjective on a task:

```
task = a name, a prompt, a folder   [+ isolated or not]
```

The forbidden list grows to match. Words that must never appear in the
interface: *container, image, mount, volume, exec, network mode* — alongside
the git words the checkpoint slice already banned.

**What replaces them is one idea: reach.** The question a user actually asks is
"what can it touch?", and that has an answer with no machinery in it:

```
Every task has a folder. That folder is the work.

Not isolated:  poieo's own file tools stay inside that folder.
               A command it runs does not — it reaches whatever you can reach.

Isolated:      a command it runs stays inside that folder too.
```

Naming an image is the one unavoidable leak, and it is licensed: DESIGN.md
already excepts configuration, because naming the real thing is the only way to
fix it. So `image: python:3.12-slim` lives in the task file and in
`poieo check`'s errors; the card says only **isolated**.

## What this does not protect

The honest half, and the one that must not be softened. A security claim that
overstates is worth the same as one that lies.

| | |
|---|---|
| **the folder itself** | It is the work; it is exposed by definition. Undo is the *change* slice's job, not this one's. |
| **what reaches the model** | Prompts and file contents leave the host as they always did. The box holds the hands, not the mouth. |
| **absolute guarantees** | A container shares the host kernel. Escapes are hard, not impossible — that is exactly why Docker Sandboxes reaches for microVMs. A microVM or an OS-level sandbox is a stronger boundary, and the factory leaves room for both. |

The decision this hands the user is a real one, and the README should ask it
plainly: *can you predict every command this prompt will run, overnight, with
this model?* If yes, isolation buys little. If no, that is what it is for.

## Configuration

One optional block on a task, mirroring the shape `folder` takes:

```yaml
name: keep the examples tidy
folder: ..
prompt: |
  Look through this folder and fix one small thing that is out of date.
isolation:
  image: python:3.12-slim     # required when the block is present
  network: none               # none (default) | bridge
  user: "1000:1000"           # optional; the uid files are written as
```

Absent the block, nothing changes anywhere. A hand-written flow takes the same
block. For a one-shot `poieo run`, it arrives as `--isolate <image>`.

**`image` is required, `network` defaults to `none`.** Both are validated when
the config loads, not when the trigger fires.

## Lifetime

**One box per folder-and-settings, kept between runs.** The task's other
durable things — its journal, its private working copy — already work this way,
and a box that reset hourly would contradict them. A task that installs its
dependencies on Monday still has them on Tuesday.

**Two tasks that want the same box get the same box.** Several standing jobs
over one repo — keep the tests green, keep the docs current, keep the lint
quiet — is the ordinary shape, and a box each would mean installing one
toolchain three times. The daemon already keeps one provider pool per binding
file for exactly this reason; boxes sit beside the pools.

Sharing is implicit, and that has a cost worth naming: tasks in one box can
disturb each other, because a box is one machine. What they still cannot
disturb is anything outside the folder, which is the boundary this slice is
about. Naming a shared box would make the coupling visible, but it would also
be a fourth word against principle 7 — and it stays available later, because
adding a name to something implicit is additive while removing a concept
users have learned is not.

The box is **derived state**, exactly as the private worktree is: deleting it
is always safe, and the next run rebuilds it. That property is what makes
keeping it defensible, because it turns drift from a corruption into a
refresh.

It is thrown away and rebuilt when:

| trigger | why |
|---|---|
| a task's `isolation` block changes | a box built from a different image is not the box that was asked for |
| the daemon restarts | the reset a user already knows how to reach |
| the box is older than 7 days | docker records creation, not last use; an age cap is the honest version and one rebuild a week is the ceiling working |
| the user asks (`poieo reset <task>`) | the explicit escape hatch, and the thing to suggest when a task starts behaving oddly |

**Daemon restart is a weaker bound than it sounds.** A resident daemon is meant
to run for weeks, so it is the idle sweep that actually caps how old a box
gets. Both are here for that reason; neither is sufficient alone.

A one-shot `poieo run --isolate` has no next run to keep a box for, so it gets
an ephemeral one, removed when the run ends.

Within a run, every agent node working in one folder shares one box. Nodes in one graph
already share a working directory; giving them separate boxes would isolate
them from each other and from nothing that matters, while making step 1's
`pip install` invisible to step 2.

## How a tool call runs

```
1. task starts       FlowRunner holds the task's box, as it holds its worktree
2. box ensured       started if missing or dead; reused if healthy
3. read_file etc.    host path, resolve_path, exactly as today
4. run_command       docker exec -w /work <container> sh -c <command>
5. run ends          the box stays; nothing is torn down
6. task retired      daemon stops, config changes, or the sweep fires -> removed
```

Shell state does not persist between calls, inside the box or out of it. Each
`run_command` is a fresh process today and stays one; what persists is the
filesystem, which is the point.

## The seam

`LocalExecutor` already advertises itself as the slot:

> The executor is the seam a future container-backed implementation slots into:
> same `definitions()`, same `execute()`, different blast radius.

`DockerExecutor` implements the same two methods. Three things grow to let it
in:

- **A lifecycle.** `LocalExecutor` needs no setup or teardown; attaching to a
  box does. Both become async context managers, and the agent node acquires
  its executor with `async with`. `LocalExecutor`'s pair is a no-op.
- **A choice.** One factory decides which executor a node gets, from a setting
  handed down beside the workdir. `runtime/nodes.py` gains no knowledge of
  Docker and no `if`.
- **An owner.** Because a box outlives a run, something that outlives a run
  must hold it. That is `FlowRunner` — "drives one flow: trigger -> run ->
  carry state -> repeat" — which Plan C already makes the owner of the task's
  private worktree. Because a box is shared across tasks, the keeper itself
  sits on the `Daemon`, beside the provider pools it already shares. The
  executor *attaches* to a box it is handed; only the one-shot path creates and
  destroys its own.

What the runtime receives is an opaque handle with no Docker words on it, the
same way it receives a workdir without knowing how the worktree was made.
Nothing in `runtime/`, `graph.py`, or `tools/files.py` learns that containers
exist.

## Failure handling

Principle 5 — fail at launch, not at 3am — decides most of this table.

| situation | when | behaviour |
|---|---|---|
| `isolation` set, docker not on PATH | config load | the task refuses to load; `poieo check` names it |
| docker present, daemon not running | config load | same — a real ping, not a PATH lookup |
| named image not present locally | config load | refuses, and prints `docker pull <image>` verbatim |
| the box died between runs | run start | rebuilt; it is derived state, and this is the ordinary case after a machine sleeps |
| the box cannot be started | run start | the run fails with docker's own message; never a fallback to local |
| docker dies mid-run | run | the run fails and is recorded; the daemon stays up (principle 5, other half) |
| command times out | tool call | killed inside the box, same `_MAX_TIMEOUT`; the box survives, as it would after any failed command |
| poieo is killed | — | boxes carry a `poieo.box` label, so orphans are findable, sweepable, and removable by hand |
| two tasks share a folder | — | one box, shared. They are concurrent writers in one place; the checkpoint slice is what makes that reviewable |
| files written as root in the box | run | why `user` exists; documented, not guessed at |

## Testing

- **Real containers, no mocks.** Mocking `docker` would test the mock — the
  same reasoning the checkpoint slice applies to git. The suite skips, loudly
  and with a reason, when the daemon is unreachable, so a machine without
  Docker still gets a green run and an honest count.
- The escape pair is the point of the whole slice and is written first: with
  isolation on, a command that reads a file one level above the workdir **must
  fail**; the same command with isolation off succeeds. If that pair ever both
  pass, the feature is decorative.
- Reuse: two runs of one task land in the same box, and a file written by the
  first run's shell is still there for the second. That is the lifetime
  decision, stated as a test.
- Sharing: two tasks over one folder get one box; a different folder or a
  different image gets its own.
- Rebuild: changing the `isolation` block replaces the box; a removed box is
  rebuilt on the next run; the idle sweep removes an old one and leaves a
  fresh one.
- Network default: with `network: none`, a container has no `eth0`.
- Cleanup: no box survives the daemon stopping, and none leaks from a run that
  raised, timed out, or was cancelled.
- Bind-mount coherence: `write_file` then `run_command cat` sees the write, and
  the reverse.
- Every existing agent-node test runs with no `isolation` block and must be
  byte-for-byte unaffected — the whole feature is a no-op without it.

## Implementation split

Plan D, seven tasks: the executor and its escape test; the lifecycle seam and
factory; the box registry and its owner; the task-level setting; load-time
preflight; `poieo run --isolate` and `poieo reset`; docs and an example. The
card's *isolated* badge is a line in a later frontend slice — the API already
carries task configuration, so it costs nothing here.
