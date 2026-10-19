"""Demo Alert Engine — KHÔNG cần mạng, chạy tức thì.

Mô phỏng một chuỗi kết quả kiểm tra để thấy rõ 4 cơ chế chống spam.
Dùng để trình bày/bảo vệ: "nếu cứ lỗi là báo thì spam, còn engine của em thì..."

Chạy:  python demo_alert_engine.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

# Windows: ép console in được tiếng Việt (UTF-8).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.alert_engine import AlertEngine, AlertPolicy
from app.checkers.base import CheckOutcome

UP = CheckOutcome.up(response_time_ms=120.0, status_code=200)
DOWN = CheckOutcome.down(error="Connection refused")

MID = 1
NAME = "Shop API"


def banner(title: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def feed(engine: AlertEngine, seq, start: datetime, step_seconds: int = 30):
    """Nạp lần lượt chuỗi kết quả, mỗi lần cách nhau step_seconds; in cảnh báo.

    Trả về (naive, real):
    - naive: số tin nếu "cứ đổi trạng thái là báo" (cách ngây thơ).
    - real : số tin engine thực sự gửi.
    """
    t = start
    naive_alerts = 0
    real_alerts = 0
    prev = None
    for outcome in seq:
        if prev is None or outcome.is_up != prev:
            naive_alerts += 1
        prev = outcome.is_up

        events = engine.process(MID, NAME, outcome, now=t)
        real_alerts += len(events)
        mark = "UP " if outcome.is_up else "DOWN"
        line = f"  {t:%H:%M:%S} check={mark}"
        if events:
            for e in events:
                line += f"\n      -> CẢNH BÁO [{e.severity}] {e.kind.value}: {e.message}"
        print(line)
        t += timedelta(seconds=step_seconds)
    return naive_alerts, real_alerts


def scenario_down_recover():
    banner("Kịch bản 1: Lỗi mạng thoáng qua vs. sập thật (xác nhận bằng retries)")
    engine = AlertEngine(AlertPolicy(retries=3, recovery_threshold=2))
    start = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    # 1 lần lỗi lẻ (nhiễu) -> KHÔNG báo. Sau đó lỗi 3 lần liên tiếp -> báo DOWN.
    seq = [UP, DOWN, UP, UP, DOWN, DOWN, DOWN, DOWN, UP, UP]
    naive, real = feed(engine, seq, start)
    print(f"\n  => Cách ngây thơ (đổi trạng thái là báo): {naive} tin.")
    print(f"     Engine: {real} tin (1 DOWN đã xác nhận + 1 RECOVERED). "
          "Lỗi lẻ bị lọc bỏ.")


def scenario_flapping():
    banner("Kịch bản 2: Dịch vụ chập chờn (flapping) -> gộp 1 cảnh báo")
    engine = AlertEngine(
        AlertPolicy(retries=1, recovery_threshold=1, flap_threshold=3,
                    flap_window=timedelta(minutes=10))
    )
    start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    # Lên xuống liên tục -> nhiều lần chuyển trạng thái trong 10 phút.
    flap = [DOWN, UP, DOWN, UP, DOWN, UP, DOWN, UP, DOWN, UP]
    # Rồi ổn định UP một lúc -> engine phát STABILIZED.
    stable = [UP] * 25
    naive, real = feed(engine, flap + stable, start)
    print(f"\n  => Cách ngây thơ: {naive} tin nhắn rác.")
    print(f"     Engine: {real} tin (vài tin đầu + 'flapping' gộp phần còn lại "
          "+ 'đã ổn định'). Càng chập chờn lâu càng tiết kiệm.")


def scenario_ssl():
    banner("Kịch bản 3: Chứng chỉ SSL sắp hết hạn (chỉ báo 1 lần)")
    engine = AlertEngine(AlertPolicy(ssl_warn_days=14))
    start = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    near_expiry = CheckOutcome.up(ssl_days_left=7)
    seq = [near_expiry] * 5  # kiểm tra 5 lần nhưng chỉ cảnh báo 1 lần
    _, real = feed(engine, seq, start, step_seconds=3600)
    print(f"\n  => Dù kiểm tra 5 lần, engine chỉ gửi {real} cảnh báo SSL (chống lặp).")


if __name__ == "__main__":
    scenario_down_recover()
    scenario_flapping()
    scenario_ssl()
    print()
