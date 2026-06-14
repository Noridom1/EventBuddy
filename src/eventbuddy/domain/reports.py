"""Report math + report prose (architecture §4, §7.5).

`compute_metrics` is pure aggregation (no LLM); `generate_summary` / `generate_suggestions`
turn the numbers + comments into manager-facing text via the LLM summary model (Qwen)."""
from collections import Counter


def compute_metrics(*, total_members: int, registered: int, responses: list[dict]) -> dict:
    n = len(responses)
    ratings = [r["rating"] for r in responses if r.get("rating") is not None]
    sentiments = [r["sentiment"] for r in responses if r.get("sentiment")]
    return {
        "total_members": total_members,
        "registered": registered,
        "registration_rate": (registered / total_members) if total_members else 0.0,
        "responses": n,
        "response_rate": (n / total_members) if total_members else 0.0,
        "satisfaction_avg": (sum(ratings) / len(ratings)) if ratings else None,
        "sentiment_distribution": dict(Counter(sentiments)),
    }


def generate_summary(llm_gateway, *, metrics: dict, comments: list[str]) -> str:
    instruction = (
        "Summarize event feedback for organizers in 3-4 sentences. "
        "Lead with satisfaction, then the top themes. Be concrete."
    )
    body = f"Metrics: {metrics}\nComments:\n" + "\n".join(f"- {c}" for c in comments)
    return llm_gateway.summarize(body, instruction)


def generate_suggestions(llm_gateway, *, metrics: dict, themes: list[str]) -> str:
    messages = [
        {"role": "system", "content":
         "You are an event-improvement advisor. Based on metrics and feedback themes, "
         "give 3-5 concrete, actionable suggestions for the NEXT event. "
         "Each suggestion ties to a metric or theme. Return a numbered list."},
        {"role": "user", "content": f"Metrics: {metrics}\nThemes: {themes}"},
    ]
    return llm_gateway.chat(messages)
