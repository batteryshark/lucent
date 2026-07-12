"""Review-model configuration — any OpenAI- or Anthropic-compatible endpoint.

The reviewer talks to whatever endpoint you point it at: a local server (LM Studio, Ollama,
llama.cpp), OpenAI, Anthropic, or a compatible gateway. Resolution is env-first so the core
stays self-contained; pydantic-ai is an optional dependency (``lucent[review]``). This mirrors
unmask's ``reviewers/config.py`` with a ``LUCENT_REVIEW_*`` namespace.

    LUCENT_REVIEW_PROVIDER   preset (lmstudio|openai|anthropic) or "custom"
    LUCENT_REVIEW_MODEL      model id (required)
    LUCENT_REVIEW_BASE_URL   overrides the preset base_url
    LUCENT_REVIEW_API_KEY    api key (or the preset's own env var)
    LUCENT_REVIEW_KIND       wire protocol: "openai" (default) or "anthropic"
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ReviewConfigError(RuntimeError):
    """Raised when the review model is requested but not configured/available."""


_PRESETS = {
    "lmstudio": {"base_url": "http://localhost:1234/v1", "api_key_env": "LUCENT_REVIEW_API_KEY", "kind": "openai"},
    "ollama": {"base_url": "http://localhost:11434/v1", "api_key_env": "LUCENT_REVIEW_API_KEY", "kind": "openai"},
    "openai": {"base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY", "kind": "openai"},
    "anthropic": {"base_url": "https://api.anthropic.com", "api_key_env": "ANTHROPIC_API_KEY", "kind": "anthropic"},
}


@dataclass
class ReviewModelConfig:
    model: str
    base_url: str
    api_key: str | None
    provider: str
    kind: str = "openai"

    @classmethod
    def from_spec(cls, spec: str | None, **kw) -> "ReviewModelConfig":
        """Resolve a ``[provider:]model_id`` spec (``lmstudio:qwen2.5``, ``gpt-4o``), falling
        back to env for base_url/api_key. ``spec=None`` is pure env resolution."""
        if not spec:
            return cls.from_env(**kw)
        provider, sep, model = spec.partition(":")
        if sep and model:
            return cls.from_env(provider=provider, model=model, **kw)
        return cls.from_env(model=provider, **kw)

    @classmethod
    def from_env(cls, *, model=None, base_url=None, api_key=None, provider=None) -> "ReviewModelConfig":
        provider = provider or os.environ.get("LUCENT_REVIEW_PROVIDER", "custom")
        model = model or os.environ.get("LUCENT_REVIEW_MODEL")
        base_url = base_url or os.environ.get("LUCENT_REVIEW_BASE_URL")
        api_key = api_key or os.environ.get("LUCENT_REVIEW_API_KEY")
        preset = _PRESETS.get(provider)
        if preset:
            base_url = base_url or preset["base_url"]
            if not api_key:
                api_key = os.environ.get(preset["api_key_env"] or "")
        kind = os.environ.get("LUCENT_REVIEW_KIND") or (preset.get("kind") if preset else None) or "openai"
        if not model:
            raise ReviewConfigError(
                "no review model configured — set LUCENT_REVIEW_MODEL (and a base_url via "
                "LUCENT_REVIEW_BASE_URL or LUCENT_REVIEW_PROVIDER=lmstudio|ollama|openai|anthropic).")
        if not base_url:
            raise ReviewConfigError(
                f"no base_url for review model {model!r} — set LUCENT_REVIEW_BASE_URL or a known "
                "LUCENT_REVIEW_PROVIDER.")
        return cls(model=model, base_url=base_url, api_key=api_key, provider=provider, kind=kind)

    def build_model(self):
        """Construct the pydantic-ai model — Anthropic ``messages`` or OpenAI chat-completions
        per ``kind``. Both take a base_url + api_key, so any compatible endpoint works."""
        try:
            if self.kind == "anthropic":
                from pydantic_ai.models.anthropic import AnthropicModel
                from pydantic_ai.providers.anthropic import AnthropicProvider
                provider = AnthropicProvider(base_url=self.base_url, api_key=self.api_key or "not-needed")
                return AnthropicModel(self.model, provider=provider)
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider
            provider = OpenAIProvider(base_url=self.base_url, api_key=self.api_key or "not-needed")
            return OpenAIChatModel(self.model, provider=provider)
        except ImportError as e:  # pragma: no cover
            raise ReviewConfigError("agentic review needs `pip install lucent[review]`") from e
