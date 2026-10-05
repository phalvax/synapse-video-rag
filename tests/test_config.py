from kb.config import load_settings


def test_all_profiles_load(monkeypatch):
    for name in ("free", "dataiku", "market"):
        s = load_settings(name)
        assert s.profile == name
        assert s.llm.base_url and s.llm.model


def test_env_overrides_profile(monkeypatch):
    monkeypatch.setenv("OLLAMA_LLM_MODEL", "gemma-test")
    assert load_settings("free").llm.model == "gemma-test"


def test_pricing_defaults(monkeypatch):
    monkeypatch.delenv("DSS_LLM_INPUT_PER_M", raising=False)
    monkeypatch.delenv("DSS_LLM_OUTPUT_PER_M", raising=False)
    assert load_settings("free").llm.input_per_m == 0
    dku = load_settings("dataiku")
    assert (dku.llm.input_per_m, dku.llm.output_per_m) == (0.2, 1.2)  # Luna
    assert dku.llm.temperature is None


def test_dataiku_url_is_built_from_env(monkeypatch):
    monkeypatch.setenv("DSS_URL", "https://dss.example")
    monkeypatch.setenv("DSS_PROJECT_KEY", "TEAM_16")
    url = load_settings("dataiku").llm.base_url
    assert url == "https://dss.example/public/api/projects/TEAM_16/llms/openai/v1/"
