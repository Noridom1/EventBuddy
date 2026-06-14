"""Impl 3, Part 2 — EventRepository.list_for_user. A user sees the events they're a roster
member of and the ones they host, paired with their role; never other people's events."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from eventbuddy.data.repositories.events import EventRepository
from eventbuddy.domain.models import Event, EventMember


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Event.__table__.create(engine)
    EventMember.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_list_for_user_returns_member_and_host_events():
    s = _session()
    s.add_all([
        Event(event_id="ev1", event_name="Launch", status="planning", host_user_id="other"),
        Event(event_id="ev2", event_name="Workshop", status="ideation", host_user_id="u1"),
        Event(event_id="ev3", event_name="Secret", status="planning", host_user_id="other"),
        EventMember(event_id="ev1", teams_user_id="u1", email="u1@x.com", role="moderator"),
        EventMember(event_id="ev3", teams_user_id="someone", email="s@x.com", role="member"),
    ])
    s.commit()

    rows = EventRepository(s).list_for_user("u1")
    by_id = {ev.event_id: role for ev, role in rows}
    assert by_id == {"ev1": "moderator", "ev2": "host"}  # member of ev1, host of ev2; not ev3


def test_list_for_user_dedupes_host_who_is_also_member():
    s = _session()
    s.add_all([
        Event(event_id="ev1", event_name="Launch", status="planning", host_user_id="u1"),
        EventMember(event_id="ev1", teams_user_id="u1", email="u1@x.com", role="host"),
    ])
    s.commit()
    rows = EventRepository(s).list_for_user("u1")
    assert len(rows) == 1 and rows[0][0].event_id == "ev1"


def test_list_for_user_empty():
    s = _session()
    s.add(Event(event_id="ev1", event_name="Launch", host_user_id="other"))
    s.commit()
    assert EventRepository(s).list_for_user("nobody") == []


def test_set_team_id_persists():
    s = _session()
    s.add(Event(event_id="ev1", event_name="Launch", teams_channel_id="ch-1"))
    s.commit()
    EventRepository(s).set_team_id("ev1", "team-42")
    s.commit()
    assert s.get(Event, "ev1").teams_team_id == "team-42"
