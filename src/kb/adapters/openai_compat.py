"""Adapters génériques compatibles OpenAI : Ollama (local/cloud), Dataiku LLM Mesh, autres."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import OpenAI

_DEFAULT = object()


@dataclass
class Usage:
    """Tokens consommés, cumulés sur la vie de l'adapter (sert au coût par question)."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, input_tokens: int, output_tokens: int) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens


class OpenAICompatLLM:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float | None = 0.0,
        timeout: float = 120.0,
        client: Any = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.usage = Usage()
        self._client = client or OpenAI(
            base_url=base_url, api_key=api_key or "not-needed", timeout=timeout
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any] | None = None,
        temperature: Any = _DEFAULT,
    ) -> str:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        temp = self.temperature if temperature is _DEFAULT else temperature
        if temp is not None:  # None = ne pas envoyer (certains modèles refusent temperature != 1)
            kwargs["temperature"] = temp
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": json_schema},
            }
        resp = self._client.chat.completions.create(**kwargs)
        if resp.usage is not None:  # certains serveurs ne renvoient pas l'usage
            self.usage.add(resp.usage.prompt_tokens or 0, resp.usage.completion_tokens or 0)
        return resp.choices[0].message.content or ""


class OpenAICompatEmbedder:
    def __init__(
        self, base_url: str, api_key: str, model: str, timeout: float = 120.0, client: Any = None
    ) -> None:
        self.model = model
        self.usage = Usage()
        self._client = client or OpenAI(
            base_url=base_url, api_key=api_key or "not-needed", timeout=timeout
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self._client.embeddings.create(model=self.model, input=texts)
        if resp.usage is not None:
            self.usage.add(resp.usage.prompt_tokens or 0, 0)
        return [item.embedding for item in resp.data]
