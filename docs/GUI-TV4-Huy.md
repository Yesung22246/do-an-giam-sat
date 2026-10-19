# Gửi riêng: TV4 — Huy (Hạ tầng & triển khai)

> Đây là phần của ông. Đọc file này là đủ.
> Ông là người **ráp cả hệ thống lại** bằng Docker, nên mục "tên service & cổng"
> bên dưới là luật chung cho cả nhóm.

## Ông làm gì
- Thiết kế & triển khai trên **nhiều máy chủ Ubuntu Server**.
- Đóng gói từng phần thành container, ráp bằng `docker-compose`.
- Dựng **Postgres dùng chung**, cấu hình **reverse proxy + HTTPS**.
- Giám sát tài nguyên máy chủ (CPU/RAM/ổ đĩa) + sao lưu & khôi phục DB.

## Ông phải nộp
`docker-compose` chạy được cả hệ thống + Postgres chung + hướng dẫn sao lưu/khôi phục.

---

## 1. Tên service & cổng 🔒 (KHÓA CỨNG — cả nhóm theo cái này)

```
service          cổng nội bộ   ghi chú
---------------------------------------------------------------
db (postgres)    5432          Postgres dùng chung, ông dựng
monitoring-core  (không mở)    phần TV1 — chỉ ghi DB + gọi webhook TV5
backend-api      8000          phần TV2
frontend         3000          phần TV3
telegram-bot     8080          phần TV5 — nhận cảnh báo ở POST /alerts
```

## 2. Biến môi trường chung

- Chuỗi kết nối DB (mọi service dùng y hệt):
  ```
  DATABASE_URL=postgresql+asyncpg://app:<mật khẩu>@db:5432/monitoring
  ```
- Riêng `monitoring-core` (TV1) cần thêm:
  ```
  ALERT_WEBHOOK_URL=http://telegram-bot:8080/alerts
  ```

## 3. Việc của ông cụ thể
- `docker-compose.yml` gồm 5 service trên + healthcheck.
- Reverse proxy (Nginx/Traefik) + HTTPS cho `backend-api` và `frontend`.
- Script backup Postgres (`pg_dump`) + thử khôi phục.
- Phần "đa máy chủ": tách DB sang 1 máy, app sang máy khác (đúng yêu cầu đề bài).

## 4. Lưu ý
- Phần TV1 (`monitoring-core`) đã có sẵn `Dockerfile`-able: Python + `requirements.txt`,
  chạy bằng `python -m app.main`, cần `DATABASE_URL` + `ALERT_WEBHOOK_URL`.
- Nhánh git của ông: `tv4-infra`.
