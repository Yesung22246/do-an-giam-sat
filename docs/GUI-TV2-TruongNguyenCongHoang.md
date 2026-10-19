# Gửi riêng: TV2 — Trương Nguyễn Công Hoàng (Backend API)

> Đây là phần của ông. Đọc file này là đủ, không cần đọc hết file chung.
> Phần ông là **xương sống dữ liệu** — TV1/TV3/TV5 đều phụ thuộc ông, nên ông
> nên chốt bảng DB (mục 1) sớm nhất.

## Ông làm gì
Viết **Backend API** + **quản lý user/gói dịch vụ**:
- Đăng ký / đăng nhập (JWT), phân quyền admin ↔ khách hàng.
- CRUD monitor (khách chỉ thấy monitor của mình).
- Giới hạn theo gói (số monitor tối đa, tần suất nhanh nhất).
- Là người **làm chủ database** chung.

## Ông phải nộp
API chạy đúng mục 2 + database đúng mục 1. Đóng gói 1 container tên `backend-api`, cổng `8000`.

---

## 1. Database — ông tạo & quản lý migration 🔒 (các tên cột là KHÓA CỨNG)

TV1 đã hiện thực sẵn 3 bảng `monitors` / `check_results` / `incidents` trong
`monitoring-core/app/models.py` — ông bê nguyên tên cột sang Postgres cho khớp.

```
plans                      -- gói dịch vụ (phần kiếm tiền)
  id PK | name text | max_monitors int | min_interval int | price int

users
  id PK | email text unique | password_hash text
  role text ("admin"|"customer") | plan_id FK->plans.id | created_at timestamptz

monitors
  id PK | owner_id FK->users.id | name text
  type text ("http"|"tcp"|"ssl") | target text | port int null
  interval_seconds int | timeout_seconds float
  expected_status int null | retries int | ssl_warn_days int
  enabled bool | created_at timestamptz

check_results              -- TV1 GHI (nguồn vẽ biểu đồ)
  id PK | monitor_id FK->monitors.id | checked_at timestamptz (index)
  status text ("up"|"down") | response_time_ms float null
  status_code int null | ssl_days_left int null | error text null

incidents                  -- TV1 GHI (nguồn lịch sử sự cố)
  id PK | monitor_id FK->monitors.id | state text ("open"|"resolved")
  started_at timestamptz | resolved_at timestamptz null
  cause text null | severity text ("critical"|"warning")

monitor_alert_states       -- TV1 GHI (lưu trạng thái alert, 1 dòng/monitor)
  monitor_id PK FK->monitors.id | confirmed text | consecutive_failures int
  consecutive_successes int | transitions json | flapping_active bool
  ssl_notified bool | last_cause text null | updated_at timestamptz

notification_channels      -- nơi khách nhận cảnh báo (TV5 đọc)
  id PK | user_id FK->users.id | type text ("telegram") | target text (chat_id)
```

## 2. API — ông viết, TV3 gọi 🔒 (đường dẫn & field là KHÓA CỨNG)

Mọi response JSON. Mọi route (trừ `/auth/*`, `/status/*`) cần header
`Authorization: Bearer <JWT>`.

```
POST /auth/register   {email, password}            -> {token}
POST /auth/login      {email, password}            -> {token}

GET    /monitors                      -> [Monitor]   (chỉ của user đăng nhập)
POST   /monitors      {name,type,target,port?,interval_seconds,...}
                                      -> Monitor      (chặn nếu vượt max_monitors của gói)
GET    /monitors/{id}                 -> Monitor
PUT    /monitors/{id} {...}           -> Monitor
DELETE /monitors/{id}                 -> {ok: true}

GET /monitors/{id}/results?hours=24   -> [CheckResult]   (TV3 vẽ biểu đồ latency)
GET /monitors/{id}/uptime?hours=24    -> {uptime_percent, avg_response_ms, total_checks}
GET /incidents?monitor_id={id}        -> [Incident]      (TV3 vẽ lịch sử sự cố)

GET /status/{public_id}               -> trang trạng thái công khai (không cần token)
```

Ví dụ `Monitor` trả về:
```json
{"id":1,"name":"Shop API","type":"http","target":"https://shop.example.com",
 "port":null,"interval_seconds":60,"retries":3,"enabled":true}
```

> Hàm tính uptime TV1 đã có sẵn ở `monitoring-core/app/uptime.py` (`compute_uptime`).
> Ông gọi lại hoặc query trực tiếp `check_results`.

## 3. Lưu ý
- DB dùng chung với mọi người (TV4 dựng Postgres). TV1 chỉ GHI vào các bảng ghi "TV1 GHI".
- Cần đổi tên cột/route 🔒 → nhắn nhóm trước.
- Nhánh git của ông: `tv2-api`.
