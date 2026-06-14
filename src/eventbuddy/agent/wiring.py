from langchain_core.messages import HumanMessage

from eventbuddy.agent.orchestrator import Orchestrator, _default_role
from eventbuddy.agent.pending import PendingActionStore
from eventbuddy.agent.session import SessionStore
from eventbuddy.bot.auth import ROLE_RANK
from eventbuddy.bot.cards.builders import confirm_card, reminder_channel_card
from eventbuddy.bot.cards.report_card import report_card
from eventbuddy.bot.confirm import ConfirmHandler
from eventbuddy.bot.turn_artifacts import emit_card
from eventbuddy.common.logging import get_logger
from eventbuddy.config import settings
from eventbuddy.data.redis import get_redis

log = get_logger("agent.wiring")


def _graph_creds() -> bool:
    """True when client-credentials Graph auth is configured (so outbound sends can run).
    Without it, prepare still works and cards still render — only the *send* degrades."""
    return bool(
        settings.graph_tenant_id and settings.graph_client_id and settings.graph_client_secret
    )


def _perform_send(*, graph, payload: dict, channel: str | None) -> tuple[bool, str]:
    """Pure dispatch for a confirmed HITL action: perform the Microsoft Graph send and return
    `(ok, summary)`. Module-level (not a closure) so it's unit-testable with a fake Graph.
    All mail/reminders send **individually** — never a shared To/CC (PII rule §11). Raises
    only on an actual Graph error; a known precondition miss returns `(False, message)`."""
    from eventbuddy.capabilities.reminders import ReminderService
    action = payload.get("type")
    recipients = payload.get("recipient_emails", [])
    event_name = payload.get("event_name") or "the event"
    if action == "remind" and channel == "teams":
        channel_id = payload.get("channel_id")
        if not channel_id:
            return False, "This event has no Teams channel to post to."
        graph.send_channel_message(
            settings.microsoft_app_tenant_id, channel_id,
            f"⏰ Reminder: '{payload.get('task_name')}' for {event_name} is due soon.",
        )
        return True, "✅ Posted the reminder to the event channel."
    if action == "remind":  # outlook (default)
        svc = ReminderService(graph)
        for email in recipients:
            svc.remind_outlook(
                email=email, task_name=payload.get("task_name", "your task"),
                event_name=event_name,
            )
        return True, f"✅ Sent {len(recipients)} Outlook reminder(s)."
    if action == "mail":
        for email in recipients:
            graph.send_mail(
                subject=payload.get("subject", ""),
                body_html=payload.get("body_html", ""), to=[email],
            )
        return True, f"✅ Sent the email to {len(recipients)} recipient(s)."
    return False, "I don't know how to perform that action."

# A DM-injected event snapshot competes with the user's own turns for the 4096-token DM
# window, so keep the cross-context read compact (Phase 1.9, Part B).
EVENT_CTX_BUDGET = 700


