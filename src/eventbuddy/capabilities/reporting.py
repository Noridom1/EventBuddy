from eventbuddy.domain.reports import compute_metrics, generate_suggestions, generate_summary


class ReportingService:
    """Capability ⑥ — Auto Report + Suggestions (architecture §4, §7.5). Composes pure
    metrics + an LLM summary + LLM next-event suggestions, then persists a `Report`."""

    def __init__(self, member_repo, feedback_repo, report_repo, llm_gateway):
        self.members = member_repo
        self.feedback = feedback_repo
        self.reports = report_repo
        self.llm = llm_gateway

    def generate(self, *, event_id: str):
        members = self.members.list(event_id)
        responses = self.feedback.list(event_id)

        total = len(members)
        registered = sum(1 for m in members if m.registration_status == "registered")
        resp_dicts = [
            {"rating": (r.raw_payload or {}).get("rating"), "sentiment": r.sentiment}
            for r in responses
        ]
        metrics = compute_metrics(total_members=total, registered=registered, responses=resp_dicts)

        comments = [
            (r.raw_payload or {}).get("comment", "") for r in responses if r.raw_payload
        ]
        themes = sorted({
            t for r in responses if r.themes
            for t in (r.themes.get("tags", []) if isinstance(r.themes, dict) else [])
        })

        summary = generate_summary(self.llm, metrics=metrics, comments=comments)
        suggestions = generate_suggestions(self.llm, metrics=metrics, themes=themes)

        return self.reports.create(event_id, metrics_json=metrics,
                                   summary_md=summary, suggestions_md=suggestions)
