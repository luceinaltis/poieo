# Task Notes Implementation Plan (Plan E)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A task can leave a line in another task's journal, and that line is read on the recipient's next run no matter how long the journal has grown — provable by one test where a note sits behind hundreds of older entries and still arrives.

**Architecture:** Nothing new is stored. A journal stays one append-only markdown file; the change is in how it is *read*. A task's own last entry is a bookmark: everything after it is new and is shown in full, everything before it is bounded history. One new toolset, `notes`, with one tool that appends a stamped line to another task's journal.

**Tech Stack:** Python 3.10, pytest + pytest-asyncio (asyncio_mode=auto).

**Spec:** docs/superpowers/specs/2026-08-23-task-notes-design.md

## Global Constraints

- **The journal file format does not change.** Same one line per entry, same timestamp, same width cap, same append-only rule. A journal written before this slice must read correctly after it, and a hand-edited one must keep working.
- **Nothing is written to track delivery.** No cursor file, no state key, no marker line. The bookmark is the task's own last entry, already there. If this plan ends with a new file next to the journal, it went wrong.
- **A task with no notes must read exactly as it does today.** The two-part split degrades to today's behaviour when nothing has arrived.
- **Loss is the bug this exists to prevent.** Anywhere the code must choose, it repeats rather than drops.
- **`notes` is opt-in.** Not in `DEFAULT_TOOLS`, not in `DEFAULT_TOOLSETS`.
- **The sender is stamped by poieo**, never taken from a tool argument.
- **Baseline:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio` → **270 passed** at `bb62391` with docker running; 241 passed / 29 skipped with it stopped. Both must stay green.
- Comment style: sparse, like the existing modules — explain constraints, not mechanics.
- Commit messages end with the trailer naming the model that wrote them, per CLAUDE.md.

## Vocabulary guard

The prompt says **new since you last worked**. Not *unread*, not *inbox*, not *messages pending*. A note reads as its sender: `[build-docs] rebuilt the docs`. Words that must not reach a prompt or a card: *queue, deliver, cursor, unread, backlog*.

---

### Task 1: read the journal in two parts

**Files:**
- Modify: `src/poieo/task.py` (`read_journal`, and what it returns)
- Test: `tests/test_task.py`

**Interfaces:**
- `read_journal` grows a second section rather than a second function: it returns the text a prompt gets, now composed of *new since the bookmark* (complete) and *history before it* (bounded).
- The bookmark is the last line the task itself wrote — a `did`, `nothing`, or `failed` entry. Lines after it are new whoever wrote them, so a user's note gets the same guarantee a task's note does.

**Why this task is first.** It is the whole safety property. The tool in Task 2 is trivial once delivery is guaranteed, and worthless before it.

**Batching.** When what is new exceeds the batch bound, show the oldest ones and say how many remain. The bookmark is a position in the file, so the rest arrive next run — but this only holds if the *shown* set is a prefix of the new set. Showing the newest first would silently strand the oldest forever.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_note_behind_a_long_journal_still_arrives(): ...     # THE test
def test_a_user_note_behind_a_long_journal_arrives(): ...      # the latent bug
def test_nothing_new_says_so_rather_than_vanishing(): ...
def test_history_is_still_bounded(): ...
def test_a_task_that_never_ran_sees_everything_as_new(): ...
def test_a_backlog_is_shown_oldest_first_and_counts_the_rest(): ...
def test_a_journal_with_no_notes_reads_as_it_did_before(): ...
def test_a_hand_written_line_after_the_bookmark_is_new(): ...
def test_an_unreadable_journal_still_lets_the_run_proceed(): ...
```

- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the full suite**
- [ ] **Step 5: Commit** — `feat: a task sees everything that arrived while it was away`

---

### Task 2: the `tell` tool

**Files:**
- Create: `src/poieo/tools/notes.py`
- Modify: `src/poieo/tools/__init__.py` (register the toolset)
- Test: `tests/test_tools_notes.py`

