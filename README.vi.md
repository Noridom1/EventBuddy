<p align="center">
  <img src="documents/assets/banner.png" alt="EventBuddy" width="320">
</p>

<h1 align="center">EventBuddy</h1>

<p align="center">
  <strong>Trợ lý AI quản lý trọn vòng đời sự kiện của bạn — ngay trong Microsoft Teams.</strong>
</p>

<p align="center">
  Tạo → tập trung → nhắc nhở → báo cáo, tất cả chỉ trong một cuộc trò chuyện.
</p>

<p align="center">
  🌐 <a href="https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/"><strong>Trang giới thiệu &amp; cài đặt</strong></a>
  &nbsp;·&nbsp;
  📖 <a href="documents/Teams-Setup-Guide.vi.md">Hướng dẫn cài đặt Teams</a>
  &nbsp;·&nbsp;
  🏗 <a href="documents/System-Architecture.vi.md">Kiến trúc hệ thống</a>
</p>

<p align="center">
  🌐 <a href="README.md">English</a> · <strong>Tiếng Việt</strong>
</p>

---

## Vấn đề

Tổ chức một sự kiện nội bộ luôn lặp lại đúng một vòng đời cố định:

```
thông báo → phát phiếu đăng ký → thúc đăng ký → nhắc trước ngày D
        → thu thập phản hồi → viết báo cáo sau sự kiện
```

Với người tổ chức (đội Event Organizer / Employee Engagement / L&D), đó là **4–6 giờ làm thủ công
cho mỗi sự kiện** — copy-paste danh sách thành viên, đi nhắc từng người chưa phản hồi, gõ lại cùng
một lời nhắc trên cả email lẫn chat, rồi ngồi ráp báo cáo bằng tay. Họ thường chạy **2–3 sự kiện
cùng lúc**, nên việc vặt nhân lên và các ngữ cảnh lẫn vào nhau.

**EventBuddy gom tất cả vào một cuộc trò chuyện.** Bạn mô tả sự kiện một lần; tác nhân (agent) giữ
ngữ cảnh của từng sự kiện tách biệt và làm phần điều phối lặp đi lặp lại — dựng không gian làm việc,
đọc tài liệu kế hoạch, gửi lời nhắc được cá nhân hoá, và viết báo cáo kèm gợi ý cho lần sau.

---

## Bạn có thể làm gì với nó

EventBuddy hoạt động qua hội thoại — bạn mô tả điều mình cần và nó làm phần việc còn lại. Các tình
huống bên dưới đi theo **vòng đời sự kiện**, từ lúc khởi động đến lúc ra báo cáo. Tất cả đều là việc
agent thực sự làm được hôm nay; các câu trích chỉ là ví dụ — bạn không cần gõ chính xác từng chữ.

### 1. 🎬 Khởi tạo sự kiện và không gian làm việc
Biến một cuộc trò chuyện thành một sự kiện được tổ chức. Trong chat 1-1, tạo sự kiện cùng đội tổ
chức. Trong group chat hoặc kênh, chỉ cần nói nhóm đó là cho một sự kiện — EventBuddy nhận cuộc trò
chuyện đó làm không gian làm việc chung và bắt đầu theo dõi. Đang chạy nhiều sự kiện cùng lúc? Liệt
kê chúng và *tập trung* vào một cái, mọi điều bạn nói tiếp theo sẽ áp dụng cho nó.
> 💬 *"Tạo sự kiện tên Spring Hackathon với thoptk và phucnlt2."*
> 💬 *"Nhóm này là cho Spring Hackathon — hỗ trợ tụi mình tổ chức nhé."*
> 💬 *"Tôi đang tham gia sự kiện nào?"* → *"Tập trung vào Hackathon."*

### 2. 👥 Dựng đội ngũ và danh sách khách
Thêm người tổ chức theo danh tính công ty, để mỗi người được nhận diện trong chính chat riêng của họ
với bot. Tách biệt với đó, đọc một **danh sách người tham dự** (tệp xlsx/csv) để biết ai sẽ đến và ai
còn cần thúc — người tham dự luôn tách bạch với đội tổ chức.
> 💬 *"Thêm những người mới trong nhóm này vào sự kiện."*
> 💬 *"Đọc participants.csv và cho tôi biết ai chưa đăng ký."*

### 3. ✅ Theo dõi công việc
Giữ một bảng công việc chung bằng ngôn ngữ tự nhiên — tạo việc, giao việc, đặt hoặc dời hạn, và cập
nhật trạng thái. Hỏi riêng việc của bạn, hoặc cả bảng với từng người phụ trách.
> 💬 *"Thêm việc đặt địa điểm, giao cho Lan, hạn 25/6."*
> 💬 *"Đánh dấu việc lo ăn uống đã xong."* · *"Còn việc gì chưa làm?"*

