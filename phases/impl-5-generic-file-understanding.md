# Implementation 5 — Generic File Understanding (Catalog + On-Demand Read + Vision) (implemented)

Status: **complete** on branch `impl-5-generic-file-understanding` (implemented 2026-06-14). **342 unit tests green** (26 new), `ruff check src/ tests/` clean, **one migration** (`0006` — `documents.summary` + `documents.doc_type`). App imports cleanly; the tool registry builds with the two new tools. Implementation plan: [__plans__/12-impl5-generic-file-understanding.md](../__plans__/12-impl5-generic-file-understanding.md).

This is the fifth implementation. Impl 1 built the **action plane**, Impl 2 the **intelligence plane** (file ingestion **hardwired to invite-proposal**), Impl 3 widened **reach** (web + brainstorm), Impl 4 added **participant rosters**. Impl 5 generalizes file handling: any file in the channel becomes a first-class, browseable, readable resource — and images become legible via a dedicated vision model — without binding "what a file is for" to a single outcome.

---

## What the agent can do now (new this implementation)

| # | Capability | Tool / surface | Gate | New? |
|---|-----------|----------------|------|------|
| 1 | **Browse the channel's files** — list every file in the focused event's Teams channel, each with a one-line summary of what it is and an id | `list_event_files` | any member | ✅ new |
| 2 | **Read any file on demand** — fetch one file live by id (or a pasted link): text documents via the parsers, **images / scanned PDFs via a vision model** | `read_event_file` | any member | ✅ new |
| 3 | **Understand images** — a separate vision model (`google/gemma-4-31b-it`) reads images & image-only PDFs; the core text agent stays text-only | `LLMGateway.describe_image` | server | ✅ new |
| — | **Generic ingestion** — ingesting a file now *catalogs* it (summary + type); member/task extraction + invites is one optional consumer, not the purpose | `IngestionPipeline` | moderator+ | ✅ changed |

The headline new use case works end-to-end: the organizer uploads a **mail template**, says *"write the sponsor emails following this template"* → the agent lists the files, sees the template by its summary, reads it, drafts mail in that style, and routes the send through the existing HITL flow. **No invite logic touched.**

---

## The reframe: ingestion ≠ a use case

Before, [`IngestionPipeline.ingest`](../src/eventbuddy/ingestion/pipeline.py) ran *every* file through one lens (extract members/tasks → propose invites) and discarded the content. A mail template, agenda, budget, or image was wasted. Now:

```
download → parse → understand (summary + doc_type) → upsert catalog   ← ingestion's whole job
                                                                       (understand + remember, then stop)
        │
        ├─ list_event_files  → browse summaries + ids
        ├─ read_event_file   → live content (text via parsers, image via vision)
        └─ OPTIONAL consumer (doc_type ∈ {roster, planning}): extract members/tasks + propose invites
```

Invite-proposal demoted from *the* pipeline to *a* `doc_type`-gated handler (`_maybe_propose_invites`). A roster still proposes invites (Impl 2 behaviour preserved); every other file is simply catalogued and becomes readable.

---

## Vision: a separate model, not a core-model swap

The agent's chat brain stays a **text model** (`qwen/qwen3-5-27b`). Image understanding is an **isolated call** to a configurable vision model via `LLMGateway.describe_image` (base64 → OpenAI multimodal `content` array). `read_event_file` / the understand step call it and hand back **text** — the agent's tool-loop is never routed through the vision model. Confirmed working against the MaaS endpoint by [scripts/probe_vision.py](../scripts/probe_vision.py) (2026-06-14): `google/gemma-4-31b-it` accepts `image_url` content and reads images correctly.

---

## The flow

```
"what files are in this event?"
  → list_event_files: membership check → Graph get_channel_files_folder + list_children (live),
       enrich each file with its stored catalog summary/doc_type → bounded, untrusted-wrapped list

"write the sponsor emails like the template in the channel"
  → read_event_file(file_id): membership check → resolve channel folder → get_drive_item_content (LIVE)
       parse → text kind: parsed text (bounded 6000 chars)
                image/image_pdf: vision describe_image (image_pdf rendered to PNG first)
       lazy catalog backfill → untrusted-wrapped content
  → model drafts mail in that style → send_outlook_mail → existing HITL confirm card

no Graph creds / vision disabled / unsupported / oversized / non-member / empty channel
  → clean message, never raises
```

---

## What changed (files)

| Piece | What it does | File |
|---|---|---|
| Vision config | `LLM_VISION_MODEL` (default `google/gemma-4-31b-it`), `LLM_VISION_ENABLED` | [config.py](../src/eventbuddy/config.py) |
| Typed error | `LLMError` (vision/chat failures normalize to it) | [common/errors.py](../src/eventbuddy/common/errors.py) |
| Vision call | `LLMGateway.describe_image(bytes, mime, instruction)` — multimodal, separate model | [integrations/llm/client.py](../src/eventbuddy/integrations/llm/client.py) |
| Catalog columns | `Document.summary`, `Document.doc_type` (nullable) | [domain/models.py](../src/eventbuddy/domain/models.py) |
| Migration | `0006` adds the two columns | [alembic/versions/0006_document_catalog.py](../alembic/versions/0006_document_catalog.py) |
| Repo | `upsert(summary,doc_type)`, `set_understanding`, `list(event_id)` | [data/repositories/documents.py](../src/eventbuddy/data/repositories/documents.py) |
| Understand step | `understand(parsed) → {summary, doc_type}` (text via chat LLM, image via vision) | [ingestion/understand.py](../src/eventbuddy/ingestion/understand.py) *(new)* |
| Image parsing | image mimes → `kind="image"` (+raw_bytes/mime); text-empty PDF → `kind="image_pdf"`; `render_pdf_first_page` (guarded PyMuPDF) | [ingestion/parsers.py](../src/eventbuddy/ingestion/parsers.py) |
| Generic pipeline | understand+catalog; `_maybe_propose_invites` gated on `doc_type ∈ {roster,planning}` | [ingestion/pipeline.py](../src/eventbuddy/ingestion/pipeline.py) |
| Capability closures | `_build_list_event_files_fn`, `_build_read_event_file_fn`, shared `_resolve_channel_access`, `_read_image_file`, `_backfill_understanding`; vision wired into channel-ingest | [agent/wiring.py](../src/eventbuddy/agent/wiring.py) |
| Tools | `list_event_files`, `read_event_file` (any member, read-only, untrusted wrap) + no-op defaults; `AgentDeps` fields | [agent/tools.py](../src/eventbuddy/agent/tools.py) |
| System prompt | browse→read guidance; read-only + untrusted reinforcement | [agent/prompts/system.py](../src/eventbuddy/agent/prompts/system.py) |

