from eventbuddy.bot.turn_artifacts import begin_artifacts, emit_card, end_artifacts


def test_emit_card_collects_within_context():
    artifacts, token = begin_artifacts()
    try:
        emit_card({"type": "AdaptiveCard", "id": 1})
        emit_card({"type": "AdaptiveCard", "id": 2})
    finally:
        end_artifacts(token)
    assert [c["id"] for c in artifacts.cards] == [1, 2]


def test_emit_card_is_noop_without_context():
    # Off the request path (e.g. a closure called directly in a unit test) nothing breaks.
    emit_card({"type": "AdaptiveCard"})  # must not raise


def test_turn_artifacts_isolated_across_turns():
    a1, t1 = begin_artifacts()
    emit_card({"id": "a"})
    end_artifacts(t1)
    a2, t2 = begin_artifacts()
    emit_card({"id": "b"})
    end_artifacts(t2)
    assert [c["id"] for c in a1.cards] == ["a"]
    assert [c["id"] for c in a2.cards] == ["b"]  # no bleed between turns
