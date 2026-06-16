# Implementation 10 — Agent Reasoning Trace Logging (implemented)

Status: **complete** on branch `impl-9-chat-file-intelligence` (implemented 2026-06-16). **482 unit tests green** (9 new), `ruff check src/ tests/` clean, **no migrations**, no schema or dependency changes. Implementation plan: [__plans__/17-agent-reasoning-trace-logging.md](../__plans__/17-agent-reasoning-trace-logging.md).

This is the tenth implementation. It is an **observability** change — it makes the agent's reasoning loop visible *in the logs* and changes nothing about what the agent can do, how it replies, or how memory works.

---

## The problem it solves

The only existing window into a turn was the **`AGENT_DEBUG` footer** ([runner.py `_format_footer`](../src/eventbuddy/agent/runner.py#L80-L92)) appended to the user reply, and it captures only tool **name + params** + error/traceback (`ToolCallRecord`). It does not show **what we send the model** (system prompt + window), the model's **reasoning**, the tool **return values**, or **how the model reasons over those returns**.

`LOG_LEVEL=DEBUG` did **not** fill the gap:
- There were **no `log.debug(...)` calls** in the runner/orchestrator/tools loop — raising the level unlocked a level nothing wrote to.
- `_JSONFormatter` serialized only `{level, logger, msg}`, **dropping** any structured `extra=` fields.
- `DEBUG` mostly surfaces `httpx`/`openai`/`redis`/`langgraph` noise, not the model's reasoning in a usable shape.

So before this change there was no way to trace the brain's reasoning, tool calls, or tool returns in the logs.

---

## What you get now

With **`AGENT_TRACE=true`**, each turn emits an ordered, structured, `jq`-filterable sequence under the **`agent.trace`** logger at **INFO**:

```
turn.start   {thread_id, scope, role, event_id, seeded}
llm.input    {step, payload:[{role, content}, …]}      ← system prompt + trimmed window
llm.output   {step, payload:{reasoning, tool_calls}, usage}
tool.start   {step, tool, payload:<input>}
tool.end     {step, payload:<return value>}             ← the piece the footer never had
llm.input    {step:2, …}                                ← how it reasons over the return
llm.output   {step:2, …}
…
```

Filter a turn out of the JSON log stream with:
```
… | jq 'select(.logger=="agent.trace")'
```

This answers all five of the original questions: what we input into the model, what the model reasons, which tools it calls (with args), what those tools return, and how it reasons over the return.

---

## Design — a LangChain callback handler, attached per turn

The model is a stock `ChatOpenAI` driven by `create_react_agent(...).invoke(...)`. The trace rides a **`BaseCallbackHandler`** passed in the invoke `config` — LangGraph propagates it to the chat model **and** the tool node, so **no tool body and no agent-construction code changed**.

| File | Change |
|------|--------|
| [config.py](../src/eventbuddy/config.py) | `agent_trace: bool = False` (env `AGENT_TRACE`) — independent of `LOG_LEVEL` and `AGENT_DEBUG` |
| [common/logging.py](../src/eventbuddy/common/logging.py) | `_JSONFormatter` merges a whitelisted `_TRACE_FIELDS` set into the JSON line (+ `default=str`); `msg`-only logs unchanged |
| [agent/trace_logger.py](../src/eventbuddy/agent/trace_logger.py) | **new** — `TracingCallbackHandler` + `_truncate`/`_render_content` helpers, `TRUNCATE_LEN=2000` |
| [agent/runner.py](../src/eventbuddy/agent/runner.py) | `trace` ctor arg; `turn.start` emit (carries `seeded`); attach handler via `config={"callbacks": [...]}` when on |
| [agent/wiring.py](../src/eventbuddy/agent/wiring.py) | thread `trace=settings.agent_trace` into `build_agent_runner` |

Hook → event mapping:
- `on_chat_model_start` → **`llm.input`** (rendered messages: `{role, content}`).
- `on_llm_end` → **`llm.output`** (assistant `content` = reasoning, compact `tool_calls`, token `usage` from `message.usage_metadata`).
- `on_tool_start` / `on_tool_end` / `on_tool_error` → **`tool.start`** / **`tool.end`** / **`tool.error`**.
- A `step` counter (per LLM round) plus `thread_id` on every record makes a turn read as an ordered sequence.
- `turn.start` (emitted by the runner, not a hook) records the **memory provenance** — `seeded` = whether the empty Redis window was re-seeded from the summary/transcript — which the model-input line alone can't reveal.

---

## Decisions (confirmed with the user, 2026-06-16)

| Question | Decision |
|----------|----------|
| Gating + level | **Dedicated `AGENT_TRACE` flag; emit at INFO** under `agent.trace`. Visible without enabling global `DEBUG` (no httpx/redis noise tax). OFF by default. |
| Payload size | **Truncate (~2000 chars) + redact images.** Base64 `image_url` content → `"<image>"`, never the blob. |
| Mechanism | **LangChain `BaseCallbackHandler`** attached in the invoke config — zero changes to tool bodies / agent construction. |
| Relationship to `AGENT_DEBUG` | **Orthogonal.** `AGENT_DEBUG` = reply footer (`ToolTrace`); `AGENT_TRACE` = log trace. Either, both, or neither. |

---

## Cross-cutting rules preserved

- **Graceful degradation.** Every callback hook is wrapped in a broad `try/except` that degrades to a single `agent.trace` warning — a formatting/serialization error can never raise into the turn (`test_handler_never_raises`). When `AGENT_TRACE=false`, no handler is attached → zero overhead on the default path.
- **`AGENT_DEBUG` untouched.** `begin_trace`/`end_trace`/`_format_footer`/`ToolTrace` are unchanged; the footer behaves byte-for-byte as before (`test_trace_independent_of_debug`).
- **Identity stays server-side (rule 2).** The trace logs the model-supplied tool args and the model's own content — identity/role/scope come from `RequestContext` and are not tool params, so they don't leak as tool arguments. (`turn.start` deliberately logs `role`/`scope` as server-resolved facts, not model input.)

---

## Tests (9 new)

- `test_formatter_passes_structured_extras` — whitelisted fields ride into the JSON; a plain log is unchanged.
- `test_handler_emits_llm_input_output` — `llm.input` (rendered messages) + `llm.output` (reasoning, tool_calls, usage).
- `test_handler_emits_tool_start_end_error` — the three tool events with input/return/error.
- `test_truncation_and_image_redaction` — long strings cut with a marker; `image_url` → `<image>`, no base64.
- `test_handler_never_raises` — malformed payloads degrade to a record, never an exception.
- `test_runner_attaches_handler_when_trace_on` / `test_runner_no_trace_when_off` — full `create_react_agent` path emits the ordered sequence (incl. the tool **return**) only when `trace=True`.
- `test_trace_independent_of_debug` — `trace=True, debug=False` → log records, no reply footer.

---

## Operating notes & follow-ups

- **`.env.example` not updated** — the file is blocked by this environment's permission settings. Add manually near the other agent flags:
  ```
  AGENT_TRACE=false   # Impl 10 — ordered reasoning trace to the `agent.trace` logger at INFO when true
  ```
- **PII in logs.** When on, `llm.input` / `tool.end` carry user content (prompts, file contents, rosters). Truncation bounds volume, but **do not enable against a shared/prod log sink without a retention review.** Intended for dev/debug.
- **Manual smoke (step 7) pending** — set `AGENT_TRACE=true` and run a list→match→read→answer turn via the dev route / emulator to eyeball the live sequence.
- **Async note** — the runner uses synchronous `.invoke`, so the sync `BaseCallbackHandler` is correct and the per-turn `step` counter is single-threaded-safe. If the runner ever moves to `ainvoke`, switch to `AsyncCallbackHandler`.
