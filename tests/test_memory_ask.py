"""Ask answers from shortlisted memories and cites only those memories."""

from conftest import remember

from poieo.memory import start_memory
from poieo.memory.ask import ask_memory, fuse
from poieo.providers import LLMResponse, Usage


class Answerer:
    name = "answerer"

    def __init__(self, text):
        self.text = text
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return LLMResponse(
            text=self.text,
            model="answer-model:latest",
            usage=Usage(input_tokens=12, output_tokens=7),
        )


def test_rank_fusion_keeps_word_evidence_ahead_of_semantic_only_matches():
    words = [
        {"slug": "exact", "rank": 1, "mode": "words"},
        {"slug": "both", "rank": 2, "mode": "words"},
    ]
    meaning = [
        {"slug": "semantic", "rank": 1, "mode": "meaning"},
        {"slug": "both", "rank": 2, "mode": "meaning"},
    ]

    assert [row["slug"] for row in fuse(words, meaning)] == ["both", "exact", "semantic"]


async def test_ask_removes_citations_the_model_was_not_given(tmp_path, monkeypatch):
    start_memory(tmp_path)
    remember(tmp_path, "windows-shell", "Windows uses a POSIX shell.")
    remember(tmp_path, "database", "SQLite stores durable memory.")
    answerer = Answerer("Use the POSIX shell [[windows-shell]]. Ignore [[invented]].")

    result = await ask_memory(
        tmp_path,
        "Why does the Windows test fail?",
        answer_provider=answerer,
        answer_model="answer-model",
        answer_params={"temperature": 0},
        embed_provider=None,
        embed_model=None,
        embed_model_key=None,
    )

    assert result["answer"] == "Use the POSIX shell [[windows-shell]]. Ignore ."
    assert result["citations"] == ["windows-shell"]
    assert result["model"] == "answer-model:latest"
    assert result["usage"]["input_tokens"] == 12
    request = answerer.requests[0]
    assert request.role == "memory_searcher"
    assert request.params == {"temperature": 0}
    assert "Windows uses a POSIX shell" in request.messages[0]["content"]
    assert "SQLite stores durable memory" not in request.messages[0]["content"]


async def test_ask_degrades_openly_when_meaning_search_fails(tmp_path):
    start_memory(tmp_path)
    remember(tmp_path, "windows-shell", "Windows shell tests need POSIX.")
    answerer = Answerer("The shell is the cause [[windows-shell]].")

    class BrokenEmbedder:
        name = "broken"

        async def embed(self, model, texts):
            from poieo.errors import ProviderError

            raise ProviderError("offline", provider="broken")

    result = await ask_memory(
        tmp_path,
        "Windows shell",
        answer_provider=answerer,
        answer_model="answer-model",
        answer_params={},
        embed_provider=BrokenEmbedder(),
        embed_model="embed",
        embed_model_key="broken/embed@one",
    )

    assert result["degraded"] == "meaning search was unavailable; the answer used word matches"
    assert result["citations"] == ["windows-shell"]
