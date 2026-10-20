# Báo cáo phần TV5 — Telegram, thống kê và kiểm thử

## Phạm vi bàn giao

- Endpoint `POST /alerts` nhận đúng JSON §C, tra chủ monitor và gửi cảnh báo tới
  `notification_channels` loại `telegram`.
- Ghép user với chat qua mã một lần, có thời hạn; endpoint tạo mã chỉ nhận lời
  gọi nội bộ có `TELEGRAM_LINK_API_KEY`.
- Lệnh `/status [giờ]`, `/report daily|weekly`, `/help`, `/stop`.
- Tự gửi báo cáo ngày/tuần theo múi giờ cấu hình; lưu kỳ đã gửi để không gửi lặp
  sau khi restart.
- Thống kê uptime, tổng lượt kiểm tra, latency trung bình, sự cố mới/đã phục hồi/
  đang mở, phân theo user và từng monitor.

## Công thức thống kê

- `uptime (%) = số lần kiểm tra UP / tổng số lần kiểm tra × 100`.
- Latency trung bình lấy các kết quả UP có `response_time_ms`.
- Báo cáo cộng cả `check_results` còn thô và `check_rollups` theo giờ, để số liệu
  tuần không mất phần lịch sử mà TV1 đã gom. Schema rollup không lưu số mẫu
  latency riêng; latency lịch sử là xấp xỉ, lấy trung bình bucket có trọng số theo
  số lần UP (cùng cách tính của helper uptime trong core).
- “Sự cố mới” đếm `started_at` trong khoảng báo cáo; “đã phục hồi” đếm
  `resolved_at` trong khoảng; “đang mở” đếm incident còn trạng thái `open` tại
  thời điểm lập báo cáo.
- Báo cáo ngày bao phủ ngày lịch vừa kết thúc; báo cáo tuần bao phủ thứ Hai đến
  hết Chủ nhật vừa qua. Khoảng thời gian được đổi sang UTC trước khi truy vấn.

## Kết quả kiểm thử

| Mã | Kịch bản | Kết quả mong đợi | Kết quả |
|---|---|---|---|
| TV5-01 | TV1 POST cảnh báo `down` đúng schema; monitor có chủ và chat đã liên kết | Gửi một tin đúng chat, có severity/nguyên nhân | Đạt |
| TV5-02 | Gọi tạo mã ghép không có internal key | Từ chối HTTP 401 | Đạt |
| TV5-03 | User nhận mã và gửi `/start <code>` | Lưu `notification_channels`; mã chỉ dùng một lần | Đạt |
| TV5-04 | Gửi `/status 24` khi có 1 lần UP, 1 lần DOWN | Uptime 50%, latency lấy từ lần UP | Đạt |
| TV5-05 | Webhook Telegram dùng secret sai; alert sai cấu trúc | Từ chối webhook HTTP 401 và payload HTTP 422 | Đạt |
| TV5-06 | Đến lịch ngày và tuần có dữ liệu giả | Tạo hai báo cáo với uptime/sự cố đúng | Đạt |
| TV5-07 | Chạy lại scheduler trong cùng kỳ | Không gửi báo cáo trùng | Đạt |

Kiểm thử tự động dùng SQLite tạm và Telegram client giả lập. Chúng xác nhận luồng
HTTP → DB → định tuyến chat và thống kê, nhưng không thay cho kiểm thử với bot
Telegram thật, Postgres của TV4 hoặc backend TV2 đã triển khai.

**Kết quả chạy:** `telegram-bot/`: 4 passed; `monitoring-core/`: 20 passed.
Tổng cộng 24 test passed, không có test thất bại.

Lệnh chạy tại `telegram-bot/`:

```bash
python -m pytest -q
```

## Kịch bản demo tích hợp

| Bước | Thao tác | Kết quả trình bày |
|---|---|---|
| 1 | TV4 khởi động Postgres, `monitoring-core`, `backend-api` và `telegram-bot`; mở trang tài khoản và yêu cầu mã ghép | Backend hiển thị mã có hạn dùng; `/health` trả `status: ok` |
| 2 | Mở bot Telegram, gửi `/start <mã>` rồi `/status 24` | Bot xác nhận ghép; bảng `notification_channels` có chat ID; lệnh trả số liệu theo user |
| 3 | Tạo monitor thử nghiệm trỏ tới một dịch vụ HTTP có thể bật/tắt | Monitor xuất hiện trong dashboard và thuộc đúng user |
| 4 | Dừng dịch vụ; chờ đủ số lần lỗi `retries` | Core mở incident; TV1 POST sự kiện `down`; Telegram nhận một tin đỏ |
| 5 | Khởi động lại dịch vụ; chờ ngưỡng phục hồi | Incident được resolve; Telegram nhận tin phục hồi màu xanh |
| 6 | Gửi `/report daily` và `/report weekly`; chờ giờ gửi đã cấu hình để xem báo cáo định kỳ | Số lượt, uptime, latency và sự cố khớp dữ liệu ở dashboard/DB |

Khi demo với hạ tầng thật, cần cấu hình domain HTTPS cho webhook và secret của
Telegram. Các bước 1–6 là kịch bản tích hợp chờ TV2/TV4 ghép; code TV5 hiện
được kiểm thử tự động với DB tạm và Telegram giả lập.

## Ghép triển khai

- TV1: `ALERT_WEBHOOK_URL=http://telegram-bot:8080/alerts`.
- TV2: dùng cùng `DATABASE_URL`, gọi `POST /link-codes` sau xác thực user; gửi
  header `X-Internal-API-Key` và hiển thị mã nhận được cho người dùng.
- TV4: chạy container `telegram-bot` trên cổng 8080, cấu hình URL HTTPS công khai
  cho Telegram webhook và giữ bot/API key trong secret của môi trường triển khai.
- TV5 tạo riêng `telegram_link_codes` và `telegram_report_deliveries`; các bảng
  `users`, `monitors`, `check_results`, `incidents`, `notification_channels` do
  TV2 sở hữu và TV5 không tự migration.
