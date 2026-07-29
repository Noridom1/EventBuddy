# EventBuddy — Hướng dẫn Deploy lên GreenNode AgentBase

> Dành cho người **không rành kỹ thuật** cần tự deploy (hoặc redeploy) EventBuddy. Làm theo đúng
> thứ tự các bước, copy-paste các lệnh trong khung code. Nếu kẹt ở bước nào, xem mục
> [Xử lý sự cố](#12-xử-lý-sự-cố-thường-gặp) ở cuối bài.

**Companion docs:** [System Architecture](System-Architecture.md) (kiến trúc kỹ thuật) ·
[Teams Setup Guide](Teams-Setup-Guide.md) (hướng dẫn cho người dùng cuối, sau khi đã deploy xong)

---

## 0. Bức tranh tổng quan

```
Code (repo này) → build thành Docker image → GreenNode AgentBase "runtime"
       → runtime sinh ra một endpoint (URL công khai) → Azure Bot (đã đăng ký sẵn bởi IT)
       → Teams app (file eventbuddy.zip) → người dùng chat trong Microsoft Teams
```

Vài điều cần nắm trước khi làm:

- **Bot Teams (app id, bot id) đã được IT đăng ký sẵn từ trước** — deploy lại **không** tạo bot
  Teams mới. Việc bạn làm chỉ là build code mới và chạy nó trên một "runtime" của AgentBase.
- Mỗi runtime AgentBase có **một endpoint (URL) riêng**. Endpoint hiện tại đang chạy là:
  `https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn`
- **Nếu bạn deploy vào đúng runtime đang chạy (cùng tên), endpoint giữ nguyên** — không cần báo
  IT, chỉ cần deploy xong là bot dùng ngay code mới.
- **Chỉ khi nào tạo một runtime mới** (đổi tên runtime, đổi tài khoản GreenNode, hoặc runtime cũ
  đã bị xoá) thì mới sinh ra **endpoint mới** — lúc đó bắt buộc phải nhờ IT cập nhật lại
  "Messaging endpoint" trên Azure Bot, xem [bước 9](#9-bước-6--nếu-endpoint-bị-đổi-việc-cần-làm).

Vậy việc đầu tiên cần xác định: **bạn đang update bản đang chạy, hay dựng một bản hoàn toàn
mới?** Nếu không chắc, cứ làm hết các bước bên dưới — bước 8 sẽ cho biết endpoint có đổi hay không.

---

## 1. Trước khi bắt đầu — checklist

**Công cụ cần có sẵn trên máy** (nhờ ai đó rành kỹ thuật cài giúp nếu chưa có):
- `git`, `docker` (đang chạy), `make`, `jq`

**Thông tin/tài khoản cần xin trước khi bắt đầu:**

| Cần gì | Xin ở đâu |
|---|---|
| Tài khoản GreenNode có quyền IAM + AgentBase | Người quản lý hạ tầng GreenNode của team |
| `DATABASE_URL` và `REDIS_URL` **của bản đang chạy** (nếu chỉ update code) | Người deploy trước đó, hoặc file `.env` cũ |
| App Password (client secret) của bot Microsoft `Event-Buddy` | IT / Entra admin (secret chỉ hiện **một lần** lúc tạo — nếu mất phải nhờ IT reset) |
| (tuỳ chọn) Tavily API key, nếu muốn bật tính năng tìm kiếm web | Tài khoản Tavily của team |

---

## 2. Bước 1 — Lấy mã nguồn

```bash
git clone <repo-url-của-team>
cd EventBuddy
```

Nếu đã có sẵn thư mục này rồi thì chỉ cần lấy code mới nhất:

```bash
git pull
```

---

## 3. Bước 2 — Xác thực với GreenNode AgentBase (IAM)

Đây là bước "đăng nhập" để các lệnh `make deploy` được phép nói chuyện với GreenNode.

1. Vào **IAM Console**: https://iam.console.vngcloud.vn/service-accounts
2. Bấm **"Create service account"**, đặt tên dễ nhớ, ví dụ `eventbuddy-deploy`.
3. Vào tab **"Permission" → "Attach Policies"**, gắn 3 policy sau:
   - `AgentBaseFullAccess`
   - `vcrFullAccess`
   - `AiPlatformFullAccess`
4. Sau khi tạo xong, **copy ngay Client Secret** — nó chỉ hiển thị **một lần duy nhất**. Nếu lỡ
   đóng cửa sổ, vào tab **"Security credentials"** và bấm **"Reset"** để lấy secret mới.
5. Quay lại terminal, chạy:

   ```bash
   make creds
   ```

   Lệnh này sẽ hỏi `client_id` rồi `client_secret` (gõ secret sẽ không hiện ký tự trên màn hình,
   đó là bình thường). Thông tin được lưu vào file `.greennode.json` trong repo, không lưu ở đâu khác.

---

## 4. Bước 3 — Lấy LLM API Key (GreenNode AI Platform / MaaS)

EventBuddy cần một API key để gọi mô hình ngôn ngữ (LLM).

1. Vào **AI Platform console**: https://aiplatform.console.vngcloud.vn/models
2. Nếu team đã có sẵn một API key dùng cho EventBuddy, dùng lại key đó (hỏi người quản lý trước
   — key chỉ hiện được plaintext **lúc tạo**, sau đó không xem lại được nữa).
3. Nếu cần tạo key mới: vào mục **API Keys → Create**, đặt tên (chỉ chữ thường/số/gạch ngang,
   5–50 ký tự, ví dụ `eventbuddy-prod`), copy giá trị key hiện ra.
4. Ghi lại 2 giá trị sau — sẽ dùng ở bước viết file `.env`:
   - **Base URL** (cố định, không đổi): `https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1`
   - **API key**: giá trị vừa copy ở trên

> ⚠️ **Lưu ý tên biến:** nếu ai đó tạo key bằng công cụ tự động của Claude Code (`aip.sh`), key sẽ
> được lưu vào `.env` với tên `LLM_API_KEY` — **EventBuddy không đọc tên đó**. Trong file `.env`
> của repo này, tên biến bắt buộc phải là `AGENTBASE_LLM_API_KEY` và `AGENTBASE_LLM_BASE_URL` (xem
> bảng ở [bước 6](#6-bước-5--tạo-file-env)). Đổi tên lại nếu cần.

---

## 5. Bước 4 — Database (Postgres) & Redis

**Nếu bạn chỉ đang update code cho bản đang chạy (trường hợp phổ biến nhất):** dùng lại đúng
`DATABASE_URL` và `REDIS_URL` trong file `.env` cũ — **không tạo database mới**, vì dữ liệu sự
kiện/thành viên/task hiện tại đang nằm ở đó. Xin file `.env` cũ hoặc 2 giá trị này từ người deploy
trước.

**Nếu đây thực sự là một lần dựng mới hoàn toàn** (môi trường mới, chưa có Postgres/Redis nào):
- Postgres: tạo project mới trên [Supabase](https://supabase.com) → **Project Settings → Database
  → Connection string** → chọn kiểu **URI**. Đổi tiền tố từ `postgresql://` thành
  `postgresql+psycopg://` (EventBuddy dùng driver `psycopg`).
- Redis: tạo instance Redis quản lý (managed Redis) theo hạ tầng team đang dùng, lấy connection
  string dạng `redis://<user>:<password>@<host>:<port>/0`.

---

## 6. Bước 5 — Thông tin bot Microsoft Teams

Bot Teams **đã được IT đăng ký sẵn** — bạn chỉ cần điền lại đúng 3 giá trị này, không tự tạo mới:

| Biến `.env` | Giá trị | Ghi chú |
|---|---|---|
| `MICROSOFT_APP_ID` | `caa64604-fc25-43c9-9f46-6a9cea4d135e` | Client ID của app Entra "Event-Buddy" |
| `MICROSOFT_APP_PASSWORD` | *(xin IT)* | Client secret của app đó — chỉ hiện 1 lần lúc IT tạo; nếu không có, nhờ IT vào **Entra app → Certificates & secrets → New client secret** để cấp lại |
| `MICROSOFT_APP_TENANT_ID` | *(tenant id của công ty)* | Xin IT nếu chưa có |

Nếu IT đã cấu hình xong **OAuth Connection** cho tính năng "sign in" (đọc file, gửi mail/nhắc
việc thay mặt người dùng), điền thêm:

| Biến `.env` | Giá trị |
|---|---|
| `GRAPH_OAUTH_CONNECTION_NAME` | Tên connection IT đặt, ví dụ `eventbuddy-graph` |

> Nếu connection **chưa** tồn tại, **để trống** biến này — bot vẫn chat bình thường, chỉ các tính
> năng cần Microsoft Graph (đọc file, gửi mail, tạo kênh) sẽ tự động báo "chưa cấu hình" thay vì
> lỗi.

---

## 7. Bước 6 — Tạo file `.env`

Tạo file `.env` ở thư mục gốc của repo (cùng cấp với `README.md`), nội dung như dưới — thay các
giá trị `<...>` bằng giá trị thật đã lấy ở các bước trên:

```ini
# --- Database & cache (bước 4) ---
DATABASE_URL=<postgresql+psycopg://...>
REDIS_URL=<redis://...>

# --- LLM (bước 3) ---
AGENTBASE_LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
AGENTBASE_LLM_API_KEY=<api-key-của-bạn>

# --- Microsoft Bot Framework (bước 5) ---
MICROSOFT_APP_ID=caa64604-fc25-43c9-9f46-6a9cea4d135e
MICROSOFT_APP_PASSWORD=<client-secret-từ-IT>
MICROSOFT_APP_TENANT_ID=<tenant-id-từ-IT>

# --- Microsoft Graph (tuỳ chọn, để trống nếu IT chưa cấu hình xong) ---
GRAPH_OAUTH_CONNECTION_NAME=

# --- Tuỳ chọn khác ---
TAVILY_API_KEY=
LOG_LEVEL=INFO
```

Các biến khác trong app đều có giá trị mặc định hợp lý (xem `.env.example` trong repo để xem đầy
đủ danh sách) — **không cần điền thêm gì nữa** để có một bản deploy chạy được.

**Không commit file `.env` lên git** — nó chứa mật khẩu/secret thật. File này chỉ nằm trên máy
bạn và được AgentBase đọc lúc deploy.

---

## 8. Bước 7 — Deploy

Chạy:

```bash
make deploy
```

Lệnh này tự động: build Docker image → đẩy (push) image lên registry của GreenNode → tạo runtime
mới **hoặc cập nhật runtime đã có sẵn cùng tên** → chờ runtime chuyển sang trạng thái `ACTIVE` →
tự kiểm tra `/health`. Toàn bộ mất khoảng **5–10 phút**, log sẽ in tiến trình từng bước.

**Điểm quan trọng nhất:** mặc định lệnh này deploy vào runtime tên **`EventBuddy`**. Nếu bản đang
chạy hiện tại **cũng** tên là `EventBuddy` (kiểm tra bằng lệnh dưới), `make deploy` sẽ **cập
nhật** runtime đó — endpoint giữ nguyên, không cần báo IT. Muốn kiểm tra tên/trạng thái runtime
hiện có trước khi deploy:

```bash
make status
```

Nếu output báo "No runtime named EventBuddy" trong khi bot vẫn đang chạy ở URL cũ, nghĩa là bản
đang chạy dùng **tên runtime khác** — hỏi lại người deploy trước để lấy đúng tên, rồi chạy:

```bash
make deploy RUNTIME_NAME=<tên-đúng>
```

---

## 9. Bước 8 — Kiểm tra sau khi deploy

```bash
make status     # trạng thái runtime (phải là ACTIVE)
make endpoint    # in ra URL endpoint hiện tại
make health      # gọi thử /health, phải trả về HTTP 200
```

So sánh URL từ `make endpoint` với URL cũ ở đầu tài liệu này (hoặc URL trên README/landing page
hiện tại):

- **Giống nhau** → xong, bỏ qua bước 9, bot đã chạy code mới ngay.
- **Khác nhau** → làm tiếp [bước 9](#10-bước-9--nếu-endpoint-bị-đổi-việc-cần-làm) bên dưới, bắt
  buộc phải cập nhật lại Azure Bot mới dùng được trong Teams.

---

## 10. Bước 9 — Nếu endpoint bị đổi: việc cần làm

Endpoint mới **chưa có tác dụng gì trong Teams** cho tới khi làm xong 3 việc sau:

### a. Cập nhật Messaging Endpoint trên Azure Bot

Cần quyền truy cập Azure (thường là IT). Vào **Azure Portal → Azure Bot resource "Event-Buddy" →
Configuration**, đổi **Messaging endpoint** thành:

```
<endpoint-mới>/api/messages
```

### b. Cập nhật Teams app package (`validDomains`)

File `teams-app/manifest.json` khai domain cũ trong mảng `validDomains`. Sửa lại thành host mới
(chỉ phần domain, không kèm `https://`), ví dụ:

```json
"validDomains": [
  "<host-mới, ví dụ endpoint-xxxx.agentbase-runtime.aiplatform.vngcloud.vn>",
  "token.botframework.com",
  "*.botframework.com",
  "login.microsoftonline.com",
  "*.microsoftonline.com",
  "login.microsoft.com",
  "login.live.com"
]
```

Sau đó đóng gói lại file zip **trước khi deploy lần nữa** (để bản zip mới được đóng gói sẵn trong
image, tải được từ landing page):

```bash
bash teams-app/build.sh
make deploy
```

Nếu app đã được tải lên (sideload) trong Teams từ trước, phải **gỡ ra và upload lại**
`teams-app/eventbuddy.zip` mới (Teams → Apps → Manage your apps → app cũ → Remove → Upload a
custom app lại). Nếu app đã publish org-wide qua Teams Admin Center, việc này do IT thực hiện lại.

### c. Báo cho IT

Gửi tin nhắn/email theo mẫu dưới đây — chỉ báo **endpoint đổi**, mọi thứ khác (bot id, quyền
Graph, scope) giữ nguyên như lần setup trước:

> **Chủ đề:** Cập nhật messaging endpoint cho bot EventBuddy
>
> Chào anh/chị, EventBuddy vừa được deploy lại trên một runtime mới nên endpoint công khai đã
> đổi. Nhờ anh/chị cập nhật giúp trên Azure Bot resource **"Event-Buddy"**:
>
> - **Messaging endpoint mới:** `<endpoint-mới>/api/messages`
> - **Domain cần thêm vào validDomains (nếu team quản lý manifest tập trung):**
>   `<host-mới>`
>
> Mọi thứ khác (App ID `caa64604-fc25-43c9-9f46-6a9cea4d135e`, quyền Graph delegated, OAuth
> connection) giữ nguyên, không cần cấu hình lại. Cảm ơn anh/chị!

(Tham khảo thêm mẫu đầy đủ ở `__documents__/EventBuddy-IT-Onboarding-Request-Compact.md` nếu đây
là lần đầu đăng ký bot, chứ không phải chỉ đổi endpoint.)

---

## 11. Việc còn lại — kiểm tra trong Teams

Sau khi Azure Bot + Teams app package đã trỏ đúng endpoint mới:

1. Vào Teams, chat với EventBuddy (hoặc upload lại `teams-app/eventbuddy.zip` nếu chưa cài).
2. Gõ `sign in` để kết nối tài khoản Microsoft 365 (nếu dùng tính năng Graph).
3. Thử một câu đơn giản: *"What are my tasks?"* hoặc *"Create an event called Test Event"*.

Xem chi tiết trải nghiệm người dùng ở [Teams Setup Guide](Teams-Setup-Guide.md).

---

## 12. Xử lý sự cố thường gặp

| Vấn đề | Cách xử lý |
|---|---|
| `make deploy` báo "IAM credentials missing" | Chạy lại `make creds` |
| `make deploy` báo lỗi 401 khi gọi API | Token hết hạn, thử lại — script tự làm mới token |
| Runtime kẹt ở trạng thái `ERROR` lâu | Xem log: `make logs`. Thường do `.env` thiếu biến bắt buộc hoặc sai `DATABASE_URL`/`REDIS_URL` |
| `make health` không trả 200 sau khi deploy xong | Container có thể còn đang khởi động — đợi thêm 1–2 phút rồi `make health` lại; nếu vẫn lỗi, xem `make logs` |
| Bot trong Teams không phản hồi | Kiểm tra Messaging endpoint trên Azure Bot có đúng endpoint hiện tại không (mục 10a) |
| Bot báo thiếu quyền / tính năng Graph không chạy | Bình thường nếu `GRAPH_OAUTH_CONNECTION_NAME` chưa cấu hình — bot vẫn chat được, chỉ tính năng liên quan file/mail/kênh bị tắt |
| Upload app trong Teams không thấy nút "Upload a custom app" | IT cần bật custom-app upload cho tài khoản của bạn |

---

## 13. Cheat sheet — các lệnh hay dùng

```bash
make creds       # lưu thông tin đăng nhập GreenNode IAM (làm 1 lần)
make deploy      # build + push + tạo/cập nhật runtime + health check
make status      # xem trạng thái runtime
make endpoint    # in URL endpoint hiện tại
make health      # kiểm tra /health
make logs        # xem log runtime (khi có lỗi)
make destroy     # XOÁ runtime (cẩn thận — không thể hoàn tác)
```
