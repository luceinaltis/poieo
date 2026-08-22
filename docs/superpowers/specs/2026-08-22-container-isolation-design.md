# Container Isolation Design

**Date:** 2026-08-22
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

## Decisions already made (with the user)

- **Only the shell moves into the container.** File tools are already confined
  to the workdir by `resolve_path`, symlinks included; putting them through
  `docker exec` would add encoding, quoting, and ownership bugs to code whose
  blast radius is already correct. The hole is `run_command`, so `run_command`
  is what gets a box. What the user is promised — *the model cannot reach
  outside the folder* — holds either way, and this version is small enough to
  review.
- **The workdir is bind-mounted, not copied.** Host file tools and the
  container shell must see the same bytes at the same instant, or the model
  writes a file it then cannot compile.
- **Isolation is a property of the task, not of the graph.** DESIGN.md: "*A
  task can opt into container isolation*". A graph that named Docker would stop
  being portable — the same graph has to run on a laptop without Docker and on
  a server with it, which is exactly the separation principle 1 protects.
- **No silent fallback.** If a task asks for isolation and Docker is not there,
  the run fails and says so. Quietly running unsandboxed would turn a safety
  feature into a lie at the worst possible moment.
- **The network is off by default.** The reason to opt into a box is a smaller
  blast radius, and a container with a network can still post the workdir
  somewhere. A task that needs to install packages says so, in one line.
- **No image is guessed.** Opting in means naming an image. There is no
  universal "agent image", and inventing one would mean maintaining it.

## Out of scope

- Isolating file tools. See above — a later slice if the shell one proves out.
- Any isolation backend other than Docker. Podman, gVisor, Firecracker and
  friends are the same seam again; adding one is not this slice.
- Building images. poieo runs an image the user names; it does not write
  Dockerfiles and it does not `docker build`.
- Resource ceilings (cpu, memory, pids). Worth having, but a different axis
  from reachability, and DESIGN.md's Time boundary already caps wall clock.
- Isolating the *model*. The provider call goes out from the host as it always
  has. This slice is about the hands, not the mouth.
- Windows containers. The image is a Linux image; on Windows that means Docker
  Desktop's Linux engine, which is the normal configuration.

## Vocabulary

DESIGN.md principle 7 binds here: machinery does not appear in the interface.
The user opts in by naming an image, which is unavoidable and honest, but
everything poieo *says* is in product words.

| the user reads | never |
|---|---|
| this task runs **isolated** | container, docker, image id |
| **isolated** / **not isolated** on the card | bind mount, exec, network mode |
| "isolation is not available on this machine" | "docker daemon unreachable" |

The one licensed exception is a configuration error, where naming the real
thing is the only way to fix it: *`poieo check` — isolation requested but
docker is not on PATH*. Configuration is not the interface.

## Configuration

One optional block on a flow, mirroring the shape `workdir` takes:

```yaml
flows:
  - name: improve-poieo
    graph: graphs/agent-task.yaml
    workdir: ~/src/poieo
    isolation:
      image: python:3.12-slim     # required when the block is present
      network: none               # none (default) | bridge
      user: "1000:1000"           # optional; the uid files are written as
```

Absent the block, nothing changes anywhere. For a one-shot `poieo run`, the
same thing arrives as `--isolate <image>`.

**`image` is required, `network` defaults to `none`.** Both are validated when
the config is loaded, not when the trigger fires.

## How a tool call runs

```
1. node starts        the executor is built from the flow's isolation setting
2. container starts   one per agent-node execution, workdir bind-mounted at /work
3. read_file etc.     host path, resolve_path, exactly as today
4. run_command        docker exec -w /work <container> sh -c <command>
5. node ends          container stopped and removed, always, including on failure
```

One container per agent-node execution, not per tool call — starting a
container costs about a second, and a node with twenty turns should pay that
once. Not one per run either: the executor's lifetime is the node's, and tying
the container to something longer means owning a lifecycle no existing code
has.

Shell state does not persist between calls, inside the container or out of it.
Each `run_command` is a fresh process today and stays one; nothing about the
model's experience changes except what it can reach.

## The seam

`LocalExecutor` already advertises itself as the slot:

> The executor is the seam a future container-backed implementation slots into:
> same `definitions()`, same `execute()`, different blast radius.

`DockerExecutor` implements the same two methods. Two things have to grow to
let it in:

- **A lifecycle.** `LocalExecutor` needs no setup or teardown; a container
  does. Both become async context managers, and the agent node acquires its
  executor with `async with`. `LocalExecutor`'s pair is a no-op. This is the
  only change the runtime sees.
- **A choice.** One factory decides which executor a node gets, from a setting
  handed down beside the workdir. `runtime/nodes.py` gains no knowledge of
  Docker and no `if` — it calls the factory and uses what comes back.

Nothing else in `runtime/`, `graph.py`, or `tools/files.py` learns that
containers exist, which is the same fence the checkpoint slice draws around
git.

## Failure handling

Principle 5 — fail at launch, not at 3am — decides most of this table.

| situation | when | behaviour |
|---|---|---|
| `isolation` set, docker not on PATH | config load | flow refuses to load; `poieo check` names it |
| docker present, daemon not running | config load | same — the check is a real ping, not a PATH lookup |
| named image not present locally | config load | refuses, and prints `docker pull <image>` verbatim |
| docker dies mid-run | run | the run fails and is recorded; the daemon stays up (principle 5, other half) |
| container cannot start | node start | node fails with docker's own message; never a fallback to local |
| workdir does not exist | config load | already an error today; unchanged |
| command times out | tool call | killed inside the container, same `_MAX_TIMEOUT`; teardown still runs |
| poieo is killed mid-run | — | containers carry a `poieo.run_id` label, so orphans are findable and removable |
| files written as root in the container | run | why `user` exists; documented, not guessed at |

The image check sits at load time even though it is the slowest of the three.
A flow whose image was pruned last week must not discover it at 3am.

## Testing

- **Real containers, no mocks.** Mocking `docker` would test the mock — the
  same reasoning the checkpoint slice applies to git. The suite skips, loudly
  and with a reason, when the daemon is unreachable, so a machine without
  Docker still gets a green run and an honest count.
- The escape test is the point of the whole slice and is written first: with
  isolation on, a command that reads a file one level above the workdir **must
  fail**; the same command with isolation off succeeds. If that pair ever both
  pass, the feature is decorative.
- Network default: with `network: none`, a command that resolves a hostname
  fails.
- Lifecycle: no container survives a node that raised, a node that timed out,
  or a cancelled run.
- Bind-mount coherence: `write_file` then `run_command cat` sees the write, and
  the reverse.
- Every existing agent-node test runs with no `isolation` block and must be
  byte-for-byte unaffected — the whole feature is a no-op without it.

## Implementation split

One plan, six tasks: the executor and its escape test; the lifecycle seam; the
flow-level setting and the factory; load-time preflight; the CLI flag; docs and
an example. The web card's *isolated* badge is a line in a later frontend
slice — the API already carries flow configuration, so it costs nothing here.
