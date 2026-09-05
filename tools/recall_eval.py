"""How well does a project's memory find the lesson a task needs?

Recall matches shared words and compares no meaning, so a lesson worded
differently from the task that needs it is never shown. This measures the
candidate fixes against that baseline, on one yardstick: the block a run
actually reads, through the same `read_memory` door a run goes through.

    python tools/recall_eval.py                          # score every arm
    python tools/recall_eval.py --corpus scifact         # on data nobody here wrote
    python tools/recall_eval.py --write-terms <binding>  # ask a model for the terms first
    python tools/recall_eval.py --judge <binding>        # ask a model which candidates apply

Not part of the gate. `--write-terms` and `--judge` need a binding that answers,
and the embedding arm needs a local ollama; both are skipped with a note rather
than a crash. Everything it builds lives in a throwaway folder outside the repo.

Cases and generated terms: tools/recall_eval_cases.json. External corpora and
their generated inputs live in a temp folder and are never checked in:
tools/recall_eval_adapters.py.
Design: docs/memory.md
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import math
import re
import shutil
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from recall_eval_adapters import Case, Corpus, Row, corpus_named  # noqa: E402

import poieo.memory.recall as memory_recall  # noqa: E402
from poieo.memory import frontmatter, read_memory, start_memory, write_entry, write_page  # noqa: E402
from poieo.memory.entries import _shaped, words  # noqa: E402
from poieo.memory.recall import ENTRIES_BUDGET  # noqa: E402

CASES = HERE / "recall_eval_cases.json"
# Real prose beats recombined vocabulary: randomly-mixed filler makes every
# entry trivially distinguishable and flatters every arm equally.
FILLER = ROOT / "docs"
# Both sizes are real prose. The larger one is close to what docs/ yields, so a
# third and larger size would have to repeat sentences -- see `main`.
SIZES = (120, 410)
KINDS = ("same-words", "different-words", "different-subject")
EMBED_MODEL = "nomic-embed-text"
EMBED_URL = "http://localhost:11434/api/embed"
# What separates one entry from the next in a block, and so how a place in it
# is counted.
BREAK = "\n\n"
# The longest entry a corpus cut at top-N may hold. Adapters cap bodies here,
# so N times this is room for exactly N entries and recall stops reading.
LONGEST = 2500


# -- the hand-written cases ---------------------------------------------------


def filler_key(sentence: str) -> str:
    """A filler entry's name, from its text rather than its place in the file.

    Keyed by position, every set of terms checked in here moved to a different
    sentence the moment docs/ was edited -- silently, and the scores with them.
    Keyed by content, an edit costs terms only for the sentences it added.
    """
    return "filler-" + hashlib.sha1(sentence.encode("utf-8")).hexdigest()[:12]


def filler_sentences() -> list[str]:
    """Sentences from this repo's own documentation, which read like the
    durable statements a memory keeps. Deterministic order, so two runs on one
    checkout build the same corpus."""
    found: list[str] = []
    seen: set[str] = set()
    for path in sorted(FILLER.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", " ", text, flags=re.S)
        text = re.sub(r"^\s*[|#>].*$", " ", text, flags=re.M)
        text = re.sub(r"[`*_\[\]]", "", text)
        for line in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ")):
            line = " ".join(line.split())
            if 60 <= len(line) <= 240 and re.match(r"^[A-Z]", line) and line.lower() not in seen:
                seen.add(line.lower())
                found.append(line)
    return found


def traps_for(data: dict, mine: list[Case]) -> dict[str, tuple[str, str]]:
    """The hard negative aimed at each of these tasks, by task id.

    A random unrelated entry does not mislead a model; one that looks related
    and is not, does. So a false positive is only worth counting in that shape,
    and each trap is the same topic as its task with advice that is wrong for
    it.
    """
    aimed = {}
    for trap in data.get("traps", []):
        for case in mine:
            if case.slug.startswith(trap["for"]):
                aimed[case.slug] = (trap["id"], trap["lesson"])
    return aimed


class Cases(Corpus):
    """The thirty hand-written tasks, their look-alikes, and real prose from
    docs/ to fill the memory around them. What every number before the
    external corpora came from."""

    name = "cases"
    cut = None
    shared_rows = True
    journals = True
    store = CASES

    def __init__(self) -> None:
        self.data = json.loads(CASES.read_text(encoding="utf-8"))
        self._cases = [
            Case(c["id"], c["class"], c["task"]["name"], c["task"]["prompt"], c["lesson"]) for c in self.data["cases"]
        ]
        self.sentences = filler_sentences()

    def kinds(self) -> list[str]:
        return list(KINDS)

    def cases(self, kind: str) -> list[Case]:
        return [c for c in self._cases if c.kind == kind]

    def sizes(self, kind: str) -> list[int]:
        return list(SIZES)

    def rows(self, kind, size, case, lesson_terms, with_terms) -> list[Row]:
        """One corpus: the lessons under test spread evenly through its ages,
        the look-alikes and enough real prose to fill it.

        The lessons are spread rather than heaped at one end because an entry
        the task matches nothing in is ordered newest first, and putting them
        all oldest or all newest would settle the answer before any arm ran.
        """
        mine = self.cases(kind)
        traps = sorted(set(self.aimed(kind).values()))
        filler = [(filler_key(line), line) for line in self.sentences[: size - len(mine) - len(traps)]]

        def row(slug: str, body: str) -> Row:
            return (slug, body, lesson_terms.get(slug, "") if with_terms else "")

        total = len(filler) + len(mine) + len(traps)
        spread = {int(i * total / len(mine)): c for i, c in enumerate(mine)}
        rest = iter([*traps, *filler])
        out = []
        for age in range(total):
            if age in spread:
                out.append(row(spread[age].slug, spread[age].lesson))
            else:
                slug, sentence = next(rest)
                out.append(row(slug, sentence))
        return out

    def aimed(self, kind: str) -> dict[str, tuple[str, str]]:
        return traps_for(self.data, self.cases(kind))

    def lesson_groups(self) -> list[list[tuple[str, str]]]:
        # Grouped so that no batch holds two wordings of one lesson. The same
        # lesson appears here twice, once in the task's words and once not, and
        # generating them together let the model read one and answer for the
        # other -- a paraphrase that never says "postgres" came back named
        # after it.
        sentences = self.sentences[: max(SIZES)]
        groups = [[(c.slug, c.lesson) for c in self.cases(kind)] for kind in KINDS]
        groups.append([(t["id"], t["lesson"]) for t in self.data.get("traps", [])])
        groups += [
            [(filler_key(line), line) for line in sentences[at : at + 60]] for at in range(0, len(sentences), 60)
        ]
        return groups

    def load_store(self) -> dict[str, Any]:
        return self.data

    def save_store(self, data: dict[str, Any]) -> None:
        CASES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# -- building one throwaway project ----------------------------------------


def build(at: Path, entries: list[Row]) -> None:
    """A project holding these entries, oldest first. Each is (slug, body, terms).

    Terms go into the *piece* -- the part of an entry retrieval matches on,
    which is never shown on its own -- and never into the body, so an arm that
    writes terms gains matches without spending a character of the budget.
    That is the change being measured, simulated here rather than in `src/`.

    Ages are stamped rather than taken from the clock. An entry the task
    matches nothing in is ordered newest first, and a corpus written inside one
    second falls back to ordering by name -- which moved answers between runs
    of this harness by two cases out of ten before it was pinned.
    """
    if at.exists():
        shutil.rmtree(at)
    (at / "work").mkdir(parents=True)
    (at / "poieo.yaml").write_text("version: 1\n", encoding="utf-8")
    start_memory(at)
    write_page(at, "- one line, so the page is never the thing under test\n")
    for slug, body, _ in entries:
        write_entry(at, slug, body, frontmatter({"scope": ["global"]}), writer="person")
    with sqlite3.connect(at / "memory" / "longterm.sqlite3") as con:
        for age, (slug, _, terms) in enumerate(entries):
            con.execute(
                "UPDATE entries SET updated_at = ? WHERE slug = ?",
                (f"2020-01-01T{age // 3600:02d}:{age // 60 % 60:02d}:{age % 60:02d}+00:00", slug),
            )
            if terms:
                con.execute(
                    "UPDATE pieces SET text = text || ' ' || ?, shape = shape || ' ' || ? WHERE slug = ? AND ord = 0",
                    (terms, _shaped(terms), slug),
                )
        con.commit()


def entries_in(block_text: str) -> list[str]:
    """The entry bodies in a block, without the page or the two headers.

    A block cut at top-N or already judged has been rebuilt without its
    headers and is entries only; reading that as "no header, so no entries"
    handed the judge an empty candidate list for every long-document task.
    """
    from poieo.memory.recall import LEARNED_HEADER

    if LEARNED_HEADER in block_text:
        block_text = block_text.split(LEARNED_HEADER, 1)[1]
    elif block_text.startswith(memory_recall.PAGE_HEADER):
        return []  # a page and nothing learned
    return [part for part in block_text.split(BREAK) if part.strip()]


def judgement_key(case: Case, bodies: list[str]) -> str:
    """One judgement per task and candidate set, so a rerun costs nothing and
    two runs on the same corpus give the same answer."""
    seed = f"{case.name}|{case.prompt}|" + "|".join(sorted(bodies))
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def judged(block_text: str, case: Case, verdicts: dict[str, Any]) -> str:
    """The block with what a judge said does not apply taken out.

    No verdict means no filtering: a missing judgement must read as the
    unjudged block rather than as an empty one.
    """
    bodies = entries_in(block_text)
    kept = verdicts.get(judgement_key(case, bodies))
    if kept is None:
        return block_text
    keep = {str(k) for k in kept}
    return BREAK.join(bodies[i] for i in range(len(bodies)) if str(i + 1) in keep)


def block(at: Path, case: Case, extra: str = "", cut: int | None = None) -> str:
    """What this task's next run would read. `extra` widens the task's own
    words, which is the task-side arm.

    A corpus of long documents is cut at the top N by rank instead of the
    character budget, which would show two abstracts and mean nothing. Done by
    lifting the budget for the read and keeping the first N, so every other
    rule recall applies still applies.
    """
    from recall_eval_adapters import Case as _Case

    class Stub(_Case):
        def __init__(self, root: Path, **kw: Any) -> None:
            super().__init__(**kw)
            self.folder = "work"
            self._root = root

        def folder_path(self) -> Path:
            return self._root / self.folder

    task = Stub(at, slug=case.slug, kind=case.kind, name=case.name, prompt=f"{case.prompt} {extra}".strip(), lesson="")
    if cut is None:
        return read_memory(at, task) or ""
    # Room for N of the longest entries, not for everything: with the budget
    # lifted outright, recall read every body in the corpus for every task and
    # a thousand abstracts times three hundred claims did not finish.
    kept = memory_recall.ENTRIES_BUDGET
    memory_recall.ENTRIES_BUDGET = cut * LONGEST
    try:
        text = read_memory(at, task) or ""
    finally:
        memory_recall.ENTRIES_BUDGET = kept
    return BREAK.join(entries_in(text)[:cut])


# -- the embedding arm ------------------------------------------------------


def ollama_up() -> bool:
    """Asked once per scoring run. A server that is listening but not
    answering made every embedding call wait out its timeout, and a run with
    six hundred of them never finished."""
    try:
        urllib.request.urlopen(EMBED_URL.rsplit("/", 2)[0] + "/api/tags", timeout=3).read()
        return True
    except (urllib.error.URLError, OSError):
        return False


def embed(texts: list[str]) -> list[list[float]] | None:
    out: list[list[float]] = []
    for at in range(0, len(texts), 64):
        body = json.dumps({"model": EMBED_MODEL, "input": texts[at : at + 64]}).encode()
        req = urllib.request.Request(EMBED_URL, data=body, headers={"Content-Type": "application/json"})
        try:
            out += json.loads(urllib.request.urlopen(req, timeout=60).read())["embeddings"]
        except (urllib.error.URLError, OSError, KeyError):
            return None
    return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) + 1e-9)


def dense_block(
    case: Case, corpus: dict[str, str], vectors: dict[str, list[float]], cut: int | None, seeds: dict[str, list[float]]
) -> str:
    """The same cut applied to a different order: nearest first, whole entries,
    the same character budget. Everything else recall does -- scope, anchors,
    association, the disagreement rule -- is missing here, and that asymmetry
    is stated in the output rather than hidden."""
    seed = seeds.get(case.slug)
    if seed is None:
        return ""
    order = sorted(corpus, key=lambda slug: -cosine(seed, vectors[slug]))
    if cut is not None:
        return BREAK.join(corpus[slug] for slug in order[:cut])
    chosen, spent = [], 0
    for slug in order:
        if spent + len(corpus[slug]) > ENTRIES_BUDGET:
            continue
        chosen.append(corpus[slug])
        spent += len(corpus[slug])
    return BREAK.join(chosen)


# -- writing the terms, blind ----------------------------------------------

LESSON_SIDE = """You keep a project's durable lessons. For each lesson below, write the words
somebody would be using while doing the work this lesson applies to -- the
vocabulary of the TASK, not of the lesson's own wording. You are not shown the
tasks and must not guess at any particular one.

