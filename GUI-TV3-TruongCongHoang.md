# Gửi riêng: TV3 — Trương Công Hoàng (Frontend Dashboard)

> Đây là phần của ông. Đọc file này là đủ.
> Tin vui: ông **không phải chờ ai** — cứ dùng dữ liệu giả đúng format bên dưới
> để dựng giao diện trước, lúc TV2 xong API thì cắm vào là chạy.

## Ông làm gì
Giao diện **dashboard**:
- Đăng nhập + màn khách hàng + màn quản trị.
- Thêm/sửa/xóa monitor.
- Hiển thị: trạng thái, uptime, thời gian phản hồi, **biểu đồ** latency, **lịch sử sự cố**.
- Trang trạng thái công khai (status page).

## Ông phải nộp
Web gọi đúng API mục 1, hiển thị dữ liệu thật. Đóng gói container tên `frontend`, cổng `3000`.

---

## 1. API ông sẽ gọi 🔒 (do TV2 cung cấp — field là KHÓA CỨNG)

Mọi response JSON. Route cần token thì thêm header `Authorization: Bearer <JWT>`.

```
POST /auth/register   {email, password}            -> {token}
POST /auth/login      {email, password}            -> {token}

GET    /monitors                      -> [Monitor]
POST   /monitors      {name,type,target,port?,interval_seconds,...} -> Monitor
GET    /monitors/{id}                 -> Monitor
PUT    /monitors/{id} {...}           -> Monitor
DELETE /monitors/{id}                 -> {ok:true}

GET /monitors/{id}/results?hours=24   -> [CheckResult]   (vẽ biểu đồ latency)
GET /monitors/{id}/uptime?hours=24    -> {uptime_percent, avg_response_ms, total_checks}
GET /incidents?monitor_id={id}        -> [Incident]      (vẽ lịch sử sự cố)

GET /status/{public_id}               -> trang trạng thái công khai
```

## 2. Hình dạng dữ liệu để ông làm UI với data giả

```json
// Monitor
{"id":1,"name":"Shop API","type":"http","target":"https://shop.example.com",
 "port":null,"interval_seconds":60,"retries":3,"enabled":true}

// CheckResult (vẽ biểu đồ latency theo thời gian)
{"id":10,"monitor_id":1,"checked_at":"2026-01-01T08:00:00+00:00",
 "status":"up","response_time_ms":120.5,"status_code":200,
 "ssl_days_left":null,"error":null}

// uptime
{"uptime_percent":99.8,"avg_response_ms":135.2,"total_checks":1440}

// Incident (lịch sử sự cố)
{"id":3,"monitor_id":1,"state":"resolved","started_at":"2026-01-01T03:00:00+00:00",
 "resolved_at":"2026-01-01T03:12:00+00:00","cause":"Connection refused","severity":"critical"}
```

## 3. Lưu ý
- `status` chỉ có `"up"` / `"down"`. `severity` sự cố: `"critical"` / `"warning"`.
- Dựng UI với mock JSON trên trước, khỏi chờ TV2.
- Nhánh git của ông: `tv3-frontend`.