def _build_event_context_fn(transcript, summarizer):
    """The single guarded DM→event cross-context read (Phase 1.9, Part B). Owns all three
    security checks (cross-cutting rule 2 + one-directional privacy) in one place:

      1. event id is always the *server-resolved* focused event — never a tool argument;
      2. membership is verified server-side (non-member → empty, not an error);
      3. only the event thread's L3 summary + L2 transcript tail are read — never L1, and
         never the reverse direction (an event channel never reads a user's DM).

    Returns a compact, timestamped snapshot string, or "" on any miss (no focused event /
    no channel bound / not a member / nothing recorded) — graceful, consistent with the
    rest of the system."""
    from eventbuddy.agent.context import event_thread_id
    from eventbuddy.agent.transcript import sent_at_prefix

    def event_context_fn(*, user_id: str, event_id: str | None) -> str:
        if not event_id:
            return ""
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.data.repositories.members import MemberRepository
        try:
            with session_scope() as s:
                ev = EventRepository(s).get(event_id)
                if ev is None or ev.teams_channel_id is None:
                    return ""  # no shared thread to read
                if MemberRepository(s).get_by_user(event_id, user_id) is None:
                    return ""  # not a member — don't leak the shared conversation
                thread_id = event_thread_id(ev.teams_channel_id)
                event_name = ev.event_name
        except Exception as e:  # noqa: BLE001 — degrade gracefully, never break the turn
            log.warning(f"event context read failed ({type(e).__name__}: {e})")
            return ""

        summary = summarizer.get_summary(thread_id) if summarizer is not None else ""
        tail = (
            transcript.rehydrate(thread_id, budget=EVENT_CTX_BUDGET)
            if transcript is not None
            else []
        )
        if not summary and not tail:
            return ""

        parts = [f"Context from event '{event_name}':"]
        if summary:
            parts.append(summary)
        if tail:
            parts.append("\nRecent discussion:")
            for m in tail:
                role = "User" if isinstance(m, HumanMessage) else "Assistant"
                speaker = getattr(m, "name", None)
                who = f"{role} ({speaker})" if speaker else role
                parts.append(f"{sent_at_prefix(m)}{who}: {m.content}")
        return "\n".join(parts)

    return event_context_fn


