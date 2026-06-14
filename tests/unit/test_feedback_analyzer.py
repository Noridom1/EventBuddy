from eventbuddy.domain.feedback import FeedbackAnalyzer


class _LLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def chat(self, messages, model=None):
        self.calls += 1
        return self.payload


def test_analyze_parses_sentiment_and_themes():
    analyzer = FeedbackAnalyzer(_LLM('{"sentiment": "positive", "themes": ["content", "speaker"]}'))
    sentiment, themes = analyzer.analyze("Great content and speaker!")
    assert sentiment == "positive"
    assert themes == ["content", "speaker"]


def test_analyze_falls_back_on_bad_json():
    sentiment, themes = FeedbackAnalyzer(_LLM("not json")).analyze("meh")
    assert sentiment == "neutral"
    assert themes == []


def test_analyze_coerces_unknown_sentiment():
    sentiment, _ = FeedbackAnalyzer(_LLM('{"sentiment": "ecstatic", "themes": []}')).analyze("x")
    assert sentiment == "neutral"


def test_analyze_skips_llm_on_empty_comment():
    llm = _LLM('{"sentiment": "positive", "themes": []}')
    sentiment, themes = FeedbackAnalyzer(llm).analyze("   ")
    assert (sentiment, themes) == ("neutral", [])
    assert llm.calls == 0  # no LLM round-trip for an empty comment
