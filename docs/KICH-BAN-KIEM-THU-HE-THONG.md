# Kịch bản kiểm thử và đánh giá toàn hệ thống

Ngày chạy: 04/11/2026. Các kiểm thử tự động chạy trên Windows, Python 3.14.

## Mục tiêu

Kiểm tra các luồng chính giữa Frontend, Backend API, monitoring-core và Telegram
bot; đặc biệt là đường cảnh báo từ bộ giám sát tới đúng tài khoản Telegram. Bộ
kiểm thử tự động thay Telegram Bot API bằng client giả để không gửi tin thật.

## Kết quả các kiểm thử đã chạy

| Mã | Thành phần/luồng | Cách kiểm tra | Kết quả | Đánh giá |
|---|---|---|---|---|
| SYS-01 | TV1 → TV5 → chat được liên kết | Test tích hợp HTTP trong tiến trình; TV1 gửi JSON + `X-Alert-Secret`, TV5 xác minh, tra DB SQLite và gọi client Telegram giả | Đạt; nằm trong 32 test của monitoring-core | Luồng hợp đồng và định tuyến đã xác minh tự động |
| SYS-02 | Xác thực cảnh báo | TV5 nhận request thiếu/sai secret; kiểm tra payload sai định dạng | Đạt; TV5 trả 401/422 theo trường hợp | Endpoint fail-closed; cấu hình secret trống trả 503 |
| SYS-03 | Tài khoản và gói dịch vụ | Chạy `backend-api/tests` | 3 passed | Đăng ký/đăng nhập, giới hạn gói và endpoint mã liên kết đạt |
| SYS-04 | Kiểm tra, cảnh báo và sự cố | Chạy toàn bộ `monitoring-core/tests` | 32 passed | Các test core, hợp đồng notifier và đường HTTP TV1→TV5 đạt |
| SYS-05 | Lệnh bot, báo cáo, chống gửi trùng | Chạy `telegram-bot/tests` với SQLite và Telegram giả | 5 passed | Các luồng TV5 đã kiểm thử tự động |
| SYS-06 | Frontend production bundle | `npm ci` rồi `npm run build` trong `frontend/` | Build thành công; npm audit báo 0 vulnerabilities | Mã frontend biên dịch được |
| SYS-07 | Ghép cả 5 service bằng Docker/Postgres | Kiểm tra môi trường chạy | Chưa chạy | Máy này không có Docker CLI; repo chưa có compose toàn hệ thống ở `main` |
| SYS-08 | Nhận cảnh báo trên điện thoại qua BotFather | Kiểm tra môi trường chạy | Chưa chạy | Chưa có Telegram Desktop/session, bot token, chat đã liên kết hoặc URL HTTPS công khai |

## Kịch bản demo end-to-end

Khi có bot token và môi trường triển khai truy cập được từ Telegram, chạy theo
trình tự sau:

| Bước | Thao tác | Kết quả mong đợi |
|---|---|---|
| 1 | Tạo bot tại `@BotFather`; đặt `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_URL` HTTPS và `TELEGRAM_WEBHOOK_SECRET` cho `telegram-bot` | Bot khởi động và đăng ký webhook; `/health` báo DB hoạt động |
| 2 | Sinh một secret ngẫu nhiên tối thiểu 32 ký tự; đặt cùng `ALERT_WEBHOOK_SECRET` ở TV1 và TV5 | TV1 và TV5 dùng cùng hợp đồng `X-Alert-Secret`; không commit secret |
| 3 | Đăng ký/đăng nhập trên frontend; yêu cầu mã liên kết Telegram; gửi `/start <mã>` trong bot | TV2/TV5 tạo `notification_channels` cho tài khoản đó |
| 4 | Tạo monitor thử nghiệm qua frontend, trỏ tới dịch vụ có thể dừng/khởi động | Monitor thuộc đúng tài khoản và bắt đầu có kết quả kiểm tra |
| 5 | Dừng dịch vụ quá số lần `retries` | Incident mở; TV1 gửi `down`; điện thoại nhận tin đỏ đúng monitor |
| 6 | Khởi động lại dịch vụ, chờ đủ số lần xác nhận phục hồi | Incident đóng; điện thoại nhận tin phục hồi màu xanh |
| 7 | Kiểm tra `/status 24`, `/report daily`, `/report weekly` | Bot trả thống kê trùng với dữ liệu trên dashboard/DB |

## Hạn chế của lần chạy hiện tại

- Tích hợp TV1→TV5 đã đi qua request HTTP thật trong ASGI và database SQLite;
  phần Telegram outbound được giả lập. Chưa có bằng chứng nhận tin trên điện
  thoại.
- Kiểm thử backend dùng database SQLite tạm. Chưa xác minh schema và giao dịch
  trên PostgreSQL dùng chung.
- Backend test có 6 cảnh báo độ dài JWT key từ khóa test ngắn; cấu hình khóa
  production phải dùng secret ít nhất 32 byte.
- Frontend đã build production; chưa chạy browser acceptance test với backend
  đang phục vụ.
- Bảng SYS-07/SYS-08 là các bước chờ hạ tầng và thông tin Telegram. Không ghi
  chúng là đạt cho tới khi compose/Postgres, bot token và webhook HTTPS chạy thật.