8-12 words each, lowercase, space separated. Answer with JSON only, keyed by
the number each item was given:
{"1": "<words>", "2": "<words>", ...}

"""

TASK_SIDE = """You keep a project's durable lessons. For each task below, write the other words
this same task could be described with -- what a lesson about it might call the
things it touches. You are not shown the lessons and must not guess at any
particular one.

8-12 words each, lowercase, space separated. Answer with JSON only, keyed by
the number each item was given:
{"1": "<words>", "2": "<words>", ...}

"""

REFERENT = """You keep a project's durable lessons. For each lesson below, name the one thing
it is about -- the particular system, file, service or object it concerns, not
the subject area it belongs to. "the nginx access logs", not "logging". If two
lessons in a project were about different things in the same area, this is the
line that would tell them apart.

2-5 words each, lowercase. Answer with JSON only, keyed by the number each
item was given:
{"1": "<the thing>", "2": "<the thing>", ...}

"""

JUDGE = """Each task below is about to run, and has been handed lessons this project
learned earlier. Some apply to it. Others only look as though they do: they are
about a different system, file or service that happens to share vocabulary with
this task, and following one would be a mistake.

For each task, list the numbers of the lessons that actually apply to it.

Answer with JSON only, keyed by the task number:
{"1": [2, 5, 9], "2": [1, 4], ...}

