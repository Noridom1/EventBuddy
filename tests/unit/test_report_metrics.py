from eventbuddy.domain.reports import compute_metrics


def test_compute_metrics_rates_and_satisfaction():
    m = compute_metrics(
        total_members=10,
        registered=8,
        responses=[
            {"rating": 5, "sentiment": "positive"},
            {"rating": 4, "sentiment": "positive"},
            {"rating": 2, "sentiment": "negative"},
        ],
    )
    assert m["registration_rate"] == 0.8
    assert m["response_rate"] == 0.3
    assert round(m["satisfaction_avg"], 2) == 3.67
    assert m["sentiment_distribution"] == {"positive": 2, "negative": 1}


def test_compute_metrics_handles_no_responses():
    m = compute_metrics(total_members=5, registered=0, responses=[])
    assert m["response_rate"] == 0.0
    assert m["satisfaction_avg"] is None
    assert m["sentiment_distribution"] == {}


def test_compute_metrics_handles_zero_members():
    m = compute_metrics(total_members=0, registered=0, responses=[])
    assert m["registration_rate"] == 0.0
    assert m["response_rate"] == 0.0
