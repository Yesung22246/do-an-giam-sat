# TV3 Frontend — PulseWatch
## Chạy thử bằng Node.js
```bash
npm install
npm run dev
```
Mở http://localhost:5173.

## Chạy bằng Docker
```bash
docker compose up -d --build
docker compose ps
```
Mở http://localhost:3000. Container: `frontend`.

## Kết nối API TV2
Sao chép `.env.example` thành `.env`, đặt URL backend thực tế:
`VITE_API_BASE_URL=http://IP_BACKEND:PORT`
Sau đó build lại. Ví dụ:
`VITE_API_BASE_URL=http://192.168.1.20:8000 docker compose up -d --build`
Backend phải bật CORS cho origin frontend. Địa chỉ API được Vite nhúng lúc build nên phải build lại khi đổi URL.

Nếu chưa đặt API, form đăng nhập cho phép vào chế độ demo bằng email hợp lệ và mật khẩu ít nhất 4 ký tự. Dữ liệu demo không lưu vào database.
