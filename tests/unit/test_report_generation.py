from eventbuddy.domain.reports import generate_suggestions, generate_summary


class _LLM:
    def __init__(self):
        self.calls = []

    def summarize(self, text, instruction):
        self.calls.append(("summarize", text, instruction))
        return "SUMMARY"

    def chat(self, messages, model=None):
        self.calls.append(("chat", messages))
        return "1. Shorten sessions\n2. More Q&A"


def test_generate_summary_uses_summary_model():
    llm = _LLM()
    out = generate_summary(llm, metrics={"satisfaction_avg": 4.2}, comments=["great", "long"])
    assert out == "SUMMARY"
    assert llm.calls and llm.calls[0][0] == "summarize"


def test_generate_suggestions_returns_text():
    out = generate_suggestions(_LLM(), metrics={"response_rate": 0.6}, themes=["timing", "qa"])
    assert "Shorten" in out