def build_orchestrator() -> Orchestrator:
    """Compose the production orchestrator. Phase 1.7 routes the conversation through an
    LLM tool-calling runner (create_react_agent + layered memory); the same capability
    closures remain the tool bodies (DRY). Without MaaS creds — or with agent_mode=regex —
    it degrades to the Phase 1 regex router. Live Microsoft actions still require Graph
    credentials; until then create-event persists locally."""
    session_store = SessionStore(get_redis())
    pending_store = PendingActionStore(get_redis(), ttl=settings.pending_action_ttl)

    def provision_fn(**kw):
        from eventbuddy.capabilities.provisioning import ProvisioningService
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.data.repositories.members import MemberRepository
        from eventbuddy.integrations.graph.client import GraphClient
        from eventbuddy.integrations.graph.token import MsalTokenProvider
        with session_scope() as s:
            svc = ProvisioningService(
                EventRepository(s), MemberRepository(s),
                GraphClient(MsalTokenProvider()), team_id=settings.microsoft_app_tenant_id,
            )
            ev = svc.create_event(**kw)
            s.flush()
            return type("E", (), {"event_id": ev.event_id})()

    def resolve_event_fn(query: str) -> str | None:
        from sqlalchemy import select

        from eventbuddy.data.db import session_scope
        from eventbuddy.domain.models import Event
        with session_scope() as s:
            ev = s.scalar(select(Event).where(Event.event_name.ilike(f"%{query}%")))
            return ev.event_id if ev else None

    def remind_fn(*, event_id, user_id, raw=""):
        """Impl 1: *prepare* (don't send) — resolve recipients, stash a one-shot pending
        action, emit the channel-choice card. The real send happens only on confirm. Returns
        None on success (the tool/regex caller uses its default 'pick a channel' message), or
        a friendly string on a degraded path."""
        if not event_id:
            return None
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.data.repositories.members import MemberRepository
        try:
            with session_scope() as s:
                ev = EventRepository(s).get(event_id)
                if ev is None:
                    return "I couldn't find that event anymore."
                recipients = [m.email for m in MemberRepository(s).list(event_id) if m.email]
                event_name, channel_id = ev.event_name, ev.teams_channel_id
        except Exception as e:  # noqa: BLE001
            log.warning(f"reminder prep failed ({type(e).__name__}: {e})")
            return "Reminders are temporarily unavailable — please try again."
        if not recipients:
            return "There's no one to remind for this event yet."
        task_name = (raw or "").strip() or "your tasks"
        payload = {
            "type": "remind", "event_id": event_id, "event_name": event_name,
            "channel_id": channel_id, "requested_by": user_id,
            "task_name": task_name, "recipient_emails": recipients, "note": raw,
        }
        try:
            pending_id = pending_store.put(payload)
        except Exception as e:  # noqa: BLE001 — Redis down: emit nothing rather than a dead card
            log.warning(f"pending store unavailable ({type(e).__name__}: {e})")
            return "Reminders are temporarily unavailable — please try again."
        emit_card(reminder_channel_card(
            task_name=task_name, recipients=recipients, pending_id=pending_id
        ))
        return None

    def report_fn(*, event_id, user_id=None):
        """Impl 2: aggregate metrics + LLM summary + next-event suggestions, persist a Report,
        emit a read-only report card, and draft the manager-summary email behind a HITL confirm
        card (reuses the Impl 1 pending-action + confirm machinery). When a responses-workbook
        is configured, fetch fresh MS Forms responses first. Degrades to a friendly message on
        any failure — never raises into the agent loop."""
        if not event_id:
            return ("Focus on an event first (e.g. 'focus on AI Workshop'), then ask for "
                    "the report.")
        from eventbuddy.capabilities.forms_sync import FormsResponseSync
        from eventbuddy.capabilities.reporting import ReportingService
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.audit import AuditRepository
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.data.repositories.feedback import FeedbackRepository
        from eventbuddy.data.repositories.members import MemberRepository
        from eventbuddy.data.repositories.reports import ReportRepository
        from eventbuddy.domain.feedback import FeedbackAnalyzer
        from eventbuddy.integrations.llm.client import LLMGateway

        try:
            with session_scope() as s:
                ev = EventRepository(s).get(event_id)
                if ev is None:
                    return "I couldn't find that event anymore."
                event_name = ev.event_name
                members = MemberRepository(s).list(event_id)
                manager_emails = [
                    m.email for m in members
                    if m.email and m.role in ("host", "moderator")
                ] or [m.email for m in members if m.email][:1]
                feedback_repo = FeedbackRepository(s)
                llm = LLMGateway()
                # Fetch fresh Form responses from the responses workbook (the chosen path).
                if settings.feedback_workbook_url and _graph_creds():
                    try:
                        from eventbuddy.integrations.graph.client import GraphClient
                        from eventbuddy.integrations.graph.token import MsalTokenProvider
                        FormsResponseSync(
                            GraphClient(MsalTokenProvider()), feedback_repo,
                            FeedbackAnalyzer(llm),
                        ).sync(event_id=event_id, workbook_url=settings.feedback_workbook_url)
                        s.flush()
                    except Exception as e:  # noqa: BLE001
                        log.warning(f"forms sync skipped ({type(e).__name__}: {e})")
                report = ReportingService(
                    MemberRepository(s), feedback_repo, ReportRepository(s), llm,
                ).generate(event_id=event_id)
                s.flush()
                metrics, summary = report.metrics_json, report.summary_md
                suggestions, report_id = report.suggestions_md, report.report_id
                AuditRepository(s).record(
                    event_id=event_id, actor_user_id=user_id, action="report",
                    tool_name="generate_report", payload={"report_id": report_id},
                    result="generated",
                )
        except Exception as e:  # noqa: BLE001 — LLM/DB down: degrade, don't crash the turn
            log.warning(f"report generation failed ({type(e).__name__}: {e})")
            return "I couldn't generate the report right now — please try again shortly."

        emit_card(report_card(metrics=metrics, summary_md=summary, suggestions_md=suggestions))

        # Draft the manager-summary email behind the HITL gate (nothing sends until confirmed).
        tail = "📊 Report ready — posted the card above."
        if manager_emails:
            body_html = (f"<h3>Report — {event_name}</h3><p><b>Summary</b><br>{summary}</p>"
                         f"<p><b>Suggestions</b><br>{suggestions}</p>")
            payload = {
                "type": "mail", "event_id": event_id, "event_name": event_name,
                "requested_by": user_id, "subject": f"[Report] {event_name}",
                "body_html": body_html, "recipient_emails": manager_emails,
            }
            try:
                pending_id = pending_store.put(payload)
                emit_card(confirm_card(
                    title=f"Email the report to the manager? ({len(manager_emails)})",
                    summary=f"Sends the summary + suggestions for '{event_name}'.",
                    pending_id=pending_id, action="mail",
                ))
                tail += " Confirm on the card to email the summary to the manager."
            except Exception as e:  # noqa: BLE001
                log.warning(f"report email draft skipped ({type(e).__name__}: {e})")
        return tail

    def query_tasks_fn(*, user_id, event_id):
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.tasks import TaskRepository
        with session_scope() as s:
            tasks = TaskRepository(s).by_assignee(user_id)
            if not tasks:
                return "You have no assigned tasks."
            return "Your tasks:\n" + "\n".join(f"- {t.task_name} ({t.status})" for t in tasks)

    def update_task_fn(*, user_id, role, event_id, task_query, status):
        """Direct (non-HITL) task status update. Member may update own tasks; moderator/host
        any. Resolves the task by name within the focused event."""
        valid = {"todo", "in_progress", "done"}
        if status not in valid:
            return f"Status must be one of: {', '.join(sorted(valid))}."
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.tasks import TaskRepository
        try:
            with session_scope() as s:
                repo = TaskRepository(s)
                matches = [
                    t for t in repo.list(event_id) if task_query.lower() in t.task_name.lower()
                ]
                if not matches:
                    return f"I couldn't find a task matching '{task_query}'."
                if len(matches) > 1:
                    return f"'{task_query}' matches multiple tasks — please be more specific."
                t = matches[0]
                is_mod = ROLE_RANK.get(role, 0) >= ROLE_RANK["moderator"]
                if not is_mod and t.assignee_id != user_id:
                    return "You can only update your own tasks (moderators can update any)."
                name = t.task_name
                repo.set_status(t.task_id, status)
                return f"Updated '{name}' → {status}."
        except Exception as e:  # noqa: BLE001
            log.warning(f"update_task failed ({type(e).__name__}: {e})")
            return "Couldn't update the task right now."

    def send_mail_fn(*, user_id, event_id, subject, body, recipients=None):
        """Impl 1: draft an Outlook mail behind a HITL confirm card (bulk/outward → §9/§11).
        Stashes a pending action + emits a confirm card; never sends here."""
        emails = list(recipients) if recipients else []
        event_name = None
        if not emails:
            if not event_id:
                return "I don't have any recipients — focus an event or give me addresses."
            from eventbuddy.data.db import session_scope
            from eventbuddy.data.repositories.events import EventRepository
            from eventbuddy.data.repositories.members import MemberRepository
            try:
                with session_scope() as s:
                    ev = EventRepository(s).get(event_id)
                    event_name = ev.event_name if ev else None
                    emails = [m.email for m in MemberRepository(s).list(event_id) if m.email]
            except Exception as e:  # noqa: BLE001
                log.warning(f"mail recipient load failed ({type(e).__name__}: {e})")
                return "Couldn't load the recipient list right now."
        if not emails:
            return "There are no members to email for this event yet."
        payload = {
            "type": "mail", "event_id": event_id, "event_name": event_name,
            "requested_by": user_id, "subject": subject,
            "body_html": f"<p>{body}</p>", "recipient_emails": emails,
        }
        try:
            pending_id = pending_store.put(payload)
        except Exception as e:  # noqa: BLE001
            log.warning(f"pending store unavailable ({type(e).__name__}: {e})")
            return "Mail confirmation is temporarily unavailable — please try again."
        emit_card(confirm_card(
            title=f"Send email: {subject}", summary=f"To {len(emails)} recipient(s).",
            pending_id=pending_id, action="mail",
        ))
        return "Drafted the email — confirm on the card to send."

    def ingest_fn(*, event_id, user_id, url=""):
        """Impl 2: pull the focused event's channel SharePoint files (or a pasted link)
        through the parse→structure→upsert pipeline, proposing invites via a HITL card posted
        to the channel. Degrades cleanly without Graph creds / a bound channel."""
        if not _graph_creds():
            return "I can't read files yet — Microsoft Graph isn't configured."
        from eventbuddy.capabilities.channel_files import ChannelFilesService
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.ingestion.extractor import Extractor
        from eventbuddy.ingestion.pipeline import IngestionPipeline
        from eventbuddy.integrations.graph.client import GraphClient
        from eventbuddy.integrations.graph.token import MsalTokenProvider
        from eventbuddy.integrations.llm.client import LLMGateway

        try:
            graph = GraphClient(MsalTokenProvider())
            team_id = settings.microsoft_app_tenant_id

            def post_card(channel_id, card):
                graph.send_channel_card(team_id, channel_id, card)

            pipeline = IngestionPipeline(
                graph, Extractor(LLMGateway()),
                pending_store=pending_store, post_card=post_card,
            )
            svc = ChannelFilesService(graph, pipeline, team_id=team_id)
            if url:
                summary = svc.ingest_link(event_id=event_id, url=url)
            else:
                with session_scope() as s:
                    ev = EventRepository(s).get(event_id)
                    channel_id = ev.teams_channel_id if ev else None
                if not channel_id:
                    return "This event has no Teams channel bound, so I can't read its files."
                summary = svc.sync_channel(event_id=event_id, channel_id=channel_id)
        except Exception as e:  # noqa: BLE001
            log.warning(f"file ingestion failed ({type(e).__name__}: {e})")
            return "I couldn't read the files right now — please try again shortly."

        parts = [f"📎 Ingested {summary['files_ingested']} file(s)"]
        if summary["members_added"]:
            parts.append(f"added {summary['members_added']} member(s)")
        if summary["tasks_added"]:
            parts.append(f"found {summary['tasks_added']} task(s)")
        msg = ", ".join(parts) + "."
        if summary["invited_proposed"]:
            msg += (f" I posted a card to the channel to invite "
                    f"{summary['invited_proposed']} member(s) — confirm to send.")
        return msg

    def role_resolver(*, user_id, scope, channel_id, event_id=None):
        """Membership-backed role (defense in depth). When an event is focused, the caller's
        real `EventMember.role` overrides the DM-host default — so the in-tool moderator gate
        and the confirm re-auth reflect actual membership. Falls back to `_default_role`
        (host-in-DM) when there's no focused event yet (e.g. event creation)."""
        if event_id:
            from eventbuddy.data.db import session_scope
            from eventbuddy.data.repositories.members import MemberRepository
            try:
                with session_scope() as s:
                    m = MemberRepository(s).get_by_user(event_id, user_id)
                    if m is not None:
                        return m.role
            except Exception as e:  # noqa: BLE001
                log.warning(f"role lookup failed ({type(e).__name__}: {e})")
        return _default_role(
            user_id=user_id, scope=scope, channel_id=channel_id, event_id=event_id
        )

    def execute_confirmed_action(*, payload, channel, actor, authorized):
        """Side-effecting half of the HITL confirm loop: the real Graph send + every
        `audit_log` write (including denials/failures). Returns `(ok, reply_text)`. All
        outward mail/reminders send **individually** (PII rule §11), never a shared To/CC."""
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.audit import AuditRepository
        action = payload.get("type", "unknown")
        event_id = payload.get("event_id")

        def _audit(result):
            try:
                with session_scope() as s:
                    AuditRepository(s).record(
                        event_id=event_id, actor_user_id=actor, action=action,
                        tool_name=action, payload=payload, result=result,
                    )
            except Exception as e:  # noqa: BLE001
                log.warning(f"audit write failed ({type(e).__name__}: {e})")

        if not authorized:
            _audit("denied")
            return False, "You're not allowed to confirm this action."
        if not _graph_creds():
            _audit("failed")
            return False, "Couldn't send — Microsoft Graph isn't configured."

        from eventbuddy.integrations.graph.client import GraphClient
        from eventbuddy.integrations.graph.token import MsalTokenProvider
        try:
            graph = GraphClient(MsalTokenProvider())
            ok, summary = _perform_send(graph=graph, payload=payload, channel=channel)
        except Exception as e:  # noqa: BLE001
            log.warning(f"confirmed {action} send failed ({type(e).__name__}: {e})")
            _audit("failed")
            return False, "Couldn't send — the Microsoft Graph call failed."
        _audit("sent" if ok else "failed")
        return ok, summary

    runner, summarizer = _build_runner_and_summarizer(
        session_store, provision_fn, resolve_event_fn, remind_fn, report_fn, query_tasks_fn,
        update_task_fn, send_mail_fn, ingest_fn,
    )

    orch = Orchestrator(
        session_store=session_store, provision_fn=provision_fn,
        resolve_event_fn=resolve_event_fn, remind_fn=remind_fn,
        report_fn=report_fn, query_tasks_fn=query_tasks_fn,
        runner=runner, agent_mode=settings.agent_mode if runner else "regex",
        role_resolver=role_resolver,
        regex_fallback_on_error=not settings.agent_debug,
    )
    orch.summarizer = summarizer  # exposed so main.py can schedule the consolidation job
    # The activity router pulls this off the orchestrator to handle Adaptive Card clicks.
    orch.confirm_handler = ConfirmHandler(
        pending_store=pending_store, role_resolver=role_resolver,
        execute_fn=execute_confirmed_action,
    )
    return orch


