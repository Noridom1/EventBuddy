from eventbuddy.agent.intents import Intent, classify


def test_create_event_intent_extracts_name():
    r = classify("@EventBuddy create event 'AI Workshop' members: a@x.com, b@x.com")
    assert r.intent == Intent.CREATE_EVENT
    assert r.slots["event_name"] == "AI Workshop"
    assert r.slots["emails"] == ["a@x.com", "b@x.com"]


def test_remind_intent():
    assert classify("remind whoever hasn't submitted slides").intent == Intent.REMIND


def test_context_switch_intent():
    r = classify("focus on AI Workshop")
    assert r.intent == Intent.CONTEXT_SWITCH
    assert r.slots["event_query"] == "AI Workshop"


def test_my_tasks_intent():
    assert classify("what tasks are due soon?").intent == Intent.QUERY_TASKS


def test_generate_report_intent():
    assert classify("generate the report").intent == Intent.GENERATE_REPORT


def test_unknown_falls_back_to_smalltalk():
    assert classify("hello there").intent == Intent.SMALL_TALK