### 4. 📣 Nhắc nhở và gửi tin — không còn copy-paste
Gửi lời nhắc, email, hoặc tin nhắn Teams trực tiếp — cho cả đội, cho người cụ thể, hoặc chỉ cho những
người trong danh sách **chưa đăng ký**. Cần mỗi người nhận một nội dung *khác nhau*? Cá nhân hoá theo
từng người trong cùng một đợt. **Mọi lần gửi đều hiện thẻ xác nhận trước**, nên không gì gửi đi cho
đến khi bạn duyệt chính xác ai nhận gì.
> 💬 *"Nhắc mọi người về hạn chót ngày mai."*
> 💬 *"Chỉ thúc những người tham dự còn đang chờ (pending)."*
> 💬 *"Nhắn cho mỗi diễn giả giờ phiên của họ."* (mỗi người một nội dung khác nhau)

### 5. 📂 Làm việc với tệp và thảo luận
Duyệt và đọc các tệp được chia sẻ trong chat hoặc kênh — lịch trình, ngân sách, mẫu email, danh sách
— chỉ theo tên, không cần link. EventBuddy hiểu **tài liệu Office, PDF, CSV và văn bản**, và đọc
**ảnh cùng PDF scan** bằng mô hình thị giác (vision model). Nó cũng có thể nắm bắt và brainstorm
quanh phần thảo luận của kênh.
> 💬 *"Đọc tệp ngân sách và cho tôi biết tổng."*
> 💬 *"Tóm tắt những gì tụi mình đã bàn và gợi ý một chủ đề."*

### 6. 📊 Thu thập phản hồi và viết báo cáo
Gắn một **Form** phản hồi cùng bảng tính phản hồi của nó vào sự kiện, rồi để EventBuddy tạo một **báo
cáo sau sự kiện bằng AI** — bản tóm tắt kèm gợi ý cụ thể, dựa trên dữ liệu, để làm sự kiện lần sau
tốt hơn.
> 💬 *"Dùng Form này để thu phản hồi."* → sau đó → *"Viết báo cáo sau sự kiện."*

### 7. 🌍 Nghiên cứu trên web (tuỳ chọn)
Khi web search được bật, EventBuddy có thể tra cứu thông tin bên ngoài hoặc tìm cảm hứng cho ý tưởng.
> 💬 *"Tìm các hoạt động icebreaker cho một hackathon 50 người."*

> **Ai được làm gì** phụ thuộc vào phạm vi (scope): trong chat 1-1 bạn là *host*; group chat là không
> gian ngang hàng nơi *mọi người* đều được hành động; kênh team dùng vai trò thành viên thật. Mô hình
> **không bao giờ** giả mạo được danh tính người gọi — danh tính luôn đến từ máy chủ, không phải từ
> cuộc trò chuyện.

---

## Dùng thử

| | |
|---|---|
| **Trang giới thiệu** | https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/ |
| **Cài đặt** | Tải `eventbuddy.zip` từ trang giới thiệu → Teams **Apps → Manage your apps → Upload a custom app** |
| **Hướng dẫn đầy đủ** | [Hướng dẫn cài đặt Teams](documents/Teams-Setup-Guide.vi.md) |

Sau khi cài, mở chat 1-1 với EventBuddy, gõ **`sign in`** và bấm nút để kết nối tài khoản Microsoft
365 — rồi cứ nói chuyện với nó: *"Tạo sự kiện tên Demo Day với \<đồng nghiệp của bạn\>"* → *"tôi có
những việc gì?"*

---

## Cách hoạt động

```
Teams (DM · group chat · kênh)
        │  Hoạt động Bot Framework (qua Azure Bot Service)
        ▼
FastAPI ingress  →  Bot Gateway (JWT + scope/role)  →  Orchestrator (điểm định tuyến)
                                                          │
                          ┌───────────────────────────────┴───────────────────────────┐
                          ▼                                                             ▼
              LangGraph create_react_agent                                  bộ định tuyến regex
              (vòng lặp gọi tool bằng LLM)                                   (phương án dự phòng)
                          │
                          ▼
              tool có kiểu, gắn ngữ cảnh  →  capabilities  →  Postgres · Redis · MS Graph · MaaS LLM
```

- **Một điểm định tuyến, hai bộ não.** Orchestrator chạy agent gọi tool bằng LLM, và khi gặp *bất kỳ*
  lỗi nào (hoặc thiếu thông tin xác thực) sẽ **hạ cấp về bộ định tuyến regex tất định**. Bot không
  bao giờ sập chỉ vì thiếu một tích hợp — không LLM → regex; không Redis → bộ nhớ tạm trong RAM;
  không Graph → chỉ lưu cục bộ.
- **Bộ nhớ ba lớp** giữ cuộc trò chuyện mạch lạc vượt ngoài cửa sổ ngữ cảnh của mô hình: cửa sổ làm
  việc Redis (≤4096 token, 24h) → bản ghi bền vững trên Postgres → bản tóm tắt cuộn được làm mới
  ngoài luồng.
- **An toàn từ thiết kế:** danh tính, vai trò và phạm vi đến từ `RequestContext` do máy chủ dựng theo
  từng yêu cầu — chúng không bao giờ là tham số của tool, nên mô hình không thể giả mạo người gọi.
  Các hành động gửi ra ngoài đều có xác nhận của con người (HITL); văn bản không tin cậy được đóng
  khung để không bao giờ bị thực thi như chỉ thị.

