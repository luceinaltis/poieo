# Code conventions

These are the repository’s deliberate departures from generic Python or
TypeScript style. The merge procedure and commands are in
[`AGENTS.md`](../AGENTS.md).

## Point modules at their design contract

Production Python modules start with a module docstring that states their
responsibility. A module that points to a component contract uses a `Design:`
line naming its guide in `docs/`; tests verify that every pointer used resolves
to a real document.

Keep the component guide about the current contract: responsibility, data and
configuration shape, important flows, failure handling, constraints, and
extension points. History belongs in Git. Do not create dated design files.

## Reject unknown configuration

User-authored Pydantic models use `extra="forbid"`. A misspelled key must fail
where the file is loaded; ignoring it can silently change unattended work.

Resolve relative paths from the file that contains them, not from the process
working directory. Preserve authored YAML when a command changes one setting:
comments and unrelated choices are the user’s data too.

## Errors are part of the interface

Expected configuration, provider, runtime, and workspace failures use the
project’s `PoieoError` family. CLI commands report those in the product’s voice
without a traceback. Unexpected programming errors should still surface as
such.

Persisted runtime failures may include a structured cause. Cause slugs and
their meanings are storage and UI contracts: prefer a stable category plus a
human explanation and recovery hint over matching exception text. Adding or
renaming a slug requires updating every reader and its tests.

## Unknown is not zero

Use `None` when a provider did not report a value. Zero means a measured zero;
it must not stand in for unknown context size, token usage, cost, or another
missing observation. Preserve that distinction through storage, aggregation,
JSON, and the browser.

## Comments explain constraints

Comments should preserve facts the code cannot express: an ordering required
for durability, a security boundary, a platform exception, or why an apparent
simplification would break a contract. Do not narrate the next line or retain
the story of a bug already fixed.

Move a comment with the constraint it describes. Module docstrings describe
the module’s current responsibility, not a roadmap.

## Keep seams narrow

The graph, binding, runtime, tools, storage, daemon, workspace, memory, and web
layers each have a component guide. Depend on their small public contracts
rather than reaching into implementation state. In particular:

- graphs name roles; bindings choose concrete models;
- runtime nodes receive tools through the tool registry;
- run consumers read the store interface, not event files directly;
- browser actions go through the HTTP boundary;
- project paths come from the project layout rather than repeated literals.

When a new backend fits an existing registry or protocol, extend that seam.
Do not add a parallel configuration shape for the same idea.

## Tests name behavior

Write the failing behavior test before the implementation. Test names should
state the observable rule and avoid private method names unless that private
unit is itself the only meaningful boundary.

Use the narrowest test level that proves the contract, then retain integration
coverage for boundaries such as YAML preservation, subprocess behavior,
streamed events, filesystem recovery, and browser requests. Tests must not
write into committed examples or depend on a developer’s credentials.

## Use the product vocabulary

The user-facing nouns are **task**, **run**, and **change**:

- a task is the standing instruction;
- a run is one attempt to carry it out;
- a change is the reviewable result applied to a user’s files.

Use those words in code names, tests, and documentation when they describe the
product. Keep domain terms such as graph node, provider, binding, journal, and
worktree only where the distinction is technically necessary. Do not introduce
a synonym that makes the same object look like a fourth concept.