**Interfaces:**
- `tell(task, message)` — one line into the named task's journal, `kind` of `task`, sender stamped by poieo.
- The toolset needs to know **who is asking** and **which tasks exist**, and neither is in a workdir. Tools today receive only a workdir and arguments, so this task has to widen that seam.

**How to widen it.** Prefer binding the roster and the sender into the tool when the executor is built, over threading a new argument through every tool signature: three of the four existing tools would gain a parameter they do not use. Whatever shape is chosen, `tools/notes.py` must be the only module that knows a note has a sender.

**Refusals are tool errors, not exceptions.** An unknown name, a self-addressed note, an empty message: the model reads the failure and corrects itself, exactly as with a missing file. An unknown name lists the names that do exist — otherwise the model guesses again.

- [ ] **Step 1: Write the failing tests**

```python
async def test_tell_appends_to_the_recipients_journal(): ...
async def test_the_sender_is_stamped_not_supplied(): ...        # forgery
async def test_an_unknown_name_lists_the_real_ones(): ...
async def test_a_task_cannot_tell_itself(): ...
async def test_an_empty_message_is_refused(): ...
async def test_a_long_message_is_capped_like_any_entry(): ...
async def test_the_note_lands_after_the_recipients_bookmark(): ...   # end to end with Task 1
def test_notes_is_not_in_the_default_toolset(): ...
def test_a_task_without_notes_has_no_such_tool(): ...
```

- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the tests to verify they pass**
- [ ] **Step 5: Commit** — `feat: a task can leave a note for another task`

---

### Task 3: who else is there

**Files:**
- Modify: `src/poieo/task.py` (the generated system prompt)
- Test: `tests/test_task.py`

The model cannot address a task it does not know exists. The system prompt of a task that took the `notes` toolset lists its siblings by the name `tell` accepts, and says plainly that a note is read on that task's next run — so the model does not expect an answer.

A task without the toolset gets none of this: no roster, no sentence, no hint that other tasks exist.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_roster_lists_siblings_for_a_task_with_notes(): ...
def test_a_task_without_notes_sees_no_roster(): ...
def test_the_task_itself_is_not_in_its_own_roster(): ...
def test_the_prompt_says_a_note_is_not_a_reply(): ...
```

- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the tests to verify they pass**
- [ ] **Step 5: Commit** — `feat: a task knows which tasks it can tell`

---

### Task 4: document it and show it working

**Files:**
- Modify: `README.md`
- Modify: `DESIGN.md` (roadmap and capability layers — status only)
- Create: `examples/tasks/` — two cards that nudge each other

- [ ] **Step 1: The example**

Two task cards where one plausibly has news for the other — something rebuilt, something that should then be re-checked. Both on the mock binding so the pair runs offline. Whether they ship enabled depends on what the loader does with them; check before deciding.

- [ ] **Step 2: README**

Extend the journal section rather than opening a new one — that placement is the argument. Say that a task can leave a line in another task's journal, that it is read on that task's next run, that it is news rather than an instruction, and that the toolset is opt-in. One sentence on why this cannot loop.

- [ ] **Step 3: DESIGN.md**

"Tasks that work together" moves out of the candidate list. Change the status, not the argument; keep the file under 500 lines and at the logic level.

- [ ] **Step 4: The whole suite, both ways**

With docker running and with it stopped. Green both times; paste both summary lines.

- [ ] **Step 5: End to end by hand**

Run the pair on the mock binding. Confirm the note lands in the other journal, that the recipient's next run shows it under *new since you last worked*, and that a second run no longer does. Then append 200 lines of history and confirm the note still arrives — that is the property, and it should be seen once rather than only asserted.

- [ ] **Step 6: Commit** — `docs: tasks can leave each other notes`

---

## Done means

- A note behind a journal far longer than the display bound still arrives. So does a user's note, which could be buried before this slice.
- A failed run does not consume a note.
- No new file, no new state key, no marker line: `git diff` shows the journal format untouched.
- A task without the `notes` toolset has no such tool and no roster, and its journal reads exactly as it did before.
- Two tasks writing to each other still run only on their own triggers.
