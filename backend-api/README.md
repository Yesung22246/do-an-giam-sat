# Backend API & Database Schema (`backend-api` — TV2)

Service quản lý cơ sở dữ liệu PostgreSQL chung (7 bảng), xác thực JWT, phân quyền `admin` / `customer`, giới hạn gói dịch vụ (`plans`) và cung cấp RESTful API cho toàn bộ hệ thống.

## 1. Thông tin kỹ thuật (Khóa cứng)
- **Container name / Service**: `backend-api`
- **Port nội bộ**: `8000`
- **Biến môi trường kết nối DB**:
  ```env
  DATABASE_URL=postgresql+asyncpg://app:password@db:5432/monitoring
  JWT_SECRET=super-secret-monitoring-key-2026
