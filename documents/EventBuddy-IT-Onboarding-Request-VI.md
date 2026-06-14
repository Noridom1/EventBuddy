# EventBuddy — Yêu cầu tích hợp Teams gửi IT (Entra Admin)

**Gửi:** IT / Microsoft Entra administrator
**Từ:** Nhóm phát triển EventBuddy
**Ngày:** 14-06-2026
**Mục đích:** đăng ký một bot Microsoft Teams nội bộ ("EventBuddy") trong tenant của công ty để có thể chạy thử (pilot) một cách an toàn.

Đây là tài liệu độc lập, đầy đủ. Bốn thông tin anh/chị yêu cầu — **name, endpoint, scope, permissions** — nằm ở §1. Phần cần IT **thực hiện** ở §2; phần cần **gửi lại** cho chúng tôi ở §3.

---

## 1. Bốn thông tin anh/chị yêu cầu

| Thông tin | Giá trị |
|---|---|
| **Tên app / bot** | `EventBuddy` |
| **Messaging endpoint** | `https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/api/messages` |
| **Endpoint host (dùng cho validDomains)** | `endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn` |
| **Install scope** | `personal` (chat 1:1) + `team` (channel) |
| **Account type** | **Single-tenant** (chỉ trong tổ chức này) |
| **Graph permissions** | **Yêu cầu toàn bộ ngay từ đầu** để test end-to-end — xem §4. |

Endpoint đã hoạt động (public HTTPS, AgentBase runtime). Anh/chị có thể kiểm tra nhanh là host trả về phản hồi trước khi cấu hình.

---

## 2. Những việc cần IT thực hiện

### 2.1 Tạo Entra app registration (bắt buộc)
- **Entra admin center → App registrations → New registration**
- Name: `EventBuddy`
- Supported account types: **Single tenant** (Accounts in this organizational directory only)
- Sau khi tạo: **Certificates & secrets → New client secret** (lưu ý ngày hết hạn — expiry).

### 2.2 Tạo Azure Bot resource (bắt buộc)
- Azure portal → tạo một **Azure Bot** resource.
- App type: **Single-tenant**; chọn **use the existing app registration** từ bước 2.1 (dán App ID vào).
- **Configuration → Messaging endpoint:** URL ở §1.
- **Channels → Microsoft Teams → bật (enable) → Save.**

> Nếu anh/chị muốn *chúng tôi* tự tạo Azure Bot resource, vui lòng cấp cho chúng tôi quyền **Contributor** trên một subscription hoặc resource group, chúng tôi sẽ tự thực hiện bước 2.2.

### 2.3 Bật custom app upload cho tài khoản test của chúng tôi (bắt buộc để pilot)
- **Teams admin center → Teams apps → Setup policies.**
- Hoặc đặt **Global (Org-wide default)** mục "Upload custom apps" thành **On**, **hoặc** (khuyến nghị — phạm vi ảnh hưởng nhỏ hơn) tạo một **app setup policy mới** với "Upload custom apps" = On và chỉ gán cho **tài khoản developer của chúng tôi**.
- Lưu ý: thiết lập này có thể mất **đến 24 giờ** để có hiệu lực.

### 2.4 Cấp (hoặc xác nhận) một test team
- Một **test team riêng do chúng tôi làm owner** ("EventBuddy Sandbox") với vài thành viên tình nguyện, để chúng tôi có thể cài/gỡ bot tự do và consent các permission ở phạm vi team một cách biệt lập. Chúng tôi **chưa** cần app hiển thị toàn tổ chức (org-wide).

### 2.5 Thêm và admin-consent các Microsoft Graph application permissions ở §4 (bắt buộc để test đầy đủ)
- Trên app registration EventBuddy: **API permissions → Add a permission → Microsoft Graph → Application permissions** → thêm các permission liệt kê ở §4 → **Grant admin consent**.
- Riêng khả năng **đọc** tin nhắn channel: team owner sẽ consent permission **RSC** lúc cài đặt (đã khai báo trong manifest) — không cần grant toàn tenant cho mục này.

### 2.6 Cung cấp mailbox người gửi cho email outbound (bắt buộc nếu test tính năng email)
- Bot gửi email *với tư cách một mailbox có thật* (`Mail.Send` application không tự tạo mailbox). Vui lòng **tạo hoặc chỉ định một mailbox** cho bot — vd shared mailbox `eventbuddy@vng.com.vn` — và gửi địa chỉ cho chúng tôi.
- Khuyến nghị: gắn một **Application Access Policy** để app EventBuddy **chỉ** được gửi từ mailbox đó (không phải từ user bất kỳ). Chúng tôi sẽ cấu hình bot gửi đúng từ địa chỉ này.

---

## 3. Những thông tin cần gửi lại cho chúng tôi

1. **Application (client) ID** của app registration EventBuddy.
2. **Directory (tenant) ID**.
3. Giá trị **client secret** — vui lòng gửi qua kênh bảo mật (không gửi email thường).
4. Xác nhận **Teams channel đã được bật** trên Azure Bot resource.
5. Xác nhận **custom app upload** đã bật cho tài khoản của chúng tôi (và tên **test team** / xác nhận chúng tôi có quyền owner).
6. **Địa chỉ mailbox người gửi** (§2.6) mà bot được phép dùng để gửi email.

Chúng tôi sẽ nạp các giá trị 1–3 vào cấu hình runtime của bot. Để test end-to-end đầy đủ, chúng tôi cũng cần các Graph permissions ở §4 được thêm và admin-consent (§2.5).

---

## 4. Microsoft Graph permissions — bộ đầy đủ để test end-to-end

