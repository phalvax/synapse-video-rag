"""Tests des adapters sans réseau : on remplace le client OpenAI par un faux."""

from types import SimpleNamespace

from kb.adapters.openai_compat import OpenAICompatEmbedder, OpenAICompatLLM


class FakeCompletions:
    def __init__(self) -> None:
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=7),
        )


def _llm(temperature):
    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = OpenAICompatLLM("http://x", "k", "m", temperature=temperature, client=client)
    return llm, completions


def test_temperature_none_is_not_sent():
    llm, fake = _llm(None)
    llm.complete([{"role": "user", "content": "hi"}])
    assert "temperature" not in fake.kwargs


def test_temperature_zero_is_sent_and_usage_is_counted():
    llm, fake = _llm(0.0)
    assert llm.complete([{"role": "user", "content": "hi"}], json_schema={"type": "object"}) == "OK"
    assert fake.kwargs["temperature"] == 0.0
    assert fake.kwargs["response_format"]["type"] == "json_schema"
    llm.complete([{"role": "user", "content": "hi"}])
    assert (llm.usage.calls, llm.usage.input_tokens, llm.usage.output_tokens) == (2, 200, 14)


def test_embedder_returns_vectors():
    resp = SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1, 0.2])], usage=SimpleNamespace(prompt_tokens=3)
    )
    client = SimpleNamespace(embeddings=SimpleNamespace(create=lambda **_: resp))
    emb = OpenAICompatEmbedder("http://x", "k", "m", client=client)
    assert emb.embed(["a"]) == [[0.1, 0.2]]
    assert emb.embed([]) == []
    assert emb.usage.input_tokens == 3
