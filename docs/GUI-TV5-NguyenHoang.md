# Gửi riêng: TV5 — Nguyễn Hoàng (Telegram Bot & báo cáo)

> Đây là phần của ông. Đọc file này là đủ.
> Việc ông nối thẳng với TV1 (phần tôi): tôi bắn cảnh báo dạng JSON, ông nhận
> và gửi Telegram. Chỉ cần khớp đúng JSON ở mục 1 là xong.

## Ông làm gì
- Dựng **bot Telegram** + 1 endpoint nhận cảnh báo.
- Nhận sự kiện cảnh báo từ TV1 → gửi tin nhắn tới đúng người.
- Lệnh xem trạng thái + báo cáo định kỳ (daily/weekly).
- Phối hợp làm kịch bản kiểm thử / demo.

## Ông phải nộp
Container tên `telegram-bot`, cổng `8080`, có endpoint `POST /alerts`.

---

## 1. JSON cảnh báo TV1 gửi cho ông 🔒 (KHÓA CỨNG)

TV1 đặt `ALERT_WEBHOOK_URL=http://telegram-bot:8080/alerts`. Mỗi khi có cảnh báo,
TV1 gửi `POST` JSON này tới ông:

```json
{
  "monitor_id": 1,
  "monitor_name": "Shop API",
  "kind": "down",
  "severity": "critical",
  "message": "Dịch vụ SẬP. Nguyên nhân: Connection refused",
  "at": "2026-01-01T08:03:00+00:00",
  "response_time_ms": null,
  "status_code": null,
  "ssl_days_left": null
}
```

- `kind` ∈ `down | recovered | flapping | stabilized | ssl_expiring`
- `severity` ∈ `critical | warning | info`

## 2. Ông chỉ cần làm
1. Dựng endpoint `POST /alerts` nhận đúng JSON trên.
2. Tra bảng `notification_channels` để biết gửi tới `chat_id` nào:
   ```
   notification_channels
     id | user_id FK->users.id | type ("telegram") | target (chat_id)
   ```
3. Gửi tin Telegram (gợi ý format):
   > 🔴 [critical] Shop API: Dịch vụ SẬP. Nguyên nhân: Connection refused — 08:03
4. (Sau) Lệnh `/status` cho khách xem nhanh + báo cáo định kỳ.

## 3. Lưu ý
- Ông **không cần hiểu bên trong TV1** làm gì — chỉ cần khớp JSON mục 1.
- Mẫu tạo JSON đó nằm ở `monitoring-core/app/notifier.py` → `event_to_dict()` (tham khảo).
- Map severity → icon: `critical`🔴 `warning`🟡 `info`🟢.
- Nhánh git của ông: `tv5-telegram`.

## 4. Phần đã triển khai trong repo

Service, hướng dẫn chạy và kiểm thử tích hợp nằm trong `telegram-bot/`.
TV2 cần gọi endpoint nội bộ `POST /link-codes` sau khi user xác thực để cấp mã
ghép Telegram dùng một lần; mô tả request/response nằm trong README của service.
Các bảng chia sẻ vẫn theo §A, TV5 chỉ tự tạo bảng riêng cho mã ghép và chống gửi
lặp báo cáo. Kết quả kiểm thử và công thức thống kê được ghi tại
[`BAO-CAO-TV5.md`](BAO-CAO-TV5.md).
