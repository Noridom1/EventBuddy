"""Coalescing the turn's per-recipient `teams_dm` confirm cards into one (UX belt-and-suspenders
over the batch `send_teams_message` tool). Uses the real `confirm_card` builder + an in-memory
pending store, so it exercises the actual merge/store/supersede path."""
from eventbuddy.agent.wiring import _card_action_data, coalesce_teams_dm_cards
from eventbuddy.bot.cards.builders import confirm_card, personalized_dm_card


class _MemStore:
    """Minimal PendingActionStore stand-in: put/get/pop over a dict, monotonically-ided."""

    def __init__(self):
        self.data = {}
        self._n = 0

    def put(self, payload):
        self._n += 1
        pid = f"p{self._n}"
        self.data[pid] = payload
        return pid

    def get(self, pid):
        return self.data.get(pid)

    def pop(self, pid):
        return self.data.pop(pid, None)


def _dm_card(store, *, targets, text, group=""):
    """Build a teams_dm confirm card backed by a freshly stored pending (as the closure does)."""
    pid = store.put({"type": "teams_dm", "targets": targets, "text": text, "group": group})
    displays = [t["display"] for t in targets]
    return confirm_card(title="Send Teams message", summary="x", pending_id=pid,
                        action="teams_dm", recipients=displays, body=text)


def _run(store, cards):
    return coalesce_teams_dm_cards(cards, pending_store=store, confirm_card_fn=confirm_card,
                                   personalized_card_fn=personalized_dm_card)


def test_single_dm_card_passes_through_unchanged():
    store = _MemStore()
    card = _dm_card(store, targets=[{"user_id": "u-1", "display": "Anh"}], text="hi")
    out = _run(store, [card])
    assert out == [card]  # untouched
    assert len(store.data) == 1  # pending not disturbed


def test_multiple_dm_cards_same_text_merge_into_one():
    store = _MemStore()
    c1 = _dm_card(store, targets=[{"user_id": "u-1", "display": "Anh"}], text="when home?")
    c2 = _dm_card(store, targets=[{"user_id": "u-2", "display": "Lam"}], text="when home?")
    c3 = _dm_card(store, targets=[{"user_id": "u-3", "display": "Phuc"}], text="when home?")
    out = _run(store, [c1, c2, c3])

    assert len(out) == 1
    data = _card_action_data(out[0])
    assert data["action"] == "teams_dm"
    merged = store.get(data["pending_id"])
    assert [t["user_id"] for t in merged["targets"]] == ["u-1", "u-2", "u-3"]
    assert merged["text"] == "when home?"
    # the three per-recipient pendings were superseded (popped); only the merged one remains
    assert list(store.data.keys()) == [data["pending_id"]]


def test_merged_card_dedupes_targets_by_user_id():
    store = _MemStore()
    c1 = _dm_card(store, targets=[{"user_id": "u-1", "display": "Anh"}], text="hi")
    c2 = _dm_card(store, targets=[{"user_id": "u-1", "display": "Anh"}], text="hi")
    out = _run(store, [c1, c2])
    assert len(out) == 1
    merged = store.get(_card_action_data(out[0])["pending_id"])
    assert [t["user_id"] for t in merged["targets"]] == ["u-1"]


def test_different_messages_stay_separate():
    store = _MemStore()
    c1 = _dm_card(store, targets=[{"user_id": "u-1", "display": "Anh"}], text="msg A")
    c2 = _dm_card(store, targets=[{"user_id": "u-2", "display": "Lam"}], text="msg A")
    c3 = _dm_card(store, targets=[{"user_id": "u-3", "display": "Phuc"}], text="msg B")
    out = _run(store, [c1, c2, c3])
    # msg A's two cards merge; msg B's lone card passes through → 2 cards total
    assert len(out) == 2
    texts = {store.get(_card_action_data(c)["pending_id"])["text"] for c in out}
    assert texts == {"msg A", "msg B"}


def test_non_teams_dm_cards_pass_through_in_place():
    store = _MemStore()
    other = confirm_card(title="Send email", summary="x", pending_id="mail-1",
                         action="mail", recipients=["a@x.com"], body="hi")
    c1 = _dm_card(store, targets=[{"user_id": "u-1", "display": "Anh"}], text="hi")
    c2 = _dm_card(store, targets=[{"user_id": "u-2", "display": "Lam"}], text="hi")
    out = _run(store, [other, c1, c2])
    assert len(out) == 2
    assert out[0] is other  # untouched, position preserved
    assert _card_action_data(out[1])["action"] == "teams_dm"


