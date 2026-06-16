# EventBuddy — Kiến trúc hệ thống

🌐 [English](System-Architecture.md) · **Tiếng Việt**

> Một bot Microsoft Teams điều hành trọn vòng đời sự kiện — tạo → tập trung → nhắc → báo cáo — qua
> một agent hội thoại duy nhất. Tài liệu này giải thích nó được xây dựng thế nào.

**Đối tượng:** kỹ sư và người review muốn hiểu EventBuddy hoạt động ra sao.
**Tài liệu liên quan:** [Hướng dẫn cài đặt Teams](Teams-Setup-Guide.vi.md) · [README](../README.vi.md)

---

## 1. Nó là gì, trong một đoạn

EventBuddy là một **trợ lý AI lấy sự kiện làm trung tâm** dành cho những người tổ chức sự kiện nội
bộ (Event Organizer, Employee Engagement, L&D). Nó sống bên trong Microsoft Teams dưới dạng một bot.
Người tổ chức nói chuyện với nó như với một đồng nghiệp giỏi — *"nhóm này là cho Spring Hackathon,
hỗ trợ tụi mình tổ chức nhé"*, *"thêm việc gửi email cảm ơn, hạn 20/6"*, *"nhắc tất cả những ai chưa
đăng ký"*, *"viết báo cáo sau sự kiện"* — và agent thực thi công việc: dựng không gian làm việc
riêng cho sự kiện, đọc tệp kế hoạch, gửi lời nhắc đa kênh được cá nhân hoá, và tạo báo cáo kèm gợi ý
cho lần sau.

Nó được thiết kế sao cho **mọi phụ thuộc bên ngoài đều hạ cấp êm ái**: không có thông tin xác thực
LLM → vẫn có bộ định tuyến regex tất định trả lời; không Redis → trạng thái hội thoại trong bộ nhớ
RAM; không Microsoft Graph → dữ liệu sự kiện lưu cục bộ. Bot không bao giờ sập cứng chỉ vì thiếu một
tích hợp.

---

## 2. Vấn đề nó giải quyết

Tổ chức một sự kiện nội bộ là một vòng đời cố định, lặp đi lặp lại, tốn của người tổ chức **4–6 giờ
làm thủ công, mỗi lần**:

```
thông báo → phát phiếu đăng ký → thúc đăng ký → nhắc trước ngày D
        → thu thập phản hồi → viết báo cáo sau sự kiện
```

Mỗi bước đều là điều phối thủ công: copy-paste danh sách thành viên, đi thúc từng người chưa phản
hồi, gõ lại cùng một lời nhắc trên cả email lẫn chat, và ráp báo cáo bằng tay. Người tổ chức thường
chạy **2–3 sự kiện cùng lúc**, nên gánh nặng nhân lên và các ngữ cảnh lẫn vào nhau.

EventBuddy gom tất cả vào một bề mặt hội thoại duy nhất. Mô tả sự kiện một lần; agent giữ ngữ cảnh
từng sự kiện tách biệt (`event_id` phân vùng mọi thứ) và làm phần việc lặp lại.

---

## 3. Kiến trúc tổng quan

Ba lối vào (ingress) đổ về một lõi bot. Lõi này chạy một agent LLM gọi tool, hành động qua một lớp
tool có kiểu rõ ràng và được kiểm soát quyền, tác động lên Microsoft 365 và các kho dữ liệu.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          CÁC CLIENT MICROSOFT TEAMS                            │
│     Chat 1-1 (personal)      Group chat       Kênh team          Outlook       │
└───────────┬───────────────────────┬───────────────────┬──────────────┬────────┘
            │  Hoạt động Bot Framework (qua Azure Bot Service)          │ Graph
            ▼                                                           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  INGRESS (FastAPI)   /api/messages   /api/webhooks/graph   /api/forms   /health │
│                      + trang landing tại  /   + dev-only  /api/dev/handle         │
└───────────────────────────────┬────────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  BOT GATEWAY        CloudAdapter (kiểm tra JWT) · EventBuddyBot ·               │
│                     phân giải scope + role · thẻ xác nhận HITL                    │
└───────────────────────────────┬────────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  AGENT (LangGraph create_react_agent)                                           │
│  Orchestrator (điểm định tuyến) → vòng lặp tool LLM  ──hoặc──  bộ định tuyến regex│
│  bộ nhớ ba lớp: cửa sổ Redis → bản ghi Postgres → bản tóm tắt cuộn                │
└───────────────────────────────┬────────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  LỚP TOOL (theo từng yêu cầu, gắn ngữ cảnh)                                      │
│  create_event · setup_event · create_task · update_task · prepare_reminders ·    │
│  send_outlook_mail · send_teams_message · read_event_file · generate_report · …  │
└───────────────────────────────┬────────────────────────────────────────────────┘
            ┌────────────────────┼─────────────────────┬─────────────────────┐
            ▼                    ▼                     ▼                     ▼