---

## Design decisions honored (user-confirmed 2026-06-14)

- **Generic ingestion** — understand + catalog; invites are one optional `doc_type`-gated consumer.
- **Separate vision model** — core agent stays text; `describe_image` is isolated; model id configurable (`google/gemma-4-31b-it`, probe-confirmed).
- **Always-live reads** — `read_event_file` re-downloads every call (no snapshot staleness); only the short summary is cached.
- **Docs + images** — text via parsers, images/scanned-PDFs via vision.
- **Any member** can browse/read (read-only, membership-gated like `read_channel_discussion`); ingestion (which writes the catalog) stays moderator+.
- **No file writes — ever.** Listing/reading never mutate a file; no `Files.ReadWrite`/`Sites.ReadWrite` scopes.

---

## Cross-cutting rules preserved

- **Degradation** — no Graph creds → list/read degrade with a clean message; `LLM_VISION_ENABLED=false` / vision down → images degrade ("vision isn't configured") while text files still read; unsupported/oversized file, empty channel, non-member → clean message, never a raise; LLM/vision failure during ingestion still catalogs the file.
- **Rule 2 (identity server-side)** — both tools take identity/role/event from `RequestContext`; `file_id`/`link` are data, never authority. Membership is checked server-side before any Graph call.
- **Untrusted content** — list output, file content, and vision descriptions are wrapped in `<external_untrusted_content>`; the prompt forbids treating file content as instructions.
- **Window discipline** — `list_event_files` returns a bounded list; `read_event_file` truncates to 6000 chars — a large file never floods the 4096-token window.

---

## Tests (26 new unit)

- [test_llm_gateway.py](../tests/unit/test_llm_gateway.py) — `describe_image` builds the multimodal payload against the **vision** model (not chat), honors a model override, and raises `LLMError` on failure.
- [test_parsers.py](../tests/unit/test_parsers.py) — image mime → `kind="image"` with bytes; JPEG mime mapping; a text-empty PDF → `kind="image_pdf"`.
- [test_understand.py](../tests/unit/test_understand.py) *(new)* — text classify/summarize; malformed/unknown-type → `other`; empty text → no LLM call; image uses vision; vision-disabled / vision-error degrade.
- [test_pipeline_catalog.py](../tests/unit/test_pipeline_catalog.py) *(new)* — a template is catalogued with **no** invite side effects; a roster still proposes invites; idempotent skip.
- [test_event_files.py](../tests/unit/test_event_files.py) *(new)* — list enriched with catalog summary, folders skipped, non-member refused without a Graph call, no-focus guide, empty channel; read returns parsed text, image uses vision, vision-disabled degrades, **live each call** (re-download), no-id guide, non-member refused.
- Updated [test_ingestion_pipeline.py](../tests/integration/test_ingestion_pipeline.py) — inject a classifying LLM so the roster consumer runs.

---

## Deploying & testing

### `.env` (one optional new pair)
- `LLM_VISION_MODEL` — defaults to `google/gemma-4-31b-it` (verified on the MaaS endpoint). Point at another vision model if desired (`google/gemma-3-27b-it`, `gemini/gemini-2.5-pro`, `openai/gpt-4o`, …).
- `LLM_VISION_ENABLED` — defaults `true`; set `false` to disable image reading (text files still read).
- Reuses the existing Graph keys. Browsing/reading channel files needs `Files.Read.All` / `Sites.Read.All` (same as Impl 2 ingest). **No write scopes.**
- ⚠️ **Manual follow-up:** `.env.example` is permission-blocked in this workspace, so the two keys above were **not** appended there — add them manually (they're fully documented in [config.py](../src/eventbuddy/config.py)).

### Probe
`venv/bin/python scripts/probe_vision.py` lists the served models and confirms the vision endpoint accepts images. `VISION_MODEL=<id> venv/bin/python scripts/probe_vision.py` tests another model.

---

## Notes / deferred
- **Image-PDF rendering needs PyMuPDF** (`fitz`) — guarded import; absent → "couldn't render this PDF" (text-PDF path stays dependency-free). Add `pymupdf` to deploy deps to enable scanned-PDF reading.
- **Cached summary can lag a changed file** — content reads are always live; only the catalog summary is computed once. Delta-refresh (eTag/lastModified) deferred.
- **Flat folder only** — subfolders skipped (as in Impl 2/4); recursion deferred.
- **No pgvector RAG** — Impl 5 is browse-and-read, not semantic retrieval over the corpus (remains Phase 2).
- **Audio/video** (`whisper-large-v3` is on the endpoint) — deferred.
