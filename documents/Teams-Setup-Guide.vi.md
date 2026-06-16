# EventBuddy — Hướng dẫn cài đặt & sử dụng

🌐 [English](Teams-Setup-Guide.md) · **Tiếng Việt**

> Cách cài EventBuddy trong Microsoft Teams, đăng nhập, và bắt đầu sử dụng.
> Các bước chính không cần kiến thức kỹ thuật.

**Trang chính (tải ứng dụng tại đây):**
👉 https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/

**Tài liệu liên quan:** [Kiến trúc hệ thống](System-Architecture.vi.md) · [README](../README.vi.md)

---

## Bắt đầu trong 3 bước

### Bước 1 — Cài ứng dụng

1. Mở **[trang EventBuddy](https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/)** và bấm **Download** để tải `eventbuddy.zip`.
2. Trong **Microsoft Teams**, vào thanh bên trái → **Apps**.
3. Bấm **Manage your apps** (phía dưới) → **Upload an app** → **Upload a custom app**.
4. Chọn tệp **`eventbuddy.zip`** vừa tải.
5. Khi Teams hỏi thêm vào đâu, chọn **Add** (để có chat 1-1 — nơi dễ bắt đầu nhất). Bạn cũng có thể
   thêm vào **group chat** hoặc **kênh team** sau.

EventBuddy giờ mở ra trong một cuộc chat, như một đồng nghiệp.

