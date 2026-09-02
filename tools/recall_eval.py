"""How well does a project's memory find the lesson a task needs?

Recall matches shared words and compares no meaning, so a lesson worded
differently from the task that needs it is never shown. This measures the
candidate fixes against that baseline, on one yardstick: the block a run
actually reads, through the same `read_memory` door a run goes through.

    python tools/recall_eval.py                  # score every arm
    python tools/recall_eval.py --write-terms    # ask a model for the terms first

Not part of the gate. `--write-terms` needs a binding that answers, and the
embedding arm needs a local ollama; both are skipped with a note rather than a
crash. Everything it builds lives in a throwaway folder outside the repo.

Cases and generated terms: tools/recall_eval_cases.json.
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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

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


# -- the corpus -------------------------------------------------------------


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


@dataclass
class Case:
    slug: str
    kind: str
    name: str
    prompt: str
    lesson: str


@dataclass
class Stub:
    """What recall asks of a task, and nothing more."""

    slug: str
    name: str
    prompt: str
    folder: str
    root: Path

    def folder_path(self) -> Path:
        return self.root / self.folder


def load_cases() -> tuple[list[Case], dict]:
    data = json.loads(CASES.read_text(encoding="utf-8"))
    cases = [Case(c["id"], c["class"], c["task"]["name"], c["task"]["prompt"], c["lesson"]) for c in data["cases"]]
    return cases, data


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


# -- building one throwaway project ----------------------------------------


def build(at: Path, entries: list[tuple[str, str, str]]) -> None:
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
                (f"2020-01-01T00:{age // 60:02d}:{age % 60:02d}+00:00", slug),
            )
            if terms:
                con.execute(
                    "UPDATE pieces SET text = text || ' ' || ?, shape = shape || ' ' || ? WHERE slug = ? AND ord = 0",
                    (terms, _shaped(terms), slug),
                )
        con.commit()


def block(at: Path, case: Case, extra: str = "") -> str:
    """What this task's next run would read. `extra` widens the task's own
    words, which is the task-side arm."""
    task = Stub(case.slug, case.name, f"{case.prompt} {extra}".strip(), "work", at)
    return read_memory(at, task) or ""


# -- the embedding arm ------------------------------------------------------


def embed(texts: list[str]) -> list[list[float]] | None:
    out: list[list[float]] = []
    for at in range(0, len(texts), 64):
        body = json.dumps({"model": EMBED_MODEL, "input": texts[at : at + 64]}).encode()
        req = urllib.request.Request(EMBED_URL, data=body, headers={"Content-Type": "application/json"})
        try:
            out += json.loads(urllib.request.urlopen(req, timeout=300).read())["embeddings"]
        except (urllib.error.URLError, OSError, KeyError):
            return None
    return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) + 1e-9)


def dense_block(case: Case, corpus: dict[str, str], vectors: dict[str, list[float]]) -> str:
    """The same cut applied to a different order: nearest first, whole entries,
    the same character budget. Everything else recall does -- scope, anchors,
    association, the disagreement rule -- is missing here, and that asymmetry
    is stated in the output rather than hidden."""
    seed = embed([f"{case.name} {case.prompt} work"])
    if seed is None:
        return ""
    order = sorted(corpus, key=lambda slug: -cosine(seed[0], vectors[slug]))
    chosen, spent = [], 0
    for slug in order:
        if spent + len(corpus[slug]) > ENTRIES_BUDGET:
            continue
        chosen.append(corpus[slug])
        spent += len(corpus[slug])
    return "\n\n".join(chosen)


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
    return json.loads(text[text.index("{") : text.rindex("}") + 1])


async def _fill(
    binding: Path, what: str, prompt: str, items: list[tuple[str, str]], per: int, into: dict[str, Any]
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
        said = await ask(binding, prompt + "\n".join(f"{i + 1}: {text}" for i, (_, text) in enumerate(batch)))
        for i, (key, _) in enumerate(batch):
            answer = said.get(str(i + 1))
            if answer:
                into[key] = answer


async def write_terms(binding_path: Path) -> None:
    """Each side is written from its own text alone. Neither generator sees the
    other side, the corpus, or which lesson belongs to which task -- a score
    from terms written with both halves in view would mean nothing."""
    cases, data = load_cases()
    sentences = filler_sentences()[: max(SIZES)]

    # Grouped so that no batch holds two wordings of one lesson. The same
    # lesson appears here twice, once in the task's words and once not, and
    # generating them together let the model read one and answer for the other
    # -- a paraphrase that never says "postgres" came back named after it.
    groups = [[(c.slug, c.lesson) for c in cases if c.kind == kind] for kind in KINDS]
    groups.append([(t["id"], t["lesson"]) for t in data.get("traps", [])])
    groups += [[(filler_key(line), line) for line in sentences[at : at + 60]] for at in range(0, len(sentences), 60)]
    tasks = {c.slug: f"{c.name}: {c.prompt}" for c in cases}

    # Only what is missing. Adding a case should cost one small call, not a
    # rewrite of every set of terms already checked in and reviewed.
    known = data.get("terms") or {}
    lesson_terms: dict[str, str] = dict(known.get("lesson") or {})
    task_terms: dict[str, str] = dict(known.get("task") or {})
    tasks = {k: v for k, v in tasks.items() if k not in task_terms}
    for group in groups:
        want = [g for g in group if g[0] not in lesson_terms]
        await _fill(binding_path, "lesson-side terms", LESSON_SIDE, want, 60, lesson_terms)
    await _fill(binding_path, "task-side terms", TASK_SIDE, list(tasks.items()), 60, task_terms)

    # What each entry is about, for the entity pass. Written from the lesson
    # alone, like its terms, and for the filler too or the pass is only scoring
    # the cases.
    referents: dict[str, Any] = dict(data.get("referents") or {})
    for group in groups:
        await _fill(binding_path, "referents", REFERENT, [g for g in group if g[0] not in referents], 60, referents)
    data["referents"] = referents

    # A stand-in, and the weakest thing here: a real journal is written by the
    # runs themselves and carries their failures and the notes people left. One
    # a model imagines is tidier than that however hard the prompt leans on it,
    # so this arm is measured optimistically and the output says so.
    journals: dict[str, Any] = dict(data.get("journals") or {})
    unwritten = [(c.slug, f"{c.name}: {c.prompt}") for c in cases if c.slug not in journals]
    await _fill(binding_path, "journals", JOURNAL, unwritten, 10, journals)
    data["journals"] = journals

    data["terms"] = {"lesson": lesson_terms, "task": task_terms}
    CASES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {len(lesson_terms)} lesson-side and {len(task_terms)} task-side term sets, and {len(journals)} journals"
    )


# -- scoring ----------------------------------------------------------------

# label, whether entries carry written terms, and what widens the task's own
# words: nothing, terms a model wrote for that prompt, or the card's journal --
# its own account of what it has been doing, which costs no model and cannot
# go stale against a prompt somebody edits.
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
    ("E  embeddings", False, "dense", ""),
)


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


Scored = tuple[int, int, int, float, str]


def score(kind: str, size: int, cases: list[Case], data: dict, sentences: list[str]) -> dict[str, Scored]:
    """Every arm on one corpus: found, crowded out, and how deep in the block.

    `crowded out` counts other cases' lessons that took budget -- an arm that
    finds more by dragging in near-misses has not won, it has spent the same
    24 slots worse. `deep` is the mean place a found lesson sat, so a lesson
    that only just made the cut is visible as one.
    """
    mine = [c for c in cases if c.kind == kind]
    terms = data.get("terms") or {}
    lesson_terms, task_terms = terms.get("lesson", {}), terms.get("task", {})
    # A journal reaches the prompt as lines; as query words it is one string.
    # The short form is there to separate two explanations of a bad score:
    # a journal is noisy, and a journal is long. Only one of those is fixable
    # by weighting rare words, which this scoring does not do.
    lines_of = data.get("journals") or {}
    journals = {slug: " ".join(lines) for slug, lines in lines_of.items()}
    journals3 = {slug: " ".join(lines[-3:]) for slug, lines in lines_of.items()}
    aimed = traps_for(data, mine)
    traps = sorted(set(aimed.values()))
    # What each entry says it is about, as words. The entity pass of a
    # multi-signal stack, written blind from the lesson alone.
    referents = {slug: words(text) for slug, text in (data.get("referents") or {}).items()}
    filler = [(filler_key(s), s) for s in sentences[: size - len(mine) - len(traps)]]

    def corpus(with_terms: bool) -> list[tuple[str, str, str]]:
        def row(slug: str, body: str) -> tuple[str, str, str]:
            return (slug, body, lesson_terms.get(slug, "") if with_terms else "")

        # The lessons under test are spread evenly through the corpus's ages
        # rather than heaped at one end. An entry the task matches nothing in
        # is ordered newest first, so putting them all oldest or all newest
        # would settle the answer before any arm ran.
        total = len(filler) + len(mine) + len(traps)
        spread = {int(i * total / len(mine)): case for i, case in enumerate(mine)}
        rest = iter([*traps, *filler])
        rows = []
        for age in range(total):
            if age in spread:
                rows.append(row(spread[age].slug, spread[age].lesson))
            else:
                slug, sentence = next(rest)
                rows.append(row(slug, sentence))
        return rows

    def shaped_of(with_terms: bool) -> dict[str, set[str]]:
        """Every entry's matched words, which is body plus terms when it has
        them -- the same text the lookup was given."""
        return {slug: words(f"{body} {terms}") for slug, body, terms in corpus(with_terms)}

    at = Path(tempfile.gettempdir()) / "poieo-recall-eval"
    others = {c.slug: c.lesson for c in mine}
    out: dict[str, Scored] = {}
    bodies = {slug: body for slug, body, _ in corpus(False)}
    vectors: dict[str, list[float]] = {}

    # Two corpora, not one per arm: the arms differ in whether entries carry
    # written terms, and in what the task asks with. Only the first needs a
    # rebuild, and rebuilding is most of what this costs.
    for with_terms in (False, True):
        build(at, corpus(with_terms))
        for arm, needs_terms, widen, scoring in ARMS:
            if needs_terms is not with_terms:
                continue
            if widen == "dense":
                got = embed(list(bodies.values()))
                if got is None:
                    out[arm] = (-1, -1, -1, 0.0, f"no {EMBED_MODEL} on this machine")
                    continue
                vectors = dict(zip(bodies, got))
            # A block from `read_memory` opens with the page and two headers,
            # which is two blank lines before the first entry; the dense arm
            # builds its own block and has none.
            head = 0 if widen == "dense" else 2
            kept = memory_recall._rank
            if scoring:
                memory_recall._rank = patch_ranking(shaped_of(with_terms), referents, scoring)
            found, crowded, sprung, places = 0, 0, 0, []
            for case in mine:
                if widen == "dense":
                    seen = dense_block(case, bodies, vectors)
                else:
                    wider = {"terms": task_terms, "journal": journals, "journal3": journals3}.get(widen, {})
                    seen = block(at, case, wider.get(case.slug, ""))
                if case.lesson in seen:
                    found += 1
                    places.append(seen[: seen.index(case.lesson)].count(BREAK) - head + 1)
                crowded += sum(1 for slug, body in others.items() if slug != case.slug and body in seen)
                sprung += 1 if case.slug in aimed and aimed[case.slug][1] in seen else 0
            memory_recall._rank = kept
            out[arm] = (found, crowded, sprung, sum(places) / len(places) if places else 0.0, "")
    shutil.rmtree(at, ignore_errors=True)
    return {label: out[label] for label, _, _, _ in ARMS if label in out}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-terms", metavar="BINDING", type=Path, help="ask this binding for the terms first")
    args = parser.parse_args()

    if args.write_terms:
        asyncio.run(write_terms(args.write_terms))
        return

    cases, data = load_cases()
    terms = data.get("terms") or {}
    if not terms.get("lesson"):
        print("no terms written yet: run with --write-terms <binding.yaml> first")
        return
    sentences = filler_sentences()

    # Loud, not silent: an arm whose entries have no terms is measuring the
    # baseline while wearing another name.
    want = [filler_key(line) for line in sentences[: max(SIZES)]] + [c.slug for c in cases]
    missing = [key for key in want if key not in terms.get("lesson", {})]
    if missing:
        print(f"{len(missing)} of {len(want)} corpus entries have no written terms.")
        print(f"Run --write-terms before believing any arm but A. First: {missing[0]}")
        print()

    print(f"{len(cases)} cases over {len(sentences)} real sentences from docs/; budget {ENTRIES_BUDGET} characters")
    print("A larger corpus was dropped, not silently capped: every entry needs its own written")
    print(f"terms for the lesson-side arm to be fair, and past {max(SIZES)} that costs more than it settles.\n")

    for kind in KINDS:
        mine = [c for c in cases if c.kind == kind]
        print(f"--- {kind} ({len(mine)} cases) ---")
        aimed = traps_for(data, mine)
        for size in SIZES:
            got = score(kind, size, cases, data, sentences)
            print(f"  {size} entries in memory:")
            for arm, (found, crowded, sprung, deep, note) in got.items():
                if note:
                    print(f"     {arm:<26} skipped: {note}")
                else:
                    # No trap is aimed at a class, no number for it: a bare 0
                    # there would read as an arm keeping look-alikes out.
                    trap = f"{sprung}/{len(mine)}" if aimed else "  n/a"
                    print(
                        f"     {arm:<26} found {found}/{len(mine)}   look-alike shown {trap}"
                        f"   other lessons in the way {crowded}   mean place {deep:.1f}"
                    )
        print()

    print("What each costs, which decides as much as the scores:")
    print("  B  one pass over every existing entry, then one per new entry. Nothing at recall time.")
    print("  C  one pass per task, when it is created or edited. Nothing at recall time.")
    print("  E  an embedding model on the machine. Anthropic has no embeddings endpoint, so a")
    print("     project bound to Claude alone cannot do this without sending its memory elsewhere.")


if __name__ == "__main__":
    # This console defaults to cp949 and the prose in docs/ is full of em dashes.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    main()