def test_same_group_distinct_messages_consolidate():
    # Impl 10 — the agent labels three personalized calls with one shared `group`; they fold into
    # a single consolidated personalized card, and each target keeps its own message text.
    store = _MemStore()
    c1 = _dm_card(store, targets=[{"user_id": "u-1", "display": "Phuc"}],
                  text="tasks A due 26/06", group="task-update")
    c2 = _dm_card(store, targets=[{"user_id": "u-2", "display": "Tho"}],
                  text="task B due 25/06", group="task-update")
    c3 = _dm_card(store, targets=[{"user_id": "u-3", "display": "Han"}],
                  text="tasks C due 10/07", group="task-update")
    out = _run(store, [c1, c2, c3])

    assert len(out) == 1
    data = _card_action_data(out[0])
    assert data["action"] == "teams_dm"
    merged = store.get(data["pending_id"])
    # each target carries its OWN message text (per-recipient personalization)
    assert {t["user_id"]: t["text"] for t in merged["targets"]} == {
        "u-1": "tasks A due 26/06", "u-2": "task B due 25/06", "u-3": "tasks C due 10/07"}
    # the three per-recipient pendings were superseded; only the merged one remains
    assert list(store.data.keys()) == [data["pending_id"]]
    # the card is a personalized breakdown, not a single shared-message card
    body_texts = [b.get("text") for b in out[0]["body"]]
    assert any("tasks A due 26/06" in (t or "") for t in body_texts)
    assert any("task B due 25/06" in (t or "") for t in body_texts)


def test_distinct_messages_no_group_stay_separate():
    # No group label + distinct text → each passes through as its own card (the agent's way of
    # keeping personalized messages separate). Mirrors the original text-based default.
    store = _MemStore()
    c1 = _dm_card(store, targets=[{"user_id": "u-1", "display": "Phuc"}], text="msg A")
    c2 = _dm_card(store, targets=[{"user_id": "u-2", "display": "Tho"}], text="msg B")
    c3 = _dm_card(store, targets=[{"user_id": "u-3", "display": "Han"}], text="msg C")
    out = _run(store, [c1, c2, c3])
    assert out == [c1, c2, c3]  # untouched, separate
    assert len(store.data) == 3  # pendings not disturbed


def test_distinct_group_labels_force_separate():
    # Same text but two different group labels → the agent explicitly chose to separate them.
    store = _MemStore()
    c1 = _dm_card(store, targets=[{"user_id": "u-1", "display": "Anh"}], text="hi", group="g1")
    c2 = _dm_card(store, targets=[{"user_id": "u-2", "display": "Lam"}], text="hi", group="g2")
    out = _run(store, [c1, c2])
    assert out == [c1, c2]  # not merged despite identical text


def test_same_group_same_text_renders_simple_batch_card():
    # A shared group whose messages all happen to be identical still folds to ONE card, but as
    # the simple shared-text batch shape (one message to many), not a per-recipient breakdown.
    store = _MemStore()
    c1 = _dm_card(store, targets=[{"user_id": "u-1", "display": "Anh"}], text="same", group="g")
    c2 = _dm_card(store, targets=[{"user_id": "u-2", "display": "Lam"}], text="same", group="g")
    out = _run(store, [c1, c2])
    assert len(out) == 1
    merged = store.get(_card_action_data(out[0])["pending_id"])
    assert merged["text"] == "same"
    assert [t["user_id"] for t in merged["targets"]] == ["u-1", "u-2"]
    # simple shared-text shape — targets carry no per-recipient text
    assert all("text" not in t for t in merged["targets"])


def test_coalesce_degrades_to_unchanged_on_store_error():
    class _BoomStore:
        def get(self, pid):
            raise RuntimeError("redis down")

    cards = [{"actions": [{"data": {"action": "teams_dm", "pending_id": "x"}}]},
             {"actions": [{"data": {"action": "teams_dm", "pending_id": "y"}}]}]
    out = coalesce_teams_dm_cards(cards, pending_store=_BoomStore(), confirm_card_fn=confirm_card)
    assert out == cards  # never drops cards when the store misbehaves