┌────────────────┐   ┌────────────────────┐  ┌──────────────────┐  ┌────────────────┐
│  CAPABILITIES  │   │  SCHEDULER         │  │  LỚP DỮ LIỆU      │  │  TÍCH HỢP       │
│ provisioning · │   │ APScheduler:       │  │ Postgres (ORM) ·  │  │ MS Graph ·      │
│ reminders ·    │   │ job làm mới        │  │ Redis (cửa sổ +   │  │ MaaS LLM ·      │
│ reporting ·    │   │ bản tóm tắt cuộn   │  │ session)          │  │ Tavily web      │
│ ingestion · …  │   │                    │  │                   │  │ (tuỳ chọn)      │
└────────────────┘   └────────────────────┘  └──────────────────┘  └────────────────┘
```

**Vì sao có hình dạng này.** Tệp tải lên, lời nhắc và phản hồi đều xảy ra bất đồng bộ, nên đường xử
lý yêu cầu của agent được tách khỏi công việc theo thời gian (scheduler) và khỏi việc gửi ra ngoài
(phản hồi là cuộc gọi *đi ra* trở lại Microsoft, không phải phản hồi HTTP). Phân lớp giúp mỗi mối
quan tâm có thể kiểm thử độc lập và để agent suy luận trên một bề mặt tool nhỏ, rõ ràng.

---

## 4. Luồng yêu cầu

Một tin nhắn từ Teams đi theo một đường cố định; cùng một điểm `handle(...)` phục vụ mọi scope.

```
Teams → Azure Bot Service → POST /api/messages  (api/messages.py)
      → CloudAdapter (kiểm tra JWT của Bot Framework)  (bot/adapter.py)
      → EventBuddyBot  (bot/activity_router.py)      — phân giải scope, danh tính, sự kiện đang tập trung
      → wrapper LangGraph, một node `orchestrate`     (agent/graph.py)
      → Orchestrator.handle(...)                       (agent/orchestrator.py)  ← điểm định tuyến
          ├─ agent_mode="llm" + có creds → runner gọi tool bằng LLM (agent/runner.py)
          └─ khi có lỗi / agent_mode="regex" / thiếu creds → bộ định tuyến regex tất định
