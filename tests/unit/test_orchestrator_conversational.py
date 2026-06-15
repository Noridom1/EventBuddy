from eventbuddy.agent.orchestrator import Orchestrator


class _FakeSession:
    def __init__(self):
        self.current = {}

    def get_current_event(self, user_id):
        return self.current.get(user_id)

    def set_current_event(self, user_id, event_id):
        self.current[user_id] = event_id


class _FakeRunner:
    def __init__(self, reply=None, raises=False):
        self.reply = reply
        self.raises = raises
        self.seen = []

    def run(self, text, ctx):
        self.seen.append((text, ctx))
        if self.raises:
            raise RuntimeError("LLM down")
        return self.reply


def _deps(**over):
    base = dict(
        session_store=_FakeSession(),
        provision_fn=lambda **kw: type("E", (), {"event_id": "ev-1"})(),
        resolve_event_fn=lambda q: "ev-7",
        remind_fn=lambda **kw: None,
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
    )
    base.update(over)
    return base


def test_llm_reply_returned_when_runner_present():
    runner = _FakeRunner(reply="A natural conversational answer.")
    orch = Orchestrator(**_deps(), runner=runner)
    out = orch.handle(user_id="u1", channel_id=None, text="hello there")
    assert out == "A natural conversational answer."


def test_ctx_carries_identity_and_scope_aware_thread():
    runner = _FakeRunner(reply="ok")
    orch = Orchestrator(**_deps(), runner=runner)
    orch.handle(user_id="u1", channel_id="ch9", text="hi", scope="channel")
    _, ctx = runner.seen[0]
    assert ctx.user_id == "u1"
    assert ctx.channel_id == "ch9"
    assert ctx.thread_id == "event:ch9"


def test_dm_scope_threads_by_user():
    runner = _FakeRunner(reply="ok")
    orch = Orchestrator(**_deps(), runner=runner)
    orch.handle(user_id="u1", channel_id=None, text="hi")  # default scope=personal
    _, ctx = runner.seen[0]
    assert ctx.thread_id == "dm:u1"


def test_sent_at_threads_into_ctx():
    from datetime import UTC, datetime
    runner = _FakeRunner(reply="ok")
    orch = Orchestrator(**_deps(), runner=runner)
    ts = datetime(2026, 6, 11, 14, 30, tzinfo=UTC)
    orch.handle(user_id="u1", channel_id=None, text="hi", sent_at=ts)
    _, ctx = runner.seen[0]
    assert ctx.sent_at == ts


def test_sent_at_defaults_when_absent():
    runner = _FakeRunner(reply="ok")
    orch = Orchestrator(**_deps(), runner=runner)
    orch.handle(user_id="u1", channel_id=None, text="hi")  # no sent_at — back-compat
    _, ctx = runner.seen[0]
    assert ctx.sent_at is None


def test_falls_back_to_regex_when_runner_raises():
    calls = {}

    def provision_fn(**kw):
        calls.update(kw)
        return type("E", (), {"event_id": "ev-9"})()

    deps = _deps(provision_fn=provision_fn)
    orch = Orchestrator(**deps, runner=_FakeRunner(raises=True))
    out = orch.handle(user_id="u1", channel_id=None,
                      text="create event 'Launch' members: a@x.com")
    assert "Created event 'Launch'" in out
    assert calls["member_emails"] == ["a@x.com"]


def test_regex_mode_bypasses_runner_even_if_present():
    runner = _FakeRunner(reply="should-not-be-used")
    orch = Orchestrator(**_deps(), runner=runner, agent_mode="regex")
    out = orch.handle(user_id="u1", channel_id=None, text="hello there")
    assert out.startswith("Hi! Try:")
    assert runner.seen == []


def test_no_runner_uses_regex():
    orch = Orchestrator(**_deps())  # runner defaults to None
    out = orch.handle(user_id="u1", channel_id=None, text="focus on AI Workshop")
    assert "Focused on 'AI Workshop'" in out


# --- group/channel onboarding: binding + auto-enroll -----------------------------------------

def test_group_scope_resolves_event_via_binding_and_carries_team_id():
    runner = _FakeRunner(reply="ok")
    orch = Orchestrator(
        **_deps(), runner=runner,
        channel_event_fn=lambda *, channel_id, team_id=None: "ev-bound",
    )
    orch.handle(user_id="u1", channel_id="conv-1", text="hi", scope="group", team_id="team-9")
    _, ctx = runner.seen[0]
    assert ctx.current_event_id == "ev-bound"  # from the binding, not the session focus
    assert ctx.team_id == "team-9"
    assert ctx.thread_id == "group:conv-1"


def test_autoenroll_called_in_bound_shared_conversation():
    seen = []
    runner = _FakeRunner(reply="ok")
    orch = Orchestrator(
        **_deps(), runner=runner,
        channel_event_fn=lambda *, channel_id, team_id=None: "ev-bound",
        member_autoenroll_fn=lambda **kw: seen.append(kw),
    )
    orch.handle(user_id="u1", channel_id="conv-1", text="hi", scope="group",
                display_name="Alice")
    assert seen == [{"event_id": "ev-bound", "user_id": "u1", "display_name": "Alice"}]


def test_autoenroll_skipped_in_dm():
    seen = []
    runner = _FakeRunner(reply="ok")
    orch = Orchestrator(**_deps(), runner=runner,
                        member_autoenroll_fn=lambda **kw: seen.append(kw))
    orch.handle(user_id="u1", channel_id=None, text="hi")  # personal scope
    assert seen == []


def test_autoenroll_skipped_when_conversation_unbound():
    seen = []
    runner = _FakeRunner(reply="ok")
    orch = Orchestrator(
        **_deps(), runner=runner,
        channel_event_fn=lambda *, channel_id, team_id=None: None,  # no event bound
        member_autoenroll_fn=lambda **kw: seen.append(kw),
    )
    orch.handle(user_id="u1", channel_id="conv-1", text="hi", scope="group")
    assert seen == []


def test_autoenroll_failure_never_breaks_turn():
    def boom(**kw):
        raise RuntimeError("db down")

    runner = _FakeRunner(reply="still works")
    orch = Orchestrator(
        **_deps(), runner=runner,
        channel_event_fn=lambda *, channel_id, team_id=None: "ev-bound",
        member_autoenroll_fn=boom,
    )
    out = orch.handle(user_id="u1", channel_id="conv-1", text="hi", scope="group")
    assert out == "still works"


def test_reset_all_coordinates_runner_and_session():
    class _Runner(_FakeRunner):
        def __init__(self):
            super().__init__(reply="ok")
            self.reset_all_seen = 0

        def reset_all(self):
            self.reset_all_seen += 1
            return {"windows": 2, "transcript": 4, "summaries": 1}

    runner = _Runner()
    orch = Orchestrator(**_deps(), runner=runner)
    orch.session.clear_all = lambda: 7  # session store grows a clear_all
    out = orch.reset_all()
    assert runner.reset_all_seen == 1
    assert out == {"windows": 2, "transcript": 4, "summaries": 1, "sessions": 7}


def test_reset_all_degraded_path_uses_summarizer_attr():
    # No runner (regex/degraded): falls back to the orchestrator's summarizer attribute for L3.
    orch = Orchestrator(**_deps())  # runner=None
    orch.summarizer = type("S", (), {"clear_all": lambda self: 3})()
    orch.session.clear_all = lambda: 1
    out = orch.reset_all()
    assert out == {"summaries": 3, "sessions": 1}
