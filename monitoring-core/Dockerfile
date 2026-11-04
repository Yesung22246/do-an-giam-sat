# Monitoring Core (TV1) — vòng lặp giám sát, không mở cổng nào.
# Chỉ đọc/ghi database chung và gửi cảnh báo sang telegram-bot.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Không chạy bằng root. Thư mục /app/data để chạy một mình bằng SQLite;
# khi ghép nhóm thì docker-compose đặt DATABASE_URL trỏ Postgres, đè giá trị này.
RUN useradd --create-home --uid 10001 monitor     && mkdir /app/data && chown monitor /app/data
ENV DATABASE_URL=sqlite+aiosqlite:////app/data/monitoring.db
USER monitor

CMD ["python", "-m", "app.main"]
