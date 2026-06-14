from eventbuddy.capabilities.reporting import ReportingService


class _Members:
    def list(self, event_id):
        return [type("M", (), {"registration_status": "registered"})(),
                type("M", (), {"registration_status": "pending"})()]


class _Feedback:
    def list(self, event_id):
        return [type("F", (), {"raw_payload": {"rating": 5, "comment": "great"},
                               "sentiment": "positive", "themes": {"tags": ["content"]}})()]


class _Reports:
    def __init__(self):
        self.created = None

    def create(self, event_id, *, metrics_json, summary_md, suggestions_md):
        self.created = (metrics_json, summary_md, suggestions_md)
        return type("R", (), {"report_id": "r1", "summary_md": summary_md,
                              "suggestions_md": suggestions_md, "metrics_json": metrics_json})()


class _LLM:
    def summarize(self, text, instruction):
        return "SUMMARY"

    def chat(self, messages, model=None):
        return "1. Shorten sessions"


def test_generate_report_computes_persists_and_returns():
    reports = _Reports()
    report = ReportingService(_Members(), _Feedback(), reports, _LLM()).generate(event_id="ev1")
    assert report.summary_md == "SUMMARY"
    assert "Shorten" in report.suggestions_md
    assert reports.created[0]["registration_rate"] == 0.5
    assert reports.created[0]["response_rate"] == 0.5
    assert reports.created[0]["sentiment_distribution"] == {"positive": 1}
