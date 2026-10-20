# Monitoring Core + Alert Engine (phần TV1)

Phần lõi của nền tảng giám sát: **kiểm tra tính sẵn sàng của website/API/máy chủ
và quyết định khi nào cảnh báo** — không gửi tin rác.

Đây là phần "nghiên cứu sâu" của đồ án: bộ **Alert Engine** chống spam bằng một
máy trạng thái (state machine) cho từng mục tiêu.

## Làm được gì

- **3 loại kiểm tra**: HTTP/HTTPS (website, API), TCP (cổng dịch vụ), SSL (hạn chứng chỉ).
- **Chạy song song** nhiều mục tiêu, mỗi mục tiêu một chu kỳ riêng, giới hạn tải bằng semaphore.
- **Tính uptime + thời gian phản hồi** từ lịch sử kiểm tra (nguồn dữ liệu cho biểu đồ của TV3).
- **Alert Engine** với 4 cơ chế:
  1. Xác nhận lỗi (`retries`) — lọc nhiễu mạng, không báo nhầm.
  2. Xác nhận phục hồi — chỉ báo "sống lại" khi thực sự ổn định.
  3. Phát hiện flapping — gộp cảnh báo khi dịch vụ chập chờn lên xuống.
  4. Chống lặp — mỗi sự cố chỉ 1 cảnh báo; SSL sắp hết hạn chỉ báo 1 lần.
- **Ghi lịch sử sự cố** (bảng `incidents`) — nguồn dữ liệu "lịch sử sự cố".
- **Lưu trạng thái alert xuống DB** (bảng `monitor_alert_states`) — restart/deploy
  lại service KHÔNG bị mất trạng thái, không báo trùng "SẬP".
- **Ngưỡng cảnh báo riêng từng monitor** — mỗi monitor dùng `retries`/`ssl_warn_days`
  của riêng nó, chạy song song không đạp nhau.
- **Gom dữ liệu dài hạn (rollup)** (bảng `check_rollups`) — dữ liệu cũ gom theo giờ
  để biểu đồ 30 ngày không làm phình DB; uptime vẫn tính đúng.
- **Multi-region probe** — kiểm tra từ nhiều khu vực, phân biệt "web sập thật"
  (mọi nơi đều lỗi) với "lỗi đường mạng" (chỉ vài nơi lỗi) để không báo nhầm.
- **Notifier tách rời** — phát sự kiện cảnh báo ra ngoài cho TV5 (Telegram) qua JSON chuẩn.

## Cài & chạy

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env      # Windows: copy .env.example .env
```

Chạy service giám sát thật (tự thêm 4 mục tiêu mẫu nếu DB trống):

```bash
python -m app.main
```

Xem Alert Engine hoạt động mà không cần mạng (dùng để trình bày/bảo vệ):

```bash
python demo_alert_engine.py
```

Xem multi-region phân biệt "sập thật" vs "lỗi đường mạng" (không cần mạng):

```bash
python demo_multi_region.py
```

Chạy test:

```bash
pytest -q
```

## Demo "chủ động tắt dịch vụ" (yêu cầu của đề bài)

1. Chạy `python -m app.main`.
2. Thêm 1 monitor trỏ tới dịch vụ cục bộ của bạn (vd web chạy trên `http://localhost:8000`).
3. Tắt dịch vụ đó đi.
4. Sau `retries` lần kiểm tra lỗi liên tiếp → engine xác nhận DOWN, mở incident, phát cảnh báo.
5. Bật lại → sau khi xác nhận ổn định → phát cảnh báo RECOVERED, đóng incident.

## Cấu trúc

```
app/
  checkers/        # http / tcp / ssl — mỗi loại 1 file, trả về CheckOutcome chung
  alert_engine.py  # <-- TRÁI TIM: state machine chống spam (thuần, test được)
  scheduler.py     # vòng lặp async: check -> lưu -> alert -> mở/đóng incident -> gửi
  notifier.py      # interface phát cảnh báo (Console / Webhook cho TV5)
  uptime.py        # tính % uptime + response time trung bình
  models.py        # 3 bảng: monitors, check_results, incidents
demo_alert_engine.py
tests/test_alert_engine.py
```

## Ghép với nhóm (ranh giới công việc)

| Với | Ghép ở đâu | Hợp đồng dữ liệu |
|-----|-----------|------------------|
| **TV2 (Backend API)** | Dùng chung 3 bảng trong `models.py` | TV2 tạo/sửa `monitors`, TV1 ghi `check_results` + `incidents` |
| **TV3 (Frontend)** | Đọc `check_results` (biểu đồ), `incidents` (lịch sử), hàm `compute_uptime` | qua API của TV2 |
| **TV4 (Hạ tầng)** | Đóng gói service này thành 1 container Docker | `DATABASE_URL` trỏ Postgres chung |
| **TV5 (Telegram)** | Nhận cảnh báo | JSON từ `notifier.event_to_dict()` — đặt `ALERT_WEBHOOK_URL` trỏ endpoint của TV5 |

**Định dạng 1 sự kiện cảnh báo** (gửi cho TV5):

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

`kind` ∈ `down | recovered | flapping | stabilized | ssl_expiring`
`severity` ∈ `critical | warning | info`

## Ghép chung với Backend API (TV2) trên Postgres

TV2 đã dựng Backend API (FastAPI) dùng **đúng 8 bảng** khớp schema ở đây, và khi
khởi động sẽ tự tạo bảng + seed gói dịch vụ/admin. Vì vậy khi chạy chung:

1. Trỏ cả 2 service vào cùng Postgres:
   `DATABASE_URL=postgresql+asyncpg://app:<mật khẩu>@db:5432/monitoring`
2. **Để TV2 làm chủ việc tạo bảng** — đặt cho monitoring-core:
   `AUTO_CREATE_TABLES=false` và `SEED_SAMPLE_MONITORS=false`
   (tránh 2 service cùng chạy `create_all` lúc khởi động).
3. Luồng dữ liệu: khách tạo monitor qua API của TV2 → monitoring-core đọc bảng
   `monitors`, kiểm tra, rồi GHI `check_results` / `incidents` / `check_rollups`
   / `monitor_alert_states` → TV2 đọc lại để trả cho Frontend (TV3).

Đã cài sẵn `asyncpg` trong `requirements.txt` để kết nối Postgres.
