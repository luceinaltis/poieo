"""Corpora for tools/recall_eval.py: the hand-written cases, and three sets
nobody here wrote.

Every number the harness produced so far came from thirty tasks and ten
look-alikes written by the same hands, with terms, referents and verdicts from
the same model family. That ordering may be real or may be an artefact of cases
shaped to produce it. These adapters put the same arms, unchanged, on data with
no hand in it -- each chosen for a different claim:

  entity       Entity-Collision (arXiv:2605.29630). K facts per entity that
               differ only in one discriminator, and a query that paraphrases
               it. The look-alike, in its purest synthetic form.
  longmemeval  LongMemEval-S (ICLR 2025). The field's yardstick for agent
               memory: real conversations, evidence marked per turn.
  scifact      BEIR SciFact. Neutral retrieval, to tell "this is retrieval"
               from "this is my test set".

None is lesson-shaped like this project (task -> rule), and the output says so.
Data lands in a temp folder, never in the repository; LongMemEval text is a
third party's. Generated inputs for these corpora are cached beside the data,
keyed by content, and are not checked in either.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATA = Path(tempfile.gettempdir()) / "poieo-bench" / "data"
HERE = Path(__file__).resolve().parent


@dataclass
class Case:
    slug: str
    kind: str
    name: str
    prompt: str
    lesson: str


Row = tuple[str, str, str]  # slug, body, written terms


class Corpus:
    """What the harness asks of a corpus. The hand-written cases are one;
    each external set is another, and the arms cannot tell them apart."""

    name = ""
    store: Path  # where generated inputs (terms, referents, verdicts) live
    cut: int | None = None  # None: the character budget; N: top-N by rank
    shared_rows = True  # rows identical across the cases of one (kind, size)
    journals = False
    blurb = ""

    def kinds(self) -> list[str]:
        raise NotImplementedError

    def cases(self, kind: str) -> list[Case]:
        raise NotImplementedError

    def sizes(self, kind: str) -> list[int]:
        raise NotImplementedError

    def rows(
        self, kind: str, size: int, case: Case | None, lesson_terms: dict[str, str], with_terms: bool
    ) -> list[Row]:
        raise NotImplementedError

    def aimed(self, kind: str) -> dict[str, tuple[str, str]]:
        """The look-alike aimed at each task, by task slug: (id, body)."""
        return {}

    def lesson_groups(self) -> list[list[tuple[str, str]]]:
        """Entries to write terms for, grouped so no batch holds two wordings
        of one thing."""
        raise NotImplementedError

    def tasks(self) -> list[tuple[str, str]]:
        return [(c.slug, f"{c.name}: {c.prompt}".strip(": ")) for k in self.kinds() for c in self.cases(k)]

    def anchor(self, kind: str, label: str) -> str | None:
        """A number from outside to stand this arm beside, when one exists."""
        return None

    def load_store(self) -> dict[str, Any]:
        if self.store.exists():
            return json.loads(self.store.read_text(encoding="utf-8"))
        return {}

    def save_store(self, data: dict[str, Any]) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _key(prefix: str, text: str) -> str:
    return prefix + hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _clean(slug: str) -> str:
    """An entry name the memory will take: lowercase letters, digits, dashes.
    A LongMemEval question id carries an underscore, and the judge died on the
    first of those a quarter of the way in."""
    return re.sub(r"[^a-z0-9-]", "-", slug.lower())


# -- Entity-Collision ---------------------------------------------------------


class EntityCollision(Corpus):
    """The protocol's own construction, from its vendored vocabulary: eight
    entities, K facts each per tag, three easy distractors per entity, seed 42.
    One kind per K, all five tags together.

    The paper's keyword floor is 1/K -- the entity token picks one of K facts
    at random and the discriminator is paraphrased away -- so arm A is expected
    near that, and the number is printed beside it.
    """

    name = "entity"
    cut = None
    store = DATA / "entity.store.json"
    blurb = (
        "Entity-Collision: K facts per entity differing in one word, and a query that\n"
        "paraphrases that word. Synthetic and small; the look-alike in its purest form."
    )
    K = (1, 2, 4, 8)

    def __init__(self) -> None:
        vocab = json.loads((HERE / "recall_eval_entity.json").read_text(encoding="utf-8"))
        self._built: dict[str, tuple[list[Case], list[Row], dict[str, tuple[str, str]]]] = {}
        for k in self.K:
            self._built[f"K={k}"] = self._generate(vocab, k)

    @staticmethod
    def _generate(vocab: dict, k: int) -> tuple[list[Case], list[Row], dict[str, tuple[str, str]]]:
        rng = random.Random(42)
        cases: list[Case] = []
        rows: list[Row] = []
        aimed: dict[str, tuple[str, str]] = {}
        for tag, spec in vocab["specs"].items():
            for entity in vocab["entities"][:8]:
                discs = rng.sample(spec["discs"], k)
                facts = [
                    (d, syn, ans, spec["memory"].format(entity=entity, disc=d, answer=ans)) for d, syn, ans in discs
                ]
                for i, (disc, syn, _, memory) in enumerate(facts):
                    slug = _key(f"ec-{k}-", memory)
                    rows.append((slug, memory, ""))
                    query = spec["query"].format(entity=entity, disc_syn=syn)
                    case = Case(f"q-{slug}", f"K={k}", "", query, memory)
                    cases.append(case)
                    if k > 1:
                        other = facts[(i + 1) % k][3]
                        aimed[case.slug] = (_key(f"ec-{k}-", other), other)
                for _ in range(3):
                    d = f"{rng.choice(vocab['distractors'])} (n{rng.randint(0, 99999)})"
                    rows.append((_key(f"ec-{k}-", d), d, ""))
        rng.shuffle(rows)
        return cases, rows, aimed

    def kinds(self) -> list[str]:
        return list(self._built)

    def cases(self, kind: str) -> list[Case]:
        return self._built[kind][0]

    def sizes(self, kind: str) -> list[int]:
        return [len(self._built[kind][1])]

    def rows(self, kind, size, case, lesson_terms, with_terms):
        return [(s, b, lesson_terms.get(s, "") if with_terms else "") for s, b, _ in self._built[kind][1]]

    def aimed(self, kind: str) -> dict[str, tuple[str, str]]:
        return self._built[kind][2]

    def lesson_groups(self) -> list[list[tuple[str, str]]]:
        # One group per K. The twin rule -- never two wordings of one thing in
        # a batch -- is not broken here: an entity's K facts are K different
        # things, and a model writing terms for "prefers JSON logs when
        # debugging" reaching for "troubleshooting" is the mechanism under
        # test, not a leak of it.
        return [[(slug, body) for slug, body, _ in rows] for _, rows, _ in self._built.values()]

    def anchor(self, kind: str, label: str) -> str | None:
        if label.startswith("A"):
            k = int(kind.split("=")[1])
            return f"the paper's keyword floor is 1/K = {1 / k:.2f}"
        return None


# -- LongMemEval --------------------------------------------------------------


class LongMemEval(Corpus):
    """LongMemEval-S, a stratified hundred of its five hundred questions. Each
    question is its own corpus: every turn of its haystack, both roles, capped
    at 500 characters so an entry stays entry-sized. The task is the question;
    the lesson is the first turn marked as evidence; the look-alike is the
    longest unmarked turn of the same session -- same context, wrong line.

    Arms that need written terms for every entry run on the first two
    questions of each type only: a hundred questions is fifty thousand turns,
    and that is more model output than the answer is worth. The harness prints
    how many questions each arm covered.
    """

    name = "longmemeval"
    cut = None
    shared_rows = False
    store = DATA / "longmemeval.store.json"
    blurb = (
        "LongMemEval-S: real conversations, evidence marked per turn. A hundred questions,\n"
        "each its own haystack of ~500 turns. Question -> turn, not task -> rule."
    )
    PER_TYPE = 17
    TERMS_PER_TYPE = 2
    CAP = 500

    def __init__(self) -> None:
        path = DATA / "longmemeval_s_cleaned.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        by_type: dict[str, list[dict]] = {}
        for q in sorted(raw, key=lambda q: str(q["question_id"])):
            if str(q["question_id"]).endswith("_abs"):
                continue  # abstention questions have no evidence to find
            by_type.setdefault(q["question_type"], []).append(q)
        self._cases: dict[str, list[Case]] = {}
        self._rows: dict[str, list[Row]] = {}
        self._aimed: dict[str, dict[str, tuple[str, str]]] = {}
        self._with_terms: set[str] = set()
        for kind, qs in sorted(by_type.items()):
            step = max(1, len(qs) // self.PER_TYPE)
            picked = qs[::step][: self.PER_TYPE]
            self._cases[kind] = []
            self._aimed[kind] = {}
            for n, q in enumerate(picked):
                slug = _clean(f"lme-{q['question_id']}")
                rows, gold, trap = self._turns(q, slug)
                if gold is None:
                    continue
                self._cases[kind].append(Case(slug, kind, "", q["question"], gold))
                self._rows[slug] = rows
                if trap:
                    self._aimed[kind][slug] = trap
                if n < self.TERMS_PER_TYPE:
                    self._with_terms.add(slug)

    def _turns(self, q: dict, slug: str) -> tuple[list[Row], str | None, tuple[str, str] | None]:
        rows: list[Row] = []
        gold: str | None = None
        gold_session = -1
        for s, session in enumerate(q["haystack_sessions"]):
            for t, turn in enumerate(session):
                body = " ".join(turn["content"].split())[: self.CAP]
                if not body:
                    continue
                rows.append((f"{slug}-{s}-{t}", body, ""))
                if turn.get("has_answer") and gold is None:
                    gold, gold_session = body, s
        trap = None
        if gold is not None:
            others = [
                (f"{slug}-{gold_session}-{t}", " ".join(turn["content"].split())[: self.CAP])
                for t, turn in enumerate(q["haystack_sessions"][gold_session])
                if not turn.get("has_answer")
            ]
            if others:
                trap = max(others, key=lambda pair: len(pair[1]))
        return rows, gold, trap

    def load_store(self) -> dict[str, Any]:
        # Terms and referents were written under the unclean names; read them
        # back under the clean ones so nothing generated is lost to a dash.
        data = super().load_store()
        for table in (data.get("terms") or {}).values():
            for key in list(table):
                table[_clean(key)] = table.pop(key)
        for key in list(data.get("referents") or {}):
            data["referents"][_clean(key)] = data["referents"].pop(key)
        return data

    def kinds(self) -> list[str]:
        return list(self._cases)

    def cases(self, kind: str) -> list[Case]:
        return self._cases[kind]

    def sizes(self, kind: str) -> list[int]:
        return [0]  # per question; the label is printed as such

    def rows(self, kind, size, case, lesson_terms, with_terms):
        assert case is not None
        return [(s, b, lesson_terms.get(s, "") if with_terms else "") for s, b, _ in self._rows[case.slug]]

    def aimed(self, kind: str) -> dict[str, tuple[str, str]]:
        return self._aimed[kind]

    def lesson_groups(self) -> list[list[tuple[str, str]]]:
        # One group per question, and only the questions that get terms.
        return [[(s, b) for s, b, _ in self._rows[slug]] for slug in sorted(self._with_terms)]

    def anchor(self, kind: str, label: str) -> str | None:
        return None


# -- BEIR SciFact -------------------------------------------------------------


class SciFact(Corpus):
    """BEIR SciFact test split: 300 claims, each with the abstract(s) that
    support or refute it. Abstracts run to 1,500 characters, so the character
    budget would show two or three and mean nothing; this corpus is cut at the
    top ten by rank instead. The corpus is every judged abstract plus enough
    hard negatives -- the abstracts sharing the most words with some claim --
    to reach a thousand, so per-entry generation stays affordable.

    BEIR reports BM25 nDCG@10 of about 0.665 here; the rarer-words arm is the
    nearest thing to BM25 in this harness and is printed beside that number.
    """

    name = "scifact"
    cut = 10
    store = DATA / "scifact.store.json"
    blurb = "BEIR SciFact: claims against paper abstracts. Neutral retrieval, cut at top ten."
    SIZE = 1000

    def __init__(self) -> None:
        from poieo.memory.entries import words

        base = DATA / "scifact"
        docs = {}
        for line in (base / "corpus.jsonl").read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            # Capped so that "room for ten entries" is a fixed number of
            # characters; the tail of a long abstract is what goes. 217 of the
            # 5,183 abstracts run past it, about four in a hundred.
            docs[str(d["_id"])] = f"{d.get('title', '').strip()}. {d['text'].strip()}".strip(". ")[:2500]
        queries = {}
        for line in (base / "queries.jsonl").read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            queries[str(d["_id"])] = d["text"]
        golds: dict[str, list[str]] = {}
        for line in (base / "qrels" / "test.tsv").read_text(encoding="utf-8").splitlines()[1:]:
            qid, did, score = line.split("\t")
            if int(score) > 0:
                golds.setdefault(qid, []).append(did)

        keep: dict[str, str] = {did: docs[did] for ds in golds.values() for did in ds}
        # Hard negatives: for each claim, the non-gold abstracts sharing the
        # most distinctive words with it, until the corpus is full.
        shaped = {did: words(text) for did, text in docs.items()}
        freq: Counter = Counter(w for ws in shaped.values() for w in ws)
        for qid in sorted(golds):
            if len(keep) >= self.SIZE:
                break
            q = words(queries[qid])
            ranked = sorted(
                (did for did in docs if did not in keep),
                key=lambda did: -sum(1.0 / freq[w] for w in q & shaped[did]),
            )
            for did in ranked[:3]:
                keep[did] = docs[did]
                if len(keep) >= self.SIZE:
                    break

        self._rows: list[Row] = [(f"sf-{did}", text, "") for did, text in sorted(keep.items())]
        self._cases = [
            Case(f"claim-{qid}", "claims", "", queries[qid], docs[ds[0]]) for qid, ds in sorted(golds.items())
        ]
        self._extra_gold = {f"claim-{qid}": [docs[d] for d in ds[1:]] for qid, ds in golds.items()}

    def kinds(self) -> list[str]:
        return ["claims"]

    def cases(self, kind: str) -> list[Case]:
        return self._cases

    def sizes(self, kind: str) -> list[int]:
        return [len(self._rows)]

    def rows(self, kind, size, case, lesson_terms, with_terms):
        return [(s, b, lesson_terms.get(s, "") if with_terms else "") for s, b, _ in self._rows]

    def lesson_groups(self) -> list[list[tuple[str, str]]]:
        rows = [(s, b) for s, b, _ in self._rows]
        return [rows[at : at + 30] for at in range(0, len(rows), 30)]

    def anchor(self, kind: str, label: str) -> str | None:
        if label.startswith("I"):
            return "BEIR's BM25 on SciFact scores nDCG@10 ~0.665; this column is recall@10"
        return None


def corpus_named(name: str) -> Corpus:
    if name == "entity":
        return EntityCollision()
    if name == "longmemeval":
        return LongMemEval()
    if name == "scifact":
        return SciFact()
    raise SystemExit(f"no corpus called {name!r}")
