# Telegram Bot + báo cáo TV5

Service nhận đúng webhook cảnh báo từ `monitoring-core`, gửi tới Telegram của
chủ monitor, hỗ trợ lệnh xem tình trạng và phát báo cáo ngày/tuần.

## Chức năng

- `POST /alerts`: nhận JSON theo hợp đồng §C của nhóm; tra `monitors.owner_id`
  và `notification_channels`, rồi gửi tới các chat Telegram đã liên kết.
- `POST /link-codes`: endpoint nội bộ cho Backend API TV2 tạo mã ghép dùng một
  lần, hết hạn sau 10 phút. TV2 chỉ cần gọi endpoint này sau khi xác thực user,
  rồi hiển thị mã để user gửi cho bot bằng `/start <mã>`.
- `POST /telegram/webhook`: nhận lệnh Telegram `/start`, `/help`, `/status`,
  `/report` và `/stop`. `TELEGRAM_WEBHOOK_SECRET` xác thực update từ Telegram.
- Báo cáo định kỳ lúc cấu hình được, theo múi giờ; một báo cáo cho mỗi user và
  kỳ báo cáo, kể cả khi service restart.
- `GET /health`: kiểm tra kết nối DB và hiển thị cấu hình Telegram.

## Chạy cục bộ

```powershell
cd telegram-bot
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Điền TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_URL, TELEGRAM_WEBHOOK_SECRET,
# TELEGRAM_LINK_API_KEY và DATABASE_URL trong .env
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Telegram yêu cầu URL webhook HTTPS có thể truy cập từ Internet. Khi khởi động,
service tự đăng ký URL với Telegram Bot API. Khi chạy Docker nội bộ, TV1 trỏ
`ALERT_WEBHOOK_URL=http://telegram-bot:8080/alerts`.

## Hợp đồng ghép với TV2

TV2 gọi từ backend (không gọi từ trình duyệt) sau khi user đăng nhập:

```http
POST /link-codes
X-Internal-API-Key: <TELEGRAM_LINK_API_KEY>
Content-Type: application/json

{"user_id": 42}
```

Phản hồi gồm `code` và `expires_at`. TV2 hiển thị hướng dẫn “mở bot và gửi
`/start <code>`”. Bot lưu chat ID vào đúng bảng dùng chung:

```text
notification_channels(id, user_id, type='telegram', target=<chat_id>)
```

Mã cũ của user bị thu hồi khi tạo mã mới; mã hết hạn hoặc đã dùng không thể
được dùng lại. TV2 cần đưa nút tạo mã này vào trang tài khoản để luồng ghép tài
khoản hoàn chỉnh.

## Lệnh bot

- `/status [giờ]`: thống kê trong 1–720 giờ gần nhất; mặc định 24 giờ.
- `/report daily`: báo cáo ngày hoàn tất gần nhất.
- `/report weekly`: báo cáo tuần hoàn tất gần nhất.
- `/stop`: gỡ liên kết chat hiện tại khỏi danh sách nhận cảnh báo.
- `/help`: hướng dẫn lệnh.

Uptime được tính `số lần UP / tổng số lần kiểm tra`; thời gian phản hồi lấy trung
bình các lần UP có latency. Báo cáo gồm số monitor, tổng lượt kiểm tra, uptime,
latency trung bình, sự cố mới, đã phục hồi và sự cố đang mở.

## Docker

Build từ thư mục repo:

```bash
docker build -t telegram-bot ./telegram-bot
docker run --env-file telegram-bot/.env -p 8080:8080 telegram-bot
```

TV4 có thể dùng image này trong `docker-compose`; service cần `DATABASE_URL`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_WEBHOOK_SECRET` và
`TELEGRAM_LINK_API_KEY`. `AUTO_CREATE_BOT_TABLES=true` chỉ tạo hai bảng riêng
của TV5; TV2 vẫn sở hữu schema dùng chung.

## Chạy kiểm thử

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

Các bài kiểm thử dùng SQLite và Telegram API giả lập; không cần bot token thật,
không gửi tin ra Telegram thật. Kết quả được ghi tại
[`docs/BAO-CAO-TV5.md`](../docs/BAO-CAO-TV5.md).