```

Bot Framework **không** theo kiểu request/response. `POST /api/messages` trả về `200 OK` như một
*ack*; phản hồi thực sự là một **cuộc gọi đi ra** từ container trở lại Bot Connector tại `serviceUrl`
của hoạt động. Tin nhắn chủ động (lời nhắc theo lịch, leo thang) tái sử dụng đúng đường đi ra đó qua
một conversation reference đã lưu — đó là lý do scheduler có thể nhắn cho người dùng mà không cần
kích hoạt từ phía vào.

Cũng có một route chỉ dùng cho dev `POST /api/dev/handle` (chỉ gắn khi `DEV_ROUTES_ENABLED=true`) để
bỏ qua xác thực Bot Framework, phục vụ kiểm thử đa lượt ở cục bộ.

---

## 5. Orchestrator — hạ cấp êm ái như một nguyên tắc thiết kế

**Orchestrator** ([`agent/orchestrator.py`](../src/eventbuddy/agent/orchestrator.py)) là điểm định
tuyến duy nhất. Chữ ký `handle(...)` ổn định nên bên gọi không bao giờ phải đổi. Bên trong:

- Khi `agent_mode="llm"` và có runner LLM, nó gọi runner gọi tool.
- Khi gặp **bất kỳ** lỗi nào, hoặc `agent_mode="regex"`, hoặc thiếu thông tin xác thực LLM, nó **hạ
  cấp về bộ định tuyến regex tất định** vẫn xử lý được các động từ cốt lõi.

Đây là điều cốt lõi, không phải tiện ích phụ. Toàn hệ thống được dựng để hạ cấp thay vì sập:

| Phụ thuộc bị thiếu | Hành vi |
|---|---|
| Thông tin xác thực MaaS / LLM | Quay về bộ định tuyến regex |
| Redis | Cửa sổ hội thoại dùng checkpointer trong RAM |
| Thông tin xác thực Microsoft Graph | `create_event` lưu cục bộ; tính năng kênh/tệp/mail báo chưa khả dụng |
| Cơ sở dữ liệu lúc khởi động | App vẫn phục vụ; tính năng bộ nhớ hạ cấp |

**Wiring** ([`agent/wiring.py`](../src/eventbuddy/agent/wiring.py)) là nơi lắp ráp. Nó định nghĩa các
closure năng lực (`provision_fn`, `remind_fn`, `report_fn`, …) **một lần** và dùng chung giữa bộ định
tuyến regex và thân tool LLM (DRY), rồi `build_orchestrator()` chọn regex-hay-LLM dựa trên thông tin
xác thực hiện có và `agent_mode`.

---

## 6. Agent runner

Runner ([`agent/runner.py`](../src/eventbuddy/agent/runner.py)) bọc vòng lặp gọi tool
`create_react_agent` của LangGraph.

- **Model và checkpointer là singleton dùng chung**; **tool và system prompt được dựng lại theo từng
  yêu cầu** để gắn `RequestContext` của người gọi (xem §8).
- Một `pre_model_hook` **cắt cửa sổ làm việc xuống ≤4096 token**, chỉ cắt tại ranh giới
  human/assistant (`start_on="human"`) để không bao giờ làm mồ côi một `tool_call_id` — mồ côi sẽ làm
  hỏng API của LLM.
- Khi cửa sổ Redis rỗng, runner **gieo trạng thái ban đầu từ bản tóm tắt cuộn + đuôi bản ghi** để hội
  thoại tiếp tục có ngữ cảnh sau khi cửa sổ hết hạn.
- Mọi lần gọi tool trong lượt được ghi vào một trace theo yêu cầu; lỗi được phân loại (lỗi do mô hình
  → thử lại; lỗi hệ thống → thông báo gọn cho người dùng), và có thể bật footer debug để hiển thị
  agent đã làm gì.

---

## 7. Bộ nhớ ba lớp

Cả ba lớp đều được khoá theo `thread_id` nhận biết scope: `event:{channel_id}` cho kênh chia sẻ,
`dm:{user_id}` cho chat 1-1.

1. **Cửa sổ làm việc** — checkpointer Redis của LangGraph với TTL 24h
   ([`agent/memory.py`](../src/eventbuddy/agent/memory.py)). Hạ cấp về `InMemorySaver` khi không có
   Redis. Một `session_lock` tuần tự hoá các post đồng thời vào cùng một thread `event:`.
2. **Bản ghi bền vững** — bảng `conversation_messages` trên Postgres
   ([`agent/transcript.py`](../src/eventbuddy/agent/transcript.py)). Chỉ lưu **lượt người dùng/trợ
   lý** (tin nhắn tool-call/result bị bỏ). Flush idempotent qua mốc high-water theo từng thread; tái
   tạo cửa sổ rỗng từ các lượt gần nhất trong ngân sách.
3. **Bản tóm tắt cuộn** — bảng `session_summaries` trên Postgres
   ([`agent/summarizer.py`](../src/eventbuddy/agent/summarizer.py)). Một bản tóm tắt gọn, đang chạy,
   của mọi thứ cũ hơn đuôi tái tạo, được làm mới **ngoài luồng** bằng một job APScheduler (không thêm
   độ trễ cho mỗi lượt). `covered_through` là mốc nước.

Bộ ba này giúp hội thoại mạch lạc vượt xa cửa sổ 4096 token mà không phải gửi lại toàn bộ lịch sử
cho mô hình ở mỗi lượt.

---

## 8. Danh tính, scope, và bất biến bảo mật

**Mô hình không bao giờ giả mạo được danh tính người gọi.** Danh tính, vai trò, scope và sự kiện
đang tập trung đến từ một **`RequestContext` do máy chủ dựng**
([`agent/context.py`](../src/eventbuddy/agent/context.py)) được giữ trong closure tạo tool theo từng
yêu cầu — chúng **không bao giờ là tham số của tool**. Mô hình quyết định *hành động gì*; nó không
quyết định được *nó đang hành động với tư cách ai*.

Vai trò **phụ thuộc scope**, được phân giải một lần và đọc ở mọi nơi:

| Scope | Vai trò được phân giải | Vì sao |
|---|---|---|
| **Chat 1-1** (`personal`) | `host` | Người dùng là người dẫn dắt sự kiện, hành động riêng tư. |
| **Group chat** (`group`) | `moderator` (mọi người) | Group chat là không gian ngang hàng, chỉ mời — ai cũng được hành động. |
| **Kênh team** (`channel`) | vai trò `EventMember.role` thật của người gọi (mặc định `member`) | Có nền team; vai trò tổ chức có ý nghĩa và thành viên là nguồn sự thật. |

Kiểm soát vai trò dùng `ROLE_RANK` từ [`bot/auth.py`](../src/eventbuddy/bot/auth.py)
(`member < moderator < host`). Hai lớp bảo vệ nữa che chắn các tác động gửi ra ngoài:

- **Thẻ xác nhận HITL** — mọi hành động gửi ra ngoài (mail, tin nhắn Teams, lời nhắc) đều cần một xác
  nhận Adaptive-Card tường minh; không gì gửi đi âm thầm. Thẻ phân giải lại vai trò người gọi tại
  thời điểm bấm, nên việc cấp quyền luôn nhất quán.
- **Đóng khung chống prompt-injection** — văn bản bên ngoài/không tin cậy (tin nhắn kênh, trang web
  lấy về, nội dung tệp) được bọc trong một bao `external_untrusted_content` trước khi tới mô hình,
  nên nó được coi là dữ liệu tham chiếu, không bao giờ là chỉ thị.

---

## 9. Năng lực (bề mặt tool của agent)

Năng lực nằm trong [`capabilities/`](../src/eventbuddy/capabilities/) và được phơi cho LLM dưới dạng
tool có kiểu trong [`agent/tools.py`](../src/eventbuddy/agent/tools.py). Docstring của mỗi tool chính
là mô tả hướng tới mô hình. Bề mặt hiện tại:

| Nhóm | Tool | Ghi chú |
|---|---|---|
| **Thiết lập sự kiện** | `create_event`, `setup_event`, `set_focus_event`, `list_my_events`, `sync_event_members` | Dựng từ chat 1-1, hoặc gắn group/kênh vào sự kiện và thêm thành viên theo danh tính công ty. |
| **Công việc** | `create_task`, `update_task`, `list_my_tasks`, `list_event_tasks` | Bảng việc qua hội thoại; ai cũng tạo/sửa việc của mình, moderator/host sửa được mọi việc. |
| **Nhắc nhở & gửi tin** | `prepare_reminders`, `send_outlook_mail`, `send_email`, `send_teams_message`, `send_participant_reminders` | Đều có HITL. `send_teams_message` hỗ trợ cá nhân hoá từng người với thẻ xác nhận gộp/tách. |
| **Tệp & trí tuệ** | `list_event_files`, `read_event_file`, `read_participant_file`, `ingest_event_files`, `read_channel_discussion` | Mô tả→khớp→đọc trên tệp chat/kênh; xlsx/docx/pdf/csv qua parser, ảnh/scan qua vision model. |
| **Thành viên & ngữ cảnh** | `list_members`, `get_event_context` | Danh sách nhận biết scope; ảnh chụp ngữ cảnh sự kiện xuyên ngữ cảnh. |
| **Phản hồi & báo cáo** | `set_feedback_sources`, `generate_report` | Gắn Form + bảng tính phản hồi; tạo báo cáo sau sự kiện bằng AI. |
| **Web (tuỳ chọn)** | `web_search`, `web_fetch` | Chỉ đăng ký khi Tavily được cấu hình — agent không quảng cáo năng lực mà deployment không làm được. |

---

## 10. Lớp dữ liệu

SQLAlchemy 2.0 ORM trong [`domain/models.py`](../src/eventbuddy/domain/models.py); repository trong
[`data/repositories/`](../src/eventbuddy/data/repositories/). Mọi ghi đều đi qua context manager
`session_scope()` ([`data/db.py`](../src/eventbuddy/data/db.py)) — commit khi thành công, rollback khi
có ngoại lệ.

- **Postgres** (Supabase) — sự kiện, thành viên, công việc, báo cáo, phản hồi, danh mục tệp chat,
  job theo lịch, audit log, và các bảng bản ghi bền vững + bản tóm tắt cuộn.
- **Redis** — checkpointer cửa sổ làm việc của LangGraph (TTL 24h) và trạng thái session/lượt.

Migration nằm trong [`alembic/versions/`](../alembic/); `alembic/env.py` tiêm URL cơ sở dữ liệu và
import các model để autogenerate thấy chúng. Entrypoint của container chạy `alembic upgrade head` khi
khởi động, theo kiểu best-effort — một trục trặc DB không làm app ngừng phục vụ.

---

## 11. Lập lịch & công việc nền

Một APScheduler chạy trong tiến trình ([`scheduler/`](../src/eventbuddy/scheduler/)) bên trong
lifespan của FastAPI. Job chính hôm nay làm mới **bản tóm tắt cuộn** ngoài luồng, để việc tóm tắt
không bao giờ thêm độ trễ cho lượt của người dùng. Chính cơ chế gửi-phản-hồi-đi-ra (một conversation
reference đã lưu) cho phép công việc theo lịch gửi lời nhắc chủ động mà không cần kích hoạt từ phía vào.

---

## 12. Tích hợp bên ngoài

- **Microsoft Graph** — tạo kênh, đọc/gửi tin nhắn kênh, truy cập tệp SharePoint/OneDrive, và mail
  Outlook. Chỉ dùng cho các tính năng chủ động/kênh/tệp/mail; đường phản hồi hội thoại **không** cần
  quyền Graph. Tích hợp tenant của dự án dùng quyền Graph uỷ quyền (delegated) sau một luồng OAuth
  bằng thẻ đăng nhập.
- **MaaS (Model-as-a-Service)** — một endpoint LLM tương thích OpenAI (GreenNode). ID model có
  **namespace** (vd. `qwen/qwen3-5-27b`); ID trần sẽ 404. Bộ não chat phải phát ra `tool_calls`
  OpenAI sạch.
- **Tavily** (tuỳ chọn) — tìm/đọc web cho brainstorm và sự thật bên ngoài.

---

## 13. Triển khai

EventBuddy là một **Custom Agent** trên **GreenNode AgentBase** — một host container tổng quát. Hợp
đồng nền tảng rất tối giản: container **lắng nghe cổng 8080** và phơi **`GET /health`** trả về 200
khi sẵn sàng. Mọi thứ khác (các route) là của ta.

```
Teams client → Azure Bot Service (Bot Connector) → AgentBase public endpoint → container :8080
```

Hai đăng ký nằm **ngoài** AgentBase, trong tenant Microsoft: một **Azure Bot resource** (có messaging
endpoint là `https://<agentbase-endpoint>/api/messages`) và **Teams app manifest** (gói được tải
lên). URL endpoint của AgentBase là chất keo — nó vừa là messaging endpoint của bot vừa là URL
webhook Graph. Các kho dữ liệu (Supabase Postgres, Redis quản lý) **không** thuộc runtime; chúng được
truy cập trực tiếp qua public TLS.

