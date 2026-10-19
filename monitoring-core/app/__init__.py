"""Monitoring Core + Alert Engine (phần TV1).

Service giám sát tính sẵn sàng của website/API/máy chủ:
- Kiểm tra định kỳ nhiều mục tiêu song song (HTTP/HTTPS, TCP, hạn SSL).
- Tính uptime, thời gian phản hồi, lưu lịch sử.
- Alert Engine chống spam: xác nhận lỗi, phát hiện flapping, báo phục hồi.
- Phát sự kiện cảnh báo ra ngoài cho TV5 (Telegram bot) qua một interface rõ ràng.
"""
