# EventBuddy — Yêu cầu tích hợp Teams gửi IT (Entra Admin)

**Gửi:** IT / Microsoft Entra administrator
**Từ:** Nhóm phát triển EventBuddy
**Ngày:** 15-06-2026
**Mục đích:** đăng ký một bot Microsoft Teams nội bộ ("EventBuddy") trong tenant của công ty để chạy thử (pilot) một cách an toàn.

Bốn thông tin anh/chị yêu cầu — **name, endpoint, scope, permissions** — ở §1; chi tiết Graph permission ở §2. **Toàn bộ truy cập Graph là delegated** (bot hành động thay mặt người dùng đã đăng nhập) — **không** xin bất kỳ application permission toàn tenant nào.

---

## 1. Bốn thông tin anh/chị yêu cầu

| Thông tin | Giá trị |
|---|---|
| **Tên app / bot** | `EventBuddy` |
| **Messaging endpoint** | `https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/api/messages` |
| **Endpoint host (dùng cho validDomains)** | `endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn` |
| **Install scope** | `personal` (chat 1:1) + `team` (channel) |
| **Account type** | **Single-tenant** (chỉ trong tổ chức này) |
| **Graph permissions** | **Chỉ delegated** — xem §2. |

Endpoint đã hoạt động (public HTTPS). Anh/chị có thể kiểm tra nhanh host trả về phản hồi trước khi cấu hình.

---

## 2. Microsoft Graph permissions (delegated)

Bot đăng nhập người dùng qua **Teams SSO** và hành động **thay mặt họ**, nên mọi lệnh gọi Graph đều bị giới hạn trong **những gì người dùng đó vốn đã được truy cập** — không bao giờ đọc được dữ liệu tenant mà người dùng không có quyền (vd OneDrive của người khác). Phần trả lời hội thoại của bot **không cần** Graph permission nào.

| Khả năng | Delegated scope | Ghi chú |
|---|---|---|
| Đăng nhập / nhận diện người dùng (SSO) | `openid`, `profile`, `email`, `User.Read` | Nền tảng Teams SSO; khai báo qua `webApplicationInfo` trong manifest |
| Duy trì cho các tác vụ gửi theo lịch | `offline_access` | Refresh token để job nhắc việc/feedback chạy nền sau này, hành động thay mặt người đã đặt lịch |
| Tạo Teams channel cho event | `Channel.Create` | Thay mặt người dùng (phải là thành viên/owner của team) |
| Đọc & tải file trong channel (SharePoint) | `Files.Read.All` + `Sites.Read.All` | **Delegated** — chỉ những file người dùng vốn mở được |
| Phân giải email công ty → định danh Teams của thành viên | `User.ReadBasic.All` | Map email roster → id Teams/AAD để nhận diện thành viên được mời |
| Gửi email thông báo / đăng ký / nhắc việc / feedback | `Mail.Send` | Gửi **với tư cách mailbox của chính người đăng nhập** (không dùng shared mailbox) |
| Đọc thảo luận channel | `ChannelMessage.Read.All` | Thay mặt người dùng |
| Đăng nhắc việc / thông báo / confirm card vào channel | `ChannelMessage.Send` | Thay mặt người dùng (hoặc qua Bot Framework proactive — không cần Graph) |

> Đây là các scope **delegated** — app **không** có quyền truy cập toàn tenant độc lập; truy cập luôn bị giới hạn theo người dùng đã đăng nhập. Admin có thể **grant admin consent một lần** cho các scope này (để người dùng không bị hỏi consent từng người), hoặc để consent theo từng người. Việc thiết lập cũng cần cấu hình **OAuth connection / SSO** trên Azure Bot + Entra app (expose một API scope `access_as_user`).

---

## 3. Vì sao việc test trong Teams production (có giới hạn) là an toàn

Một Teams bot chỉ nhìn thấy chat/channel mà nó **được thêm vào một cách rõ ràng**. Với truy cập Graph **delegated**, nó còn chỉ chạm tới dữ liệu mà **người dùng đã đăng nhập** vốn được truy cập — bản thân bot không có credential nào vươn tới toàn tenant. Khi chỉ cài vào một **test team do chúng tôi làm owner** và chỉ bật custom-app upload cho tài khoản của chúng tôi, bot **không hiển thị với phần còn lại của tổ chức**. Chỉ xin publish toàn tổ chức **sau khi** test sandbox đạt yêu cầu.

**Một lưu ý thẳng thắn:** email nhắc việc/feedback theo lịch sẽ chạy sau khi không có ai đăng nhập, nên chúng tái sử dụng một **refresh token đã lưu** (`offline_access`) và hành động *thay mặt host đã đặt lịch*. Token đó có thể hết hạn hoặc bị thu hồi (đổi mật khẩu/MFA), khi đó các lần gửi nền sẽ tạm dừng đến khi host đăng nhập lại — đây là sự đánh đổi có chủ đích để giữ bot ở mức quyền tối thiểu.

---

*Tài liệu đi kèm: [EventBuddy-Teams-Integration-Guide.md](EventBuddy-Teams-Integration-Guide.md) và app package trong [`teams-app/`](../teams-app/).*
