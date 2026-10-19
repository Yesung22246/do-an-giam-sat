# Hợp đồng kỹ thuật của nhóm — Nền tảng giám sát website & máy chủ

> **Tài liệu này thay cho buổi họp.** Cả nhóm bận, nên mọi thứ cần thống nhất
> đều nằm ở đây. Không ai được tự ý đổi các phần "KHÓA CỨNG" bên dưới; muốn đổi
> thì nhắn nhóm trước, vì đổi một bên là bên kia hỏng.

---

## 0. Cách dùng tài liệu này (đọc 30 giây)

Tìm đúng dòng của bạn trong bảng, rồi nhảy tới mục được ghi. Chỉ cần đọc mục của
mình + các mục mình phụ thuộc, không cần đọc hết.

| Bạn là | Nhiệm vụ 1 câu | ĐỌC mục | PHẢI NỘP (output) |
|--------|----------------|---------|-------------------|
| **TV1 — Đức Hoàng** (lõi giám sát) | Kiểm tra web/máy chủ + sinh cảnh báo | §A schema, §C cảnh báo | Service `monitoring-core` ghi dữ liệu vào DB + bắn cảnh báo |
| **TV2 — Trương Nguyễn Công Hoàng** (Backend API) | Viết API + quản lý user/gói | §A schema, §B API | API chạy đúng §B, đúng bảng §A |
| **TV3 — Trương Công Hoàng** (Frontend) | Giao diện dashboard | §B API | Web gọi API §B, hiển thị uptime/biểu đồ/sự cố |
| **TV4 — Huy** (Hạ tầng) | Docker + triển khai đa máy chủ | §D hạ tầng | docker-compose chạy cả hệ thống + Postgres chung |
| **TV5 — Nguyễn Hoàng** (Telegram) | Bot gửi/nhận cảnh báo | §C cảnh báo | Endpoint nhận JSON §C + gửi Telegram |

**Nguyên tắc sống còn:** Các mục có nhãn 🔒 **KHÓA CỨNG** là giao diện giữa người
với người. Giữ y nguyên tên trường/đường dẫn. Bên trong code mỗi người muốn làm
sao cũng được.

---

## §A. Schema database 🔒 KHÓA CỨNG

**Chủ sở hữu: TV2 — Trương Nguyễn Công Hoàng** (tạo và quản lý file migration). TV1 chỉ GHI vào
`check_results` + `incidents`. Dùng chung 1 Postgres do TV4 dựng.

Dùng lại đúng các bảng này (TV1 đã hiện thực sẵn 3 bảng cuối trong
`monitoring-core/app/models.py` — TV2 bê nguyên tên cột sang Postgres).

```
plans                      -- các gói dịch vụ (phần kiếm tiền)
  id            PK
  name          text        -- "Free", "Pro", "Business"
  max_monitors  int         -- số website tối đa được giám sát
  min_interval  int         -- tần suất nhanh nhất cho phép (giây)
  price         int         -- giá / tháng

users
  id            PK
  email         text unique
  password_hash text
  role          text        -- "admin" | "customer"
  plan_id       FK -> plans.id
  created_at    timestamptz

monitors                   -- mục tiêu cần giám sát
  id            PK
  owner_id      FK -> users.id     -- khách chỉ thấy monitor của mình
  name          text
  type          text        -- "http" | "tcp" | "ssl"
  target        text        -- http: URL; tcp/ssl: host
  port          int null
  interval_seconds int      -- chu kỳ kiểm tra
  timeout_seconds  float
  expected_status  int null -- http: mã coi là "sống" (vd 200)
  retries       int         -- số lần lỗi liên tiếp mới coi là SẬP
  ssl_warn_days int         -- cảnh báo khi SSL còn <= số ngày này
  enabled       bool
  created_at    timestamptz

check_results              -- mỗi lần kiểm tra 1 dòng (TV1 ghi) -> biểu đồ
  id            PK
  monitor_id    FK -> monitors.id
  checked_at    timestamptz (index)
  status        text        -- "up" | "down"
  response_time_ms float null
  status_code   int null
  ssl_days_left int null
  error         text null

incidents                  -- mỗi sự cố mở/đóng (TV1 ghi) -> lịch sử sự cố
  id            PK
  monitor_id    FK -> monitors.id
  state         text        -- "open" | "resolved"
  started_at    timestamptz
  resolved_at   timestamptz null
  cause         text null
  severity      text        -- "critical" | "warning"

notification_channels      -- nơi khách muốn nhận cảnh báo (TV5 dùng)
  id            PK
  user_id       FK -> users.id
  type          text        -- "telegram"
  target        text        -- telegram chat_id
```

---

## §B. API 🔒 KHÓA CỨNG

**Chủ sở hữu: TV2 (Trương Nguyễn Công Hoàng) viết · TV3 (Trương Công Hoàng) gọi.** Mọi response là JSON. Mọi route (trừ
`/auth/*` và `/status/*`) cần header `Authorization: Bearer <JWT>`.

