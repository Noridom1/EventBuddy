"""Coalescing the turn's per-recipient `teams_dm` confirm cards into one (UX belt-and-suspenders
over the batch `send_teams_message` tool). Uses the real `confirm_card` builder + an in-memory
pending store, so it exercises the actual merge/store/supersede path."""
from eventbuddy.agent.wiring import _card_action_data, coalesce_teams_dm_cards
from eventbuddy.bot.cards.builders import confirm_card


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


def _dm_card(store, *, targets, text):
    """Build a teams_dm confirm card backed by a freshly stored pending (as the closure does)."""
    pid = store.put({"type": "teams_dm", "targets": targets, "text": text})
    displays = [t["display"] for t in targets]
    return confirm_card(title="Send Teams message", summary="x", pending_id=pid,
                        action="teams_dm", recipients=displays, body=text)


def _run(store, cards):
    return coalesce_teams_dm_cards(cards, pending_store=store, confirm_card_fn=confirm_card)


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


def test_coalesce_degrades_to_unchanged_on_store_error():
    class _BoomStore:
        def get(self, pid):
            raise RuntimeError("redis down")

    cards = [{"actions": [{"data": {"action": "teams_dm", "pending_id": "x"}}]},
             {"actions": [{"data": {"action": "teams_dm", "pending_id": "y"}}]}]
    out = coalesce_teams_dm_cards(cards, pending_store=_BoomStore(), confirm_card_fn=confirm_card)
    assert out == cards  # never drops cards when the store misbehaves