Chúng tôi muốn kiểm thử **toàn bộ** hệ thống (tạo channel, đọc file trong channel, tra cứu thành viên, gửi email, đọc thảo luận channel), nên xin cấp bộ permission đầy đủ ngay từ đầu. Phần **trả lời hội thoại của bot vẫn không cần Graph permission nào** — mọi mục bên dưới phục vụ một khả năng cụ thể:

| Khả năng cần test | Permission | Loại / cách cấp | Ghi chú |
|---|---|---|---|
| Tạo Teams channel cho event | `Channel.Create.All` | Application — admin consent | Hoặc `Group.ReadWrite.All` nếu policy của IT thiên về grant ở mức group |
| Đọc & tải file trong channel (SharePoint) | `Files.Read.All` + `Sites.Read.All` | Application — admin consent | Phạm vi rộng. Có thể thu hẹp bằng **`Sites.Selected`** giới hạn vào site của test team — xem §5 |
| Tra cứu hồ sơ thành viên (tên, email, id) | `User.Read.All` | Application — admin consent | Phân giải email trong roster → user record |
| Đọc roster / thành viên của team | `TeamMember.Read.All` | Application — admin consent | Ai đang ở trong team/event |
| Gửi email thông báo / feedback | `Mail.Send` | Application — admin consent | Phạm vi rộng (có thể gửi từ mọi mailbox). Vui lòng giới hạn bằng **Application Access Policy** chỉ cho mailbox EventBuddy — xem §5 |
| Đọc thảo luận channel | `ChannelMessage.Read.Group` | **RSC** — team owner consent lúc cài đặt | Đã có trong manifest. **Ưu tiên hơn** `ChannelMessage.Read.All` toàn tenant, vốn là **"protected API"** của Microsoft cần gửi yêu cầu phê duyệt riêng |

**Đăng tin nhắn vào channel/chat** được xử lý **không cần Graph permission bổ sung**: bot đăng **chủ động (proactive) qua Bot Framework connector** sau khi đã được cài vào team/chat. (Việc gửi tin nhắn channel *với tư cách app qua Graph* bản thân nó là protected API, nên chúng tôi chủ động tránh hướng này.)

> Tóm lại: chỉ các mục sau cần **admin consent toàn tenant**: `Channel.Create.All`, `Files.Read.All`, `Sites.Read.All`, `User.Read.All`, `TeamMember.Read.All`, `Mail.Send`. Đọc channel dùng **RSC** (không cần grant tenant); gửi tin nhắn channel/chat dùng **Bot Framework** (không cần grant Graph).

---

## 5. Lưu ý về xử lý dữ liệu (vui lòng xem xét)

EventBuddy lưu transcript hội thoại và bản tóm tắt (rolling summary) trong **cloud Postgres (Supabase) và Redis**, kết nối qua public TLS. Điều này nghĩa là một phần dữ liệu hội thoại của công ty (tin nhắn channel được yêu cầu tóm tắt, thông tin event/thành viên) sẽ **đi qua và lưu bên ngoài tenant Microsoft 365**. Chúng tôi nêu ra để IT đối chiếu với các chính sách data-residency hoặc DLP trước khi mở rộng. Sẵn sàng trao đổi về các biện pháp kiểm soát (region, retention, encryption) nếu cần.

**Thu hẹp phạm vi các permission rộng (khuyến nghị).** Vì các application permission ở §4 có phạm vi toàn tenant, chúng tôi sẵn sàng áp dụng các biện pháp thu hẹp sau cho giai đoạn test:
- **`Sites.Selected`** thay cho `Files.Read.All` + `Sites.Read.All` — chỉ cấp quyền truy cập file vào **site SharePoint của test team** mà IT chỉ định, không gì khác.
- Một **Application Access Policy** trên `Mail.Send` — giới hạn bot chỉ gửi từ một **mailbox EventBuddy** chỉ định, không phải mọi user.
- **Secret có thời hạn ngắn** (vd 90 ngày) và **app registration riêng cho Graph** tách khỏi identity của bot, nếu IT muốn cô lập phần consent quyền cao.

---

## 6. Vì sao việc test trong Teams production (có giới hạn) là an toàn

Một Teams bot chỉ nhìn thấy được:
- các chat/channel mà nó **được thêm vào một cách rõ ràng**, và
- (với Graph) chỉ dữ liệu mà **permissions / RSC consent đã cấp** cho phép.

Bằng cách chỉ bật upload cho tài khoản của chúng tôi (§2.3) và chỉ cài vào một **test team do chúng tôi làm owner** (§2.4), bot sẽ **không hiển thị với phần còn lại của tổ chức** và phần *nhắn tin* của nó (trả lời, đăng chủ động) bị giới hạn ở nơi nó được cài. RSC consent áp dụng theo từng team. Chúng tôi sẽ chỉ xin publish toàn tổ chức (Teams Admin Center, có policy giới hạn nhóm pilot) **sau khi** bài test trong sandbox đạt yêu cầu.

**Một lưu ý thẳng thắn:** các **application** Graph permission toàn tenant ở §4 (`Files`/`Sites`/`User`/`TeamMember`/`Mail.Send`) *không* bị giới hạn trong test team — về mặt kỹ thuật, credential của bot có thể đọc các tài nguyên đó trên toàn tenant. Các biện pháp thu hẹp ở §5 (`Sites.Selected`, Application Access Policy cho mail, app Graph riêng, secret thời hạn ngắn) sẽ kéo phạm vi đó về đúng phạm vi test. Chúng tôi sẵn sàng áp dụng bất kỳ biện pháp nào IT yêu cầu.

---

*Tài liệu đi kèm (phía developer): [EventBuddy-Teams-Integration-Guide.md](EventBuddy-Teams-Integration-Guide.md) (kiến trúc & runbook đầy đủ) và app package trong [`teams-app/`](../teams-app/) (manifest + build).*