def build_summarizer():
    """The rolling-summary consolidator, or None without MaaS creds. Stateless aside from
    its LLM/DB handles — safe to build standalone for the background scheduler job."""
    from eventbuddy.agent.summarizer import Summarizer
    from eventbuddy.integrations.llm.client import LLMGateway

    return Summarizer(LLMGateway()) if settings.agentbase_llm_base_url else None


def _build_runner_and_summarizer(
    session_store, provision_fn, resolve_event_fn, remind_fn, report_fn, query_tasks_fn,
    update_task_fn=None, send_mail_fn=None, ingest_fn=None,
):
    """Build the LLM runner + summarizer, or (None, summarizer) when the chat path can't run
    (no creds / agent_mode=regex). The summarizer is built regardless so the background
    consolidation job can run wherever a transcript exists."""
    summarizer = build_summarizer()

    creds = bool(settings.agentbase_llm_base_url and settings.agentbase_llm_api_key)
    if settings.agent_mode != "llm" or not creds:
        if not creds:
            log.info("No MaaS creds — chat path degraded to the regex router.")
        return None, summarizer

    from eventbuddy.agent.memory import build_checkpointer, setup_checkpointer
    from eventbuddy.agent.model import build_chat_model, make_token_counter
    from eventbuddy.agent.runner import build_agent_runner
    from eventbuddy.agent.tools import AgentDeps, build_tools
    from eventbuddy.agent.transcript import Transcript

    model = build_chat_model()
    checkpointer = build_checkpointer()
    setup_checkpointer(checkpointer)
    transcript = Transcript()

    # Built here (after transcript + summarizer exist) so the cross-context closure can
    # close over them — same DRY composition-root pattern as the other capability closures.
    event_context_fn = _build_event_context_fn(transcript, summarizer)

    from eventbuddy.agent.tools import _no_ingest, _no_send_mail, _no_update_task

    deps = AgentDeps(
        session_store=session_store, provision_fn=provision_fn,
        resolve_event_fn=resolve_event_fn, remind_fn=remind_fn,
        report_fn=report_fn, query_tasks_fn=query_tasks_fn,
        event_context_fn=event_context_fn,
        update_task_fn=update_task_fn or _no_update_task,
        send_mail_fn=send_mail_fn or _no_send_mail,
        ingest_fn=ingest_fn or _no_ingest,
        debug=settings.agent_debug,
    )
    runner = build_agent_runner(
        model,
        tools_factory=lambda ctx: build_tools(deps, ctx),
        checkpointer=checkpointer,
        token_counter=make_token_counter(),
        transcript=transcript,
        summarizer=summarizer,
        debug=settings.agent_debug,
    )
    return runner, summarizer
