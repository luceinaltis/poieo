"""Endpoints poieo knows the address of.

Every one of these speaks the OpenAI wire format, so none of them is a new way
of talking -- what a preset saves is the part a person gets wrong. There is no
guessing `https://api.groq.com/openai/v1` from the vendor's name: neither `/v1`
nor `/openai` alone reaches it, and getting it wrong fails without saying which
half was the mistake.

This is why another harness can list thirty-eight providers over three
transports. The thirty-five are names.

**A table here is safe in a way the ones this project refused are not.** A stale
price inflates a bill quietly and a stale context window truncates a
conversation quietly; a stale address fails to connect, loudly, on the first
call. Only tables that are wrong in silence are dangerous.

Each address below was probed against the live endpoint when it was written.
Two of them are the reason that sentence is worth reading: Gemini and Perplexity
answer 404 on `/models` and 400/401 on `/chat/completions`, so a probe that only
asked the first would have declared two correct addresses wrong.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Preset:
    """Where an endpoint lives and which variable holds its key."""

    base_url: str
    api_key_env: str


PRESETS: dict[str, Preset] = {
    "openai": Preset("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "openrouter": Preset("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "groq": Preset("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "deepseek": Preset("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "together": Preset("https://api.together.xyz/v1", "TOGETHER_API_KEY"),
    "fireworks": Preset("https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY"),
    "mistral": Preset("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "xai": Preset("https://api.x.ai/v1", "XAI_API_KEY"),
    "cerebras": Preset("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "nebius": Preset("https://api.studio.nebius.ai/v1", "NEBIUS_API_KEY"),
    "moonshot": Preset("https://api.moonshot.cn/v1", "MOONSHOT_API_KEY"),
    "zai": Preset("https://api.z.ai/api/paas/v4", "ZAI_API_KEY"),
    # No `/models` route on either of these; both were verified by asking
    # `/chat/completions` instead.
    "gemini": Preset("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "perplexity": Preset("https://api.perplexity.ai", "PERPLEXITY_API_KEY"),
}