"""

JOURNAL = """Each task below runs on a schedule and keeps a journal: one line per run, in
its own words, saying what it did. Write the journal each of these would have
after a few weeks of running -- 12 lines each, one sentence, under 300
characters.

Write what a real one looks like, not a tidy one. About a third of the lines
should be a run that went wrong, a digression, a half-finished thing picked up
next time, or a note somebody left the task. You are not shown what this
project has learned and must not guess at it.

Answer with JSON only, keyed by the number each task was given:
{"1": ["line", "line", ...], "2": [...], ...}

"""


async def ask(binding_path: Path, prompt: str) -> dict[str, Any]:
    from poieo.binding import load_binding
    from poieo.providers import LLMRequest, ProviderPool

    spec = load_binding(binding_path)
    resolved = spec.resolve("learner")
    async with ProviderPool(spec) as pool:
        answer = await pool.get(resolved.provider_name).complete(
            LLMRequest(
                model=resolved.model,
                messages=[{"role": "user", "content": prompt}],
                system=None,
                params=dict(resolved.params),
                role="learner",
            )
        )
    text = answer.text
    # The first complete object, not the span from the first brace to the
    # last: a model that adds a second object or a braced remark after its
    # answer turned that span into "extra data" nine calls into a run.
    found, _ = json.JSONDecoder().raw_decode(text[text.index("{") :])
    return found


async def _fill(
    binding: Path,
    what: str,
    prompt: str,
    items: list[tuple[str, str]],
    per: int,
    into: dict[str, Any],
    calls: dict[str, int],
) -> None:
    """Ask for what is missing, a batch at a time, and file the answers.

    The model is given a **number** per item and answers by number. It was given
    the entry's own name once, and a name here is a twelve-character digest --
    sixty of those echoed back by hand lost twenty of them to a mistyped
    character, silently, because a missing set of terms just reads as an entry
    that has none.
    """
    for at in range(0, len(items), per):
        batch = items[at : at + per]
        print(f"  {what} {at + len(batch)}/{len(items)} ...", flush=True)
        body = prompt + "\n".join(f"{i + 1}: {text}" for i, (_, text) in enumerate(batch))
        said: dict[str, Any] = {}
        # One retry, then move on: a two-hundred-call run must not die on
        # the ninth, and a batch that is skipped reads as entries with no
        # terms, which the scorer counts and says.
        for attempt in (1, 2):
            try:
                said = await ask(binding, body)
                calls[what] = calls.get(what, 0) + 1
                break
            except Exception as exc:  # noqa: BLE001 -- a provider hiccup must not end a long run either
                print(f"  {what}: attempt {attempt} failed ({type(exc).__name__}: {str(exc)[:120]})", flush=True)
        for i, (key, _) in enumerate(batch):
            answer = said.get(str(i + 1))
            if answer:
                into[key] = answer


async def write_verdicts(corpus: Corpus, binding_path: Path) -> None:
    """Ask a judge which of the candidates a task was handed actually apply.

    This is the step that needs a model where nothing else here does, so it is
    its own command: an ordinary scoring run reads what it wrote. One call per
    ten tasks rather than one per task, and answers are keyed by the task and
    its candidate set, so a rerun over an unchanged corpus asks nothing.
    """
    data = corpus.load_store()
    verdicts: dict[str, Any] = dict(data.get("verdicts") or {})
    calls: dict[str, int] = dict(data.get("calls") or {})
    per = 5 if corpus.cut else 10  # long documents: fewer tasks per call

    for kind in corpus.kinds():
        for size in corpus.sizes(kind):
            pool = candidates_for(corpus, kind, size, data)
            asking = [(c, pool[c.slug]) for c in corpus.cases(kind) if pool.get(c.slug)]
            asking = [(c, bodies) for c, bodies in asking if judgement_key(c, bodies) not in verdicts]
            for at in range(0, len(asking), per):
                batch = asking[at : at + per]
                print(f"  judging {kind} at {size}: {at + len(batch)}/{len(asking)} ...", flush=True)
                body = BREAK.join(
                    f"TASK {n + 1}: {c.name} -- {c.prompt}\n"
                    + "\n".join(f"  {i + 1}. {text}" for i, text in enumerate(bodies))
                    for n, (c, bodies) in enumerate(batch)
                )
                said = await ask(binding_path, JUDGE + body)
                calls["verdicts"] = calls.get("verdicts", 0) + 1
                for n, (c, bodies) in enumerate(batch):
                    answer = said.get(str(n + 1))
                    if answer is not None:
                        verdicts[judgement_key(c, bodies)] = answer
                data["verdicts"], data["calls"] = verdicts, calls
                corpus.save_store(data)  # after every call: a long pass may not finish

    data["verdicts"], data["calls"] = verdicts, calls
    corpus.save_store(data)
    print(f"wrote {len(verdicts)} judgements")


async def write_terms(corpus: Corpus, binding_path: Path) -> None:
    """Each side is written from its own text alone. Neither generator sees the
    other side, the corpus, or which lesson belongs to which task -- a score
    from terms written with both halves in view would mean nothing."""
    data = corpus.load_store()
    calls: dict[str, int] = dict(data.get("calls") or {})
    groups = corpus.lesson_groups()
    per = 30 if corpus.cut else 60  # long documents: fewer per call

    # Only what is missing. Adding a case should cost one small call, not a
    # rewrite of every set of terms already checked in and reviewed.
    known = data.get("terms") or {}
    lesson_terms: dict[str, str] = dict(known.get("lesson") or {})
    task_terms: dict[str, str] = dict(known.get("task") or {})
    tasks = [(k, v) for k, v in corpus.tasks() if k not in task_terms]
    for group in groups:
        want = [g for g in group if g[0] not in lesson_terms]
        await _fill(binding_path, "lesson-side terms", LESSON_SIDE, want, per, lesson_terms, calls)
        data["terms"], data["calls"] = {"lesson": lesson_terms, "task": task_terms}, calls
        corpus.save_store(data)
    await _fill(binding_path, "task-side terms", TASK_SIDE, tasks, 60, task_terms, calls)
    data["terms"], data["calls"] = {"lesson": lesson_terms, "task": task_terms}, calls
    corpus.save_store(data)

    # What each entry is about, for the entity pass. Written from the lesson
    # alone, like its terms, and for the filler too or the pass is only scoring
    # the cases.
    referents: dict[str, Any] = dict(data.get("referents") or {})
    for group in groups:
        want = [g for g in group if g[0] not in referents]
        await _fill(binding_path, "referents", REFERENT, want, per, referents, calls)
        data["referents"], data["calls"] = referents, calls
        corpus.save_store(data)

    # A stand-in, and the weakest thing here: a real journal is written by the
    # runs themselves and carries their failures and the notes people left. One
    # a model imagines is tidier than that however hard the prompt leans on it,
    # so this arm is measured optimistically and the output says so.
    journals: dict[str, Any] = dict(data.get("journals") or {})
    if corpus.journals:
        unwritten = [(k, v) for k, v in corpus.tasks() if k not in journals]
        await _fill(binding_path, "journals", JOURNAL, unwritten, 10, journals, calls)
    data["journals"] = journals

    data["terms"], data["calls"] = {"lesson": lesson_terms, "task": task_terms}, calls
    corpus.save_store(data)
    print(
        f"wrote {len(lesson_terms)} lesson-side and {len(task_terms)} task-side term sets, and {len(journals)} journals"
    )


# -- scoring ----------------------------------------------------------------

# label, whether entries carry written terms, what widens the task's words, and
# how a shared word is counted. The last two are what the multi-signal stacks
# call the keyword pass and the entity pass; the third pass is meaning, and it
# is arm E.
ARMS: tuple[tuple[str, bool, str, str], ...] = (
    ("A  words, as it is today", False, "", ""),
    ("B  lesson-side terms", True, "", ""),
    ("C  task-side terms", False, "terms", ""),
    ("D  both sides", True, "terms", ""),
    ("F  the card's own journal", False, "journal", ""),
    ("G  lesson terms + journal", True, "journal", ""),
    ("H  lesson terms + last 3 lines", True, "journal3", ""),
    ("I  rarer words count more", False, "", "idf"),
    ("J  rarer words + both sides", True, "terms", "idf"),
    ("K  what it is about + both sides", True, "terms", "referent"),
    ("L  all three", True, "terms", "idf referent"),
    ("M  all three, then judged", True, "terms", "idf referent judge"),
    ("E  embeddings", False, "dense", ""),
)

# What each arm needs written before it can run, in model calls at build time.
# Nothing needs a model at read time except a judge with a cold cache.
NEEDS: dict[str, tuple[str, ...]] = {
    "B": ("lesson-side terms",),
    "C": ("task-side terms",),
    "D": ("lesson-side terms", "task-side terms"),
    "F": ("journals",),
    "G": ("lesson-side terms", "journals"),
    "H": ("lesson-side terms", "journals"),
    "J": ("lesson-side terms", "task-side terms"),
    "K": ("lesson-side terms", "task-side terms", "referents"),
    "L": ("lesson-side terms", "task-side terms", "referents"),
    "M": ("lesson-side terms", "task-side terms", "referents", "verdicts"),
}

# A shared word is worth its rarity, scaled to whole numbers because a rank
# carries one. Ten keeps a whole block's worth of matches well under the anchor
# boost, which must stay the largest thing a score can hold.
_RARITY = 10
# What naming the same thing is worth, in shared words. Untuned: it is here to
# see whether the signal separates anything at all, not to find its best value.
_SAME_THING = 3


def rarity(entries: dict[str, set[str]]) -> dict[str, float]:
    """How much each word is worth: the fewer entries hold it, the more.

    The standard inverse document frequency. Over a few hundred short entries
    it is a coarse statistic and over twenty it is nearly none, which is the
    first thing to doubt if this arm disappoints.
    """
    total = len(entries) or 1
    seen: dict[str, int] = {}
    for shaped in entries.values():
        for word in shaped:
            seen[word] = seen.get(word, 0) + 1
    return {w: math.log(1 + (total - n + 0.5) / (n + 0.5)) for w, n in seen.items()}


def patch_ranking(shapes: dict[str, set[str]], referents: dict[str, set[str]], scoring: str):
    """Score the same candidates differently, and change nothing else.

    Wraps the ranking rather than replacing recall, so scope, anchors,
    association, the disagreement rule and the budget all still decide what
    they decide. An anchored entry keeps its boost: the wrapper can see it in
    the score it is handed and puts it back.
    """
    original = memory_recall._rank
    weights = rarity(shapes) if "idf" in scoring else {}

    def ranked(con, seed, use_index, where):
        out = []
        for found in original(con, seed, use_index, where):
            anchored = found.score >= memory_recall._ANCHOR_BOOST
            shared = seed & shapes.get(found.slug, set())
            if weights:
                score = round(_RARITY * sum(weights.get(word, 0.0) for word in shared))
                unit = _RARITY
            else:
                score = len(shared)
                unit = 1
            if "referent" in scoring and seed & referents.get(found.slug, set()):
                score += _SAME_THING * unit
            if anchored:
                score += memory_recall._ANCHOR_BOOST
            out.append(replace(found, score=score))
        return out

    return ranked


def _with_ranking(shapes, referents, scoring):
    kept = memory_recall._rank
    if scoring:
        memory_recall._rank = patch_ranking(shapes, referents, scoring)
    return kept


def candidates_for(corpus: Corpus, kind: str, size: int, data: dict) -> dict[str, list[str]]:
    """What each task in this class would be shown by the best-scoring arm,
    before any judge sees it -- so the judge is handed exactly what a run would
    hand it. A task whose entries carry no written terms is judged over the
    rarer-words candidates instead, and the output says which."""
    lesson_terms = (data.get("terms") or {}).get("lesson", {})
    task_terms = (data.get("terms") or {}).get("task", {})
    referents = {slug: words(text) for slug, text in (data.get("referents") or {}).items()}
    # One folder per corpus: two corpora scored at once shared one and the
    # second's rebuild pulled the first's database out from under it.
    at = Path(tempfile.gettempdir()) / f"poieo-recall-judge-{corpus.name}"
    out: dict[str, list[str]] = {}
    built: list[Row] | None = None
    for case in corpus.cases(kind):
        rows = corpus.rows(kind, size, case, lesson_terms, True)
        bare = sum(1 for _, _, t in rows if not t)
        covered = any(body == case.lesson and t for _, body, t in rows) and bare <= len(rows) // 20
        if not covered:
            rows = corpus.rows(kind, size, case, lesson_terms, False)
        if rows != built:
            build(at, rows)
            built = rows
        shapes = {slug: words(f"{body} {terms}") for slug, body, terms in rows}
        kept = _with_ranking(shapes, referents, "idf referent" if covered else "idf")
        try:
            out[case.slug] = entries_in(block(at, case, task_terms.get(case.slug, "") if covered else "", corpus.cut))
        finally:
            memory_recall._rank = kept
    shutil.rmtree(at, ignore_errors=True)
    return out


Scored = tuple[int, int, int, float, int, int, str]  # found, crowded, sprung, place, covered, first, note


def score(corpus: Corpus, kind: str, size: int, data: dict) -> dict[str, Scored]:
    """Every arm on one corpus: found, crowded out, and how deep in the block.

    `crowded out` counts other cases' lessons that took budget -- an arm that
    finds more by dragging in near-misses has not won, it has spent the same
    24 slots worse. `deep` is the mean place a found lesson sat, so a lesson
    that only just made the cut is visible as one. `covered` is how many tasks
    the arm could run on at all: one needing written terms skips a task whose
    entries have none rather than scoring the baseline under another name.
    """
    mine = corpus.cases(kind)
    terms = data.get("terms") or {}
    lesson_terms, task_terms = terms.get("lesson", {}), terms.get("task", {})
    # A journal reaches the prompt as lines; as query words it is one string.
    # The short form is there to separate two explanations of a bad score:
    # a journal is noisy, and a journal is long. Only one of those is fixable
    # by weighting rare words, which this scoring does not do.
    lines_of = data.get("journals") or {}
    journals = {slug: " ".join(lines) for slug, lines in lines_of.items()}
    journals3 = {slug: " ".join(lines[-3:]) for slug, lines in lines_of.items()}
    aimed = corpus.aimed(kind)
    # What each entry says it is about, as words. The entity pass of a
    # multi-signal stack, written blind from the lesson alone.
    referents = {slug: words(text) for slug, text in (data.get("referents") or {}).items()}
    verdicts = data.get("verdicts") or {}
    others = {c.slug: c.lesson for c in mine}
    at = Path(tempfile.gettempdir()) / f"poieo-recall-eval-{corpus.name}"
    out: dict[str, Scored] = {}

    # Two corpora, not one per arm: the arms differ in whether entries carry
    # written terms, and in what the task asks with. Only the first needs a
    # rebuild, and rebuilding is most of what this costs. A corpus that is one
    # per task rebuilds per task instead.
    for with_terms in (False, True):
        built: list[Row] | None = None
        bodies: dict[str, str] = {}
        shapes: dict[str, set[str]] = {}
        vectors: dict[str, list[float]] = {}
        seeds: dict[str, list[float]] = {}
        arms = [a for a in ARMS if a[1] is with_terms and (corpus.journals or "journal" not in a[2])]
        # found, crowded, sprung, places, covered, first -- "first" is the
        # gold at the head of the block, which is what the protocol papers
        # call hit@1 and the only number their floors compare to.
        tallies = {label: [0, 0, 0, [], 0, 0] for label, _, _, _ in arms}
        for case in mine:
            rows = corpus.rows(kind, size, case, lesson_terms, with_terms)
            # Covered means the lesson under test carries terms and nearly
            # every entry around it does. A batch a model refused -- thirty
            # biomedical abstracts tripped a safety filter -- leaves a few
            # entries bare; they behave as today's baseline, which is stated,
            # rather than voiding every task in the corpus.
            bare = sum(1 for _, _, t in rows if not t) if with_terms else 0
            gold_has = any(body == case.lesson and t for _, body, t in rows)
            covered = not with_terms or (gold_has and bare <= len(rows) // 20)
            if with_terms and not covered:
                continue
            if rows != built:
                build(at, rows)
                built = rows
                bodies = {slug: body for slug, body, _ in rows}
                shapes = {slug: words(f"{body} {t}") for slug, body, t in rows}
                vectors = {}
            for label, _, widen, scoring in arms:
                if widen == "dense":
                    if not ollama_up():
                        out[label] = (-1, -1, -1, 0.0, 0, 0, f"{EMBED_MODEL}'s server is not answering")
                        continue
                    if not vectors:
                        got = embed(list(bodies.values()))
                        if got is None:
                            out[label] = (-1, -1, -1, 0.0, 0, 0, f"no {EMBED_MODEL} on this machine")
                            continue
                        vectors = dict(zip(bodies, got))
                    if case.slug not in seeds:
                        got = embed([f"{case.name} {case.prompt} work"])
                        if got is None:
                            continue
                        seeds[case.slug] = got[0]
                    seen = dense_block(case, bodies, vectors, corpus.cut, seeds)
                    head = 0
                else:
                    wider = {"terms": task_terms, "journal": journals, "journal3": journals3}.get(widen, {})
                    kept = _with_ranking(shapes, referents, scoring)
                    try:
                        seen = block(at, case, wider.get(case.slug, ""), corpus.cut)
                    finally:
                        memory_recall._rank = kept
                    # A block from `read_memory` opens with the page and two
                    # headers, two blank lines before the first entry; a
                    # judged or top-N block is rebuilt without them.
                    head = 0 if "judge" in scoring or corpus.cut is not None else 2
                    if "judge" in scoring:
                        seen = judged(seen, case, verdicts)
                tally = tallies[label]
                tally[4] += 1
                if case.lesson in seen:
                    tally[0] += 1
                    place = seen[: seen.index(case.lesson)].count(BREAK) - head + 1
                    tally[3].append(place)
                    tally[5] += place == 1
                tally[1] += sum(1 for slug, body in others.items() if slug != case.slug and body in seen)
                tally[2] += 1 if case.slug in aimed and aimed[case.slug][1] in seen else 0
        for label, (found, crowded, sprung, places, covered, first) in tallies.items():
            if label not in out:
                deep = sum(places) / len(places) if places else 0.0
                out[label] = (found, crowded, sprung, deep, covered, first, "")
    shutil.rmtree(at, ignore_errors=True)
    return {label: out[label] for label, _, _, _ in ARMS if label in out}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="cases", help="cases (default), entity, longmemeval or scifact")
    parser.add_argument("--write-terms", metavar="BINDING", type=Path, help="ask this binding for the terms first")
    parser.add_argument("--judge", metavar="BINDING", type=Path, help="ask this binding which candidates apply")
    args = parser.parse_args()
    corpus: Corpus = Cases() if args.corpus == "cases" else corpus_named(args.corpus)

    if args.write_terms:
        asyncio.run(write_terms(corpus, args.write_terms))
        return

    if args.judge:
        asyncio.run(write_verdicts(corpus, args.judge))
        return

    data = corpus.load_store()
    terms = data.get("terms") or {}
    if not terms.get("lesson"):
        if isinstance(corpus, Cases):
            print("no terms written yet: run with --write-terms <binding.yaml> first")
            return
        # An external corpus still has its model-free arms to show; the ones
        # that need terms report zero coverage rather than a borrowed number.
        print("no terms written yet for this corpus: only the arms needing no model can score\n")

    if isinstance(corpus, Cases):
        sentences = corpus.sentences
        # Loud, not silent: an arm whose entries have no terms is measuring the
        # baseline while wearing another name.
        want = [filler_key(line) for line in sentences[: max(SIZES)]] + [c.slug for c in corpus._cases]
        missing = [key for key in want if key not in terms.get("lesson", {})]
        if missing:
            print(f"{len(missing)} of {len(want)} corpus entries have no written terms.")
            print(f"Run --write-terms before believing any arm but A. First: {missing[0]}")
            print()
        n = len(corpus._cases)
        print(f"{n} cases over {len(sentences)} real sentences from docs/; budget {ENTRIES_BUDGET} characters")
        print("A larger corpus was dropped, not silently capped: every entry needs its own written")
        print(f"terms for the lesson-side arm to be fair, and past {max(SIZES)} that costs more than it settles.\n")
    else:
        print(corpus.blurb)
        print("Not lesson-shaped like this project; each of these tests one claim, and the")
        print("arms, scoring and cut are the ones the hand-written cases ran through.")
        cut = f"top {corpus.cut} by rank" if corpus.cut else f"budget {ENTRIES_BUDGET} characters"
        print(f"cut: {cut}\n")

    for kind in corpus.kinds():
        mine = corpus.cases(kind)
        print(f"--- {kind} ({len(mine)} cases) ---")
        aimed = corpus.aimed(kind)
        for size in corpus.sizes(kind):
            got = score(corpus, kind, size, data)
            print(f"  {size} entries in memory:" if corpus.shared_rows else "  one memory per task:")
            for arm, (found, crowded, sprung, deep, covered, first, note) in got.items():
                if note:
                    print(f"     {arm:<26} skipped: {note}")
                    continue
                # No trap is aimed at a class, no number for it: a bare 0
                # there would read as an arm keeping look-alikes out.
                n = covered if covered else len(mine)
                trap = f"{sprung}/{n}" if aimed else "  n/a"
                line = (
                    f"     {arm:<26} found {found}/{n}   first {first}/{n}   look-alike shown {trap}"
                    f"   other lessons in the way {crowded}   mean place {deep:.1f}"
                )
                if not isinstance(corpus, Cases):
                    if covered < len(mine):
                        line += f"   [covered {covered} of {len(mine)} tasks]"
                    if arm.startswith("M") and "L  all three" in got:
                        line += f"   judge dropped {got['L  all three'][0] - found} right answers"
                    anchor = corpus.anchor(kind, arm)
                    if anchor:
                        line += f"   ({anchor})"
                print(line)
        print()

    if isinstance(corpus, Cases):
        print("What each costs, which decides as much as the scores:")
        print("  B  one pass over every existing entry, then one per new entry. Nothing at recall time.")
        print("  C  one pass per task, when it is created or edited. Nothing at recall time.")
        print("  E  an embedding model on the machine. Anthropic has no embeddings endpoint, so a")
        print("     project bound to Claude alone cannot do this without sending its memory elsewhere.")
    else:
        calls = data.get("calls") or {}
        print("Model calls it took to build this corpus's inputs, and what each arm needs:")
        for what, n in sorted(calls.items()):
            print(f"  {what:<18} {n} calls")
        for label, _, _, _ in ARMS:
            needs = NEEDS.get(label[0], ())
            print(f"  {label:<34} {', '.join(needs) if needs else 'nothing -- no model at build or read time'}")
        print("  Nothing needs a model at read time except a judge whose answer is not cached yet.")


if __name__ == "__main__":
    # This console defaults to cp949 and the prose in docs/ is full of em dashes.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    main()
