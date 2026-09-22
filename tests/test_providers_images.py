"""A picture in the conversation, said once and carried to every backend.

A message's `content` is either a string or a list of blocks: `{"type":
"text", "text"}` and `{"type": "image", "media_type", "data"}`, the data in
base64. Each backend is handed the picture in its own wire shape; one that
cannot see pictures refuses rather than dropping it, because a model told
about a screenshot it was never shown answers about nothing.
"""

from __future__ import annotations

import pytest

from poieo.errors import ProviderError
from poieo.providers.anthropic_provider import _anthropic_messages
from poieo.providers.base import LLMRequest
from poieo.providers.local import _ollama_messages, _openai_messages
from poieo.providers.subscription import _last_user_message
from poieo.providers.typesafe import _state
from poieo.runtime.nodes import _conversation_size, _transcript

PIXEL = "iVBORw0KGgo="
LOOK = [
    {"type": "text", "text": "what is this?"},
    {"type": "image", "media_type": "image/png", "data": PIXEL},
]
CALLED = {
    "role": "assistant",
    "content": "",
    "tool_calls": [{"id": "c1", "name": "view_image", "arguments": {"path": "a.png"}}],
}
SEEN = {
    "role": "tool",
    "tool_call_id": "c1",
    "content": [
        {"type": "text", "text": "a.png, 1 KB"},
        {"type": "image", "media_type": "image/png", "data": PIXEL},
    ],
}


def test_anthropic_gets_the_picture_as_a_base64_image_block():
    [turn] = _anthropic_messages([{"role": "user", "content": LOOK}])

    assert turn == {
        "role": "user",
        "content": [
            {"type": "text", "text": "what is this?"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PIXEL}},
        ],
    }


def test_anthropic_carries_a_picture_a_tool_returned_inside_its_result():
    turns = _anthropic_messages([{"role": "user", "content": "look at a.png"}, CALLED, SEEN])

    result = turns[-1]["content"][0]
    assert result["type"] == "tool_result"
    assert result["content"] == [
        {"type": "text", "text": "a.png, 1 KB"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PIXEL}},
    ]


def test_anthropic_folds_a_picture_said_after_tool_results_into_that_turn():
    turns = _anthropic_messages(
        [
            {"role": "user", "content": "go"},
            CALLED,
            {"role": "tool", "tool_call_id": "c1", "content": "done"},
            {"role": "user", "content": LOOK},
        ]
    )

    assert [turn["role"] for turn in turns] == ["user", "assistant", "user"]
    assert turns[-1]["content"][-1]["type"] == "image"
    assert turns[-1]["content"][-2] == {"type": "text", "text": "what is this?"}


def test_an_openai_shaped_endpoint_gets_the_picture_as_a_data_url():
    messages = _openai_messages(LLMRequest(model="m", messages=[{"role": "user", "content": LOOK}]))

    assert messages == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "what is this?"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PIXEL}"}},
            ],
        }
    ]


def test_an_openai_shaped_endpoint_sees_a_tools_picture_right_after_the_results():
    """This API takes only text in a tool message, so the picture follows the
    turn's results as the next user message -- after all of them, because a
    user message between two results would orphan the second."""
    second = {"role": "tool", "tool_call_id": "c2", "content": "ok"}
    called = {**CALLED, "tool_calls": [*CALLED["tool_calls"], {"id": "c2", "name": "list_dir", "arguments": {}}]}
    messages = _openai_messages(
        LLMRequest(model="m", messages=[{"role": "user", "content": "go"}, called, SEEN, second])
    )

    assert [message["role"] for message in messages] == ["user", "assistant", "tool", "tool", "user"]
    assert messages[2] == {"role": "tool", "tool_call_id": "c1", "content": "a.png, 1 KB"}
    assert messages[-1]["content"] == [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PIXEL}"}},
    ]


def test_ollama_gets_the_text_as_content_and_the_picture_beside_it():
    request = LLMRequest(model="m", messages=[{"role": "user", "content": LOOK}, CALLED, SEEN])
    messages = _ollama_messages(request)

    assert messages[0] == {"role": "user", "content": "what is this?", "images": [PIXEL]}
    assert messages[2] == {"role": "tool", "tool_call_id": "c1", "content": "a.png, 1 KB", "images": [PIXEL]}


def test_plain_text_is_sent_exactly_as_before():
    history = [{"role": "user", "content": "hi"}]

    assert _openai_messages(LLMRequest(model="m", messages=history)) == history
    assert _ollama_messages(LLMRequest(model="m", messages=history)) == history
    assert _anthropic_messages(history) == history


def test_a_harness_is_handed_text_blocks_as_text_and_refuses_a_picture():
    words = [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]
    assert _last_user_message(LLMRequest(model="m", messages=[{"role": "user", "content": words}]), "cc") == (
        "first\n\nsecond"
    )

    with pytest.raises(ProviderError, match="cannot be shown a picture"):
        _last_user_message(LLMRequest(model="m", messages=[{"role": "user", "content": LOOK}]), "cc")


def test_a_model_that_only_decides_refuses_a_picture():
    with pytest.raises(ProviderError, match="cannot be shown a picture"):
        _state("jev", LLMRequest(model="m", messages=[{"role": "user", "content": LOOK}]))


def test_a_picture_weighs_what_it_costs_a_model_not_the_length_of_its_bytes():
    big = "A" * 2_000_000
    pictured = [{"role": "user", "content": [{"type": "image", "media_type": "image/png", "data": big}]}]
    worded = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]

    assert 0 < _conversation_size(pictured) < 20_000
    assert _conversation_size(worded) == len("hello")


def test_a_folded_history_mentions_the_picture_without_its_bytes():
    folded = _transcript([{"role": "user", "content": LOOK}, CALLED, SEEN])

    assert PIXEL not in folded
    assert "user: what is this? [image]" in folded
    assert "the tool answered: a.png, 1 KB [image]" in folded


def test_clearing_reaches_a_tool_result_that_carries_a_picture():
    """A picture a tool returned is resent every turn like any result, so the
    room-saving that empties old results must be able to empty it too."""
    from poieo.runtime.nodes import _CLEARED, _KEEP_RESULTS, _TOO_BIG, _clear_old_results, _drop_newest_result

    newer = [{"role": "tool", "tool_call_id": f"n{i}", "content": "ok"} for i in range(_KEEP_RESULTS)]
    messages = [{"role": "user", "content": "go"}, CALLED, SEEN, *newer]
    freed = _clear_old_results(messages)

    assert messages[2]["content"] == _CLEARED
    assert freed == _conversation_size([SEEN]) - len(_CLEARED)

    messages = [{"role": "user", "content": "go"}, CALLED, SEEN]
    assert _drop_newest_result(messages) > 0
    assert messages[-1]["content"] == _TOO_BIG