> 💡 Không thấy **"Upload a custom app"**? Tổ chức của bạn có thể cần bật tính năng tải ứng dụng tuỳ
> chỉnh cho tài khoản của bạn — hãy nhờ quản trị viên IT/Teams (xem [phần dành cho
> admin](#dành-cho-quản-trị-viên-it-thiết-lập-một-lần)).

### Bước 2 — Đăng nhập

Lần đầu sử dụng, hãy kết nối EventBuddy với tài khoản Microsoft 365 của bạn để nó hành động thay bạn
(đọc tệp, gửi lời nhắc, tạo kênh).

1. Trong cuộc chat, chỉ cần gõ:

   ```
   sign in
   ```

2. EventBuddy trả lời kèm một nút **Sign in**. Bấm vào đó.
3. Một cửa sổ đăng nhập Microsoft mở ra — chọn tài khoản công ty của bạn và chấp thuận quyền truy cập.
4. Teams xác nhận đã kết nối. Xong — bạn đã sẵn sàng.

> Bạn chỉ cần làm việc này một lần. Nếu muốn kết nối lại bằng tài khoản khác hoặc làm mới quyền, hãy
> gõ **`sign out`** rồi **`sign in`** lại.
>
> EventBuddy cũng sẽ tự hiện nút **Sign in** lần đầu cần một quyền mà nó chưa có — chỉ cần bấm vào và
> hỏi lại.

### Bước 3 — Bắt đầu trò chuyện

Cứ nói với EventBuddy điều bạn muốn bằng ngôn ngữ tự nhiên. Thử:

- *"Tạo sự kiện tên Demo Day với thoptk và phucnlt2."*
- *"Tôi có những việc gì?"*
- *"Thêm việc đặt địa điểm, hạn 25/6."*

Đó là toàn bộ phần thiết lập. Phần còn lại của trang này cho biết **bạn có thể hỏi gì** và, ở cuối,
**các bước admin một lần** nếu EventBuddy chưa được thiết lập trong tổ chức của bạn.

---

## Bạn có thể hỏi EventBuddy điều gì

EventBuddy hiểu ngôn ngữ tự nhiên — bạn không cần câu lệnh chính xác. Nó hành xử hơi khác tuỳ vào nơi
bạn đã thêm nó.

### Trong chat 1-1 (chỉ mình bạn)
Bạn là người chủ trì ở đây. Vài câu nên nói:
- *"Tạo sự kiện tên Spring Hackathon với \<đồng nghiệp của bạn\>."*
- *"Tôi đang tham gia những sự kiện nào?"* → rồi *"Tập trung vào Spring Hackathon."*
- *"Tôi có những việc gì?"* / *"Thêm việc gửi thư mời, giao cho tôi, hạn thứ Sáu."*
- *"Viết báo cáo sau sự kiện."*

### Trong group chat (đội tổ chức của bạn)
Mọi người trong chat đều là cộng sự ngang hàng — ai cũng có thể nhờ EventBuddy làm bất cứ việc gì.
- *"Nhóm này là cho Spring Hackathon — hỗ trợ tụi mình tổ chức nhé."* (thiết lập sự kiện)
- *"Thêm những người mới trong chat này vào sự kiện."*
- *"Đọc participants.csv và nhắc những ai chưa đăng ký."*

### Trong kênh team
Kênh trở thành không gian làm việc chung của sự kiện. EventBuddy theo dõi thảo luận, nên bạn có thể hỏi:
- *"Tóm tắt những gì tụi mình đã bàn."*
- *"Tạo báo cáo cho sự kiện này."*

### Vài ví dụ tiện dụng
| Bạn nói… | EventBuddy làm… |
|---|---|
| *"Nhắc mọi người về hạn chót ngày mai."* | Soạn lời nhắc và hiện thẻ xác nhận trước khi gửi. |
| *"Gửi email lịch trình cho cả đội."* | Soạn email; bạn duyệt trước khi nó gửi đi. |
| *"Đọc tệp ngân sách và cho tôi biết tổng."* | Mở tệp được chia sẻ (Excel, Word, PDF, ảnh…) và trả lời. |
| *"Thêm việc in thẻ tên, giao cho Lan, hạn 20/6."* | Thêm vào bảng công việc của sự kiện. |

> 🔒 **Không gì được gửi mà chưa có sự đồng ý của bạn.** Mọi email, tin nhắn hay lời nhắc đều hiện
> **thẻ xác nhận** trước — bạn thấy chính xác ai nhận gì rồi mới bấm gửi.

---

## Xử lý sự cố

| Vấn đề | Hãy thử |
|---|---|
| **Không có "Upload a custom app"** | Admin cần bật tải ứng dụng tuỳ chỉnh cho tài khoản của bạn — xem bên dưới. |
| **EventBuddy nói cần quyền truy cập** | Gõ **`sign in`** và bấm nút, rồi hỏi lại. |
| **Nó đang hành động trên sai tài khoản** | Gõ **`sign out`**, rồi **`sign in`** và chọn đúng tài khoản. |
| **Một thao tác tệp/kênh báo chưa khả dụng** | Tính năng đó cần một quyền mà admin chưa cấp — xem bên dưới. EventBuddy vẫn hoạt động cho mọi việc khác. |

---

## Dành cho quản trị viên IT (thiết lập một lần)

> Bỏ qua hoàn toàn phần này nếu EventBuddy đã có sẵn trong tổ chức — người dùng cuối chỉ cần 3 bước
> phía trên. Phần này dành cho admin bật nó lần đầu.

EventBuddy đã được xây dựng và lưu trữ sẵn; bạn chỉ cần đăng ký danh tính của nó trong tenant
Microsoft và cho phép cài đặt.

**1. Đăng ký danh tính bot (Microsoft Entra)**
- Entra admin center → **App registrations → New registration** → tên `EventBuddy`,
  **single tenant**. Ghi lại **Application (client) ID** và **Directory (tenant) ID**.
- **Certificates & secrets → New client secret** → lưu lại giá trị.

**2. Tạo Azure Bot resource**
- Azure portal → tạo **Azure Bot** → "Use existing app registration" (ID ở trên).
- **Messaging endpoint:**
  `https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/api/messages`
- **Channels → Microsoft Teams → bật.**

**3. Cho phép cài đặt**
- Bật **tải ứng dụng tuỳ chỉnh (sideloading)** cho nhóm người dùng thử (nên dùng app-setup policy có
  phạm vi giới hạn thay vì thay đổi toàn tổ chức). Có thể mất tới 24h để có hiệu lực.

**4. Cấp quyền Microsoft 365 — theo giai đoạn**
EventBuddy dùng quyền Microsoft Graph **uỷ quyền (delegated)**: mỗi người tự đăng nhập (bước "sign
in" ở trên) và hành động với tư cách chính họ, nên bot chỉ làm được những gì người đó vốn đã làm
được. Các tính năng hội thoại không cần admin consent thêm. Khi bật các tính năng phong phú hơn, hãy
cấp các quyền sau và **admin-consent** các quyền uỷ quyền tương ứng:

| Tính năng | Quyền Graph (delegated) |
|---|---|
| Đọc/gửi tin nhắn kênh, tạo kênh sự kiện | `Channel.Create.All`, `ChannelMessage.Read.All`, `ChannelMessage.Send` |
| Đọc tệp SharePoint/OneDrive/Forms | `Files.Read.All`, `Sites.Read.All` |
| Gửi tin nhắn 1-1 / email phản hồi | `Chat.ReadWrite`, `Mail.Send` |

Vì EventBuddy **hạ cấp êm ái**, bạn có thể cấp từng quyền một — thiếu một quyền chỉ tắt một tính năng
chứ không làm hỏng bot.

**5. Phát hành (tuỳ chọn)**
Khi bản thử nghiệm ổn, hãy phát hành toàn tổ chức qua Teams Admin Center, lý tưởng là sau một
permission policy nhắm vào nhóm thử nghiệm trước.

### Tham chiếu nhanh cho admin

| Mục | Giá trị |
|---|---|
| Trang giới thiệu | `https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/` |
| Gói ứng dụng | `…/download/eventbuddy.zip` |
| Messaging endpoint | `…/api/messages` |
| Phạm vi cài đặt | `personal`, `team`, `groupChat` |

**Tham chiếu Microsoft:**
[Kết nối bot với Teams](https://learn.microsoft.com/en-us/azure/bot-service/channel-connect-teams?view=azure-bot-service-4.0) ·
[Tải ứng dụng tuỳ chỉnh](https://learn.microsoft.com/en-us/microsoftteams/platform/concepts/deploy-and-publish/apps-upload) ·
[Chính sách ứng dụng tuỳ chỉnh](https://learn.microsoft.com/en-us/microsoftteams/teams-custom-app-policies-and-settings)