```
POST /auth/register   body {email, password}            -> {token}
POST /auth/login      body {email, password}            -> {token}

GET    /monitors                      -> [Monitor, ...]   (chỉ của user đang đăng nhập)
POST   /monitors      body {name,type,target,port?,interval_seconds,...}
                                      -> Monitor          (TV2 chặn nếu vượt max_monitors của gói)
GET    /monitors/{id}                 -> Monitor
PUT    /monitors/{id} body {...}      -> Monitor
DELETE /monitors/{id}                 -> {ok: true}

GET /monitors/{id}/results?hours=24   -> [CheckResult, ...]   (TV3 vẽ biểu đồ latency)
GET /monitors/{id}/uptime?hours=24    -> {uptime_percent, avg_response_ms, total_checks}
GET /incidents?monitor_id={id}        -> [Incident, ...]      (TV3 vẽ lịch sử sự cố)

GET /status/{public_id}               -> trang trạng thái công khai (không cần token)
```

**Ví dụ một `Monitor` trả về:**
```json
{
  "id": 1, "name": "Shop API", "type": "http",
  "target": "https://shop.example.com", "port": null,
  "interval_seconds": 60, "retries": 3, "enabled": true
}
```

> TV1 lưu ý: hàm tính uptime đã có sẵn ở `monitoring-core/app/uptime.py`
> (`compute_uptime`). TV2 gọi lại logic này hoặc query trực tiếp `check_results`.

---

## §C. Format sự kiện cảnh báo 🔒 KHÓA CỨNG

**Chủ sở hữu: TV1 (Đức Hoàng) gửi · TV5 (Nguyễn Hoàng) nhận.** TV1 đặt biến `ALERT_WEBHOOK_URL` trỏ tới
endpoint của TV5. Mỗi khi có cảnh báo, TV1 gửi `POST` JSON sau tới đó:

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

**TV5 chỉ cần:** dựng 1 endpoint (vd `POST /alerts`) nhận đúng JSON này, tra
`notification_channels` để biết gửi tới chat_id nào, rồi gửi tin Telegram.
Hàm tạo JSON này đã có sẵn: `monitoring-core/app/notifier.py` →
`event_to_dict()`. TV5 không cần hiểu bên trong TV1 làm gì.

---

## §D. Hạ tầng 🔒 KHÓA CỨNG (tên service & cổng)

**Chủ sở hữu: TV4 — Huy.** Mọi người đóng gói phần mình thành 1 container. TV4 ráp
bằng `docker-compose`. Thống nhất:

```
service          cổng nội bộ   ghi chú
---------------------------------------------------------------
db (postgres)    5432          Postgres dùng chung, TV4 dựng
monitoring-core  (không mở)    phần TV1, chỉ ghi DB + gọi webhook TV5
backend-api      8000          phần TV2
frontend         3000          phần TV3
telegram-bot     8080          phần TV5, nhận cảnh báo ở POST /alerts
```

- Chuỗi kết nối DB chung (tất cả service dùng y hệt):
  `DATABASE_URL=postgresql+asyncpg://app:<mật khẩu>@db:5432/monitoring`
- TV1 đặt thêm: `ALERT_WEBHOOK_URL=http://telegram-bot:8080/alerts`
- TV4 lo reverse proxy (Nginx/Traefik) + HTTPS cho `backend-api` và `frontend`.

---

## §E. Quy tắc làm việc chung (để khỏi giẫm chân, không cần họp)

1. **Một repo chung, mỗi người một nhánh**: `tv1-core`, `tv2-api`, `tv3-frontend`,
   `tv4-infra`, `tv5-telegram`. Xong việc nào mở Pull Request vào `main`.
2. **Không tự đổi mục 🔒**. Cần đổi → nhắn nhóm + sửa tài liệu này trước, rồi mới code.
3. **Thứ tự phụ thuộc** (ai chờ ai):
   - TV2 chốt bảng §A trước → TV1, TV3, TV5 mới chạy mượt.
   - Trong lúc chờ, TV3 cứ dùng **dữ liệu giả** đúng format §B để làm UI; TV1 đã
     chạy độc lập được rồi (có SQLite + demo).
4. **Mốc ghép thử**: tự hẹn một ngày, mỗi người push nhánh của mình, TV4 chạy
   `docker-compose up` để nối. Lỗi gì sửa ngay hôm đó.
5. Thắc mắc về phần nào → nhắn thẳng người chủ mục đó (ghi ở đầu mỗi mục).

---

## §F. Trạng thái hiện tại

- ✅ **TV1 — Đức Hoàng (lõi giám sát)**: xong bản chạy được — 3 loại kiểm tra,
  alert engine chống spam, lưu DB, tính uptime, đã test. Nằm ở `monitoring-core/`
  (xem `monitoring-core/README.md`).
- ⬜ **TV2 — Trương Nguyễn Công Hoàng** (Backend API): bắt đầu từ §A + §B.
- ⬜ **TV3 — Trương Công Hoàng** (Frontend): bắt đầu từ §B.
- ⬜ **TV4 — Huy** (Hạ tầng): bắt đầu từ §D.
- ⬜ **TV5 — Nguyễn Hoàng** (Telegram): bắt đầu từ §C.
