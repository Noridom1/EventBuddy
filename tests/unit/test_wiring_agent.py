from eventbuddy.agent import wiring


def test_build_orchestrator_degrades_to_regex_without_creds(monkeypatch):
    monkeypatch.setattr(wiring.settings, "agentbase_llm_base_url", "")
    monkeypatch.setattr(wiring.settings, "agentbase_llm_api_key", "")
    monkeypatch.setattr(wiring.settings, "agent_mode", "llm")

    orch = wiring.build_orchestrator()

    assert orch.runner is None
    assert orch.agent_mode == "regex"
    # regex path answers without touching the runner (small-talk needs no DB/Redis)
    out = orch.handle(user_id="u1", channel_id=None, text="hello there")
    assert out.startswith("Hi! Try:")


def test_build_summarizer_none_without_creds(monkeypatch):
    monkeypatch.setattr(wiring.settings, "agentbase_llm_base_url", "")
    assert wiring.build_summarizer() is None