API không trạng thái (session sống trong Redis), nên nó co giãn theo chiều ngang. Luồng triển khai
được gói trong `make deploy` (build → push lên registry quản lý → tạo/cập nhật runtime → health-check).
Xem [README](../README.vi.md#phát-triển-cục-bộ) để biết lệnh và [Hướng dẫn cài đặt
Teams](Teams-Setup-Guide.vi.md) cho phần đấu nối phía Microsoft.

---

## 14. Bản đồ codebase

```
src/eventbuddy/
├── main.py                 # Khởi tạo app FastAPI + lifespan (khởi động scheduler)
├── config.py               # pydantic-settings, lấy từ env
├── api/                    # Bề mặt HTTP: messages, webhooks, forms, health, landing, dev
├── bot/                    # Adapter Bot Framework, định tuyến hoạt động, auth/role, thẻ xác nhận HITL
├── agent/                  # bộ não: orchestrator, runner, tools, wiring, bộ nhớ 3 lớp, prompts
├── capabilities/           # mỗi module một tính năng vòng đời (dựng kênh, nhắc, báo cáo, ingestion…)
├── domain/                 # Model SQLAlchemy + logic nghiệp vụ (sự kiện, thành viên, công việc, báo cáo)
├── data/                   # engine/session db, redis, repositories
├── ingestion/              # luồng parse tệp → LLM cấu trúc hoá → ghi DB
├── integrations/           # lớp DUY NHẤT nói chuyện với hệ thống bên ngoài (Graph, LLM, web)
├── scheduler/              # job APScheduler (làm mới bản tóm tắt cuộn) + trigger
└── common/                 # logging, errors, ids
```

**Ranh giới:** `api/` và `bot/` không biết gì về SQL; `domain/` không biết gì về Bot Framework;
`integrations/` là lớp duy nhất nói chuyện với hệ thống bên ngoài; `agent/wiring.py` là điểm lắp ráp
mọi thứ. Sự tách bạch đó là điều khiến hạ cấp êm ái khả thi — một tích hợp bị thiếu chỉ tắt một năng
lực thay vì làm hỏng bot.