Xem thiết kế đầy đủ trong **[Kiến trúc hệ thống](documents/System-Architecture.vi.md)**.

---

## Nhìn nhanh vào codebase

```
src/eventbuddy/
├── main.py          # Khởi tạo app FastAPI + lifespan (khởi động scheduler)
├── config.py        # pydantic-settings, lấy từ env; mọi thứ hạ cấp khi thiếu creds
├── api/             # Lớp HTTP — /api/messages, /api/webhooks/graph, /api/forms, /health, landing
├── bot/             # Adapter Bot Framework, định tuyến hoạt động, auth scope/role, thẻ xác nhận HITL
├── agent/           # ★ bộ não — orchestrator, runner, tools, wiring, bộ nhớ 3 lớp, prompts
├── capabilities/    # mỗi module một tính năng vòng đời (dựng kênh, nhắc nhở, báo cáo, ingestion…)
├── domain/          # Mô hình SQLAlchemy 2.0 + logic nghiệp vụ (sự kiện, thành viên, công việc, báo cáo)
├── data/            # engine/session DB, redis, repositories
├── ingestion/       # luồng parse tệp → LLM cấu trúc hoá → ghi vào DB
├── integrations/    # lớp DUY NHẤT nói chuyện với hệ thống bên ngoài (Graph, LLM, web)
├── scheduler/       # job APScheduler (làm mới bản tóm tắt cuộn)
└── common/          # logging, errors, ids
```

**Bắt đầu đọc từ đâu:** [`agent/orchestrator.py`](src/eventbuddy/agent/orchestrator.py) (điểm định
tuyến) → [`agent/wiring.py`](src/eventbuddy/agent/wiring.py) (nơi lắp ráp) →
[`agent/tools.py`](src/eventbuddy/agent/tools.py) (toàn bộ bề mặt năng lực của agent; docstring của
mỗi tool chính là mô tả của nó).

**Ranh giới giữa các lớp rất chặt:** `api/` và `bot/` không biết gì về SQL; `domain/` không biết gì
về Bot Framework; `integrations/` là nơi duy nhất chạm tới hệ thống bên ngoài; `agent/wiring.py` là
điểm lắp ráp tất cả. Đó là điều khiến việc hạ cấp êm ái trở nên khả thi.

---

## Công nghệ sử dụng

| Lớp | Lựa chọn |
|---|---|
| Runtime | Python 3.12 · FastAPI · bố cục `src/` |
| Agent | LangGraph `create_react_agent` · tool LangChain |
| Teams | Bot Framework SDK (`CloudAdapter`) · Adaptive Cards |
| LLM | Endpoint MaaS tương thích OpenAI (GreenNode) |
| Dữ liệu | Postgres (Supabase) qua SQLAlchemy 2.0 · Redis · migration Alembic |
| Nền | APScheduler (chạy trong tiến trình) |
| Hosting | GreenNode AgentBase (container Custom Agent, cổng 8080 + `/health`) |
| Bên ngoài | Microsoft Graph · Tavily web search (tuỳ chọn) |

---

## Phát triển cục bộ

Chạy từ thư mục gốc (các target chuyển tiếp tới `deployment/Makefile`, dùng `venv/`):

```bash
make run      # uvicorn ở :8080
make test     # unit test (mặc định bỏ qua integration test)
make lint     # ruff check src/ tests/
```

```bash
# Một test đơn lẻ
venv/bin/python -m pytest tests/unit/test_runner.py::test_name -q

# Integration test (cần Postgres/Redis chạy thật)
docker compose -f deployment/docker-compose.yml up -d db redis
venv/bin/python -m pytest -m integration

# Migration DB (entrypoint của container cũng chạy lệnh này khi khởi động)
venv/bin/alembic upgrade head
```

**Triển khai lên AgentBase:** `make creds` (lưu IAM secret, tương tác) → `make deploy` (build, push,
tạo/cập nhật runtime, health-check). Xem `make status` / `make endpoint` / `make health` / `make logs`.

Cấu hình lấy từ môi trường qua `pydantic-settings` — xem [`.env.example`](.env.example) để biết đầy
đủ các khoá. **Mọi thứ hạ cấp êm ái khi thiếu thông tin xác thực**, nên bạn có thể chạy một phần hữu
ích ở cục bộ mà không cần quyền truy cập Microsoft/cloud.

---

## Tài liệu

| Tài liệu | Nội dung |
|---|---|
| **[Kiến trúc hệ thống](documents/System-Architecture.vi.md)** | Toàn bộ thiết kế — luồng yêu cầu, Orchestrator, bộ nhớ ba lớp, mô hình bảo mật, lớp dữ liệu, triển khai. |
| **[Hướng dẫn cài đặt Teams](documents/Teams-Setup-Guide.vi.md)** | Từng bước: cài vào Teams, đăng nhập, và cuộc trò chuyện đầu tiên. |
| [CLAUDE.md](CLAUDE.md) | Hướng dẫn cho lập trình viên/người đóng góp khi làm việc trong repo này. |

---

<p align="center"><sub>Được xây dựng bởi <strong>Bit By Bit</strong> trên GreenNode AgentBase.</sub></p>
