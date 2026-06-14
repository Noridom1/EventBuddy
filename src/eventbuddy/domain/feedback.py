"""Per-response feedback analysis (architecture §5.4 Feedback capability, §7.5).

Classifies a single free-text comment into a sentiment + a few theme tags via the LLM.
JSON-only prompt with a defensive fallback — a malformed model reply degrades to neutral/[],
never an exception (the report still aggregates whatever it can)."""
import json

ANALYZE_PROMPT = (
    "You classify a single event-feedback comment. Return ONLY JSON: "
    '{"sentiment": "positive|neutral|negative", "themes": [string, ...]}. '
    "Themes are short topic tags (e.g. content, speaker, timing, logistics)."
)


class FeedbackAnalyzer:
    def __init__(self, llm_gateway):
        self.llm = llm_gateway

    def analyze(self, comment: str) -> tuple[str, list[str]]:
        if not comment or not comment.strip():
            return "neutral", []
        raw = self.llm.chat(
            [{"role": "system", "content": ANALYZE_PROMPT},
             {"role": "user", "content": comment}]
        )
        try:
            data = json.loads(raw)
            sentiment = data.get("sentiment", "neutral")
            themes = data.get("themes", [])
            if sentiment not in {"positive", "neutral", "negative"}:
                sentiment = "neutral"
            return sentiment, list(themes)
        except (json.JSONDecodeError, AttributeError, TypeError):
            return "neutral", []
