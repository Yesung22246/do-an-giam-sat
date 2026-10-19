"""Unit test cho Alert Engine — chứng minh logic chống spam hoạt động đúng."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.alert_engine import AlertEngine, AlertKind, AlertPolicy
from app.checkers.base import CheckOutcome
from app.models import CheckStatus

UP = CheckOutcome.up(response_time_ms=100.0, status_code=200)
DOWN = CheckOutcome.down(error="refused")
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _t(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _run(engine: AlertEngine, seq, step=30):
    events = []
    for i, outcome in enumerate(seq):
        events.extend(engine.process(1, "x", outcome, now=_t(i * step)))
    return events


def test_single_failure_does_not_alert():
    """1 lần lỗi lẻ (dưới ngưỡng retries) -> không báo gì."""
    engine = AlertEngine(AlertPolicy(retries=3))
    events = _run(engine, [UP, DOWN, UP, UP])
    assert events == []
    assert engine.state_of(1) == CheckStatus.UP


def test_confirmed_down_alerts_once():
    """Lỗi liên tiếp đủ retries -> đúng 1 cảnh báo DOWN."""
    engine = AlertEngine(AlertPolicy(retries=3))
    events = _run(engine, [UP, DOWN, DOWN, DOWN, DOWN, DOWN])
    downs = [e for e in events if e.kind == AlertKind.DOWN]
    assert len(downs) == 1
    assert engine.state_of(1) == CheckStatus.DOWN


def test_down_then_recovery():
    """Sập rồi lên lại -> 1 DOWN + 1 RECOVERED."""
    engine = AlertEngine(AlertPolicy(retries=2, recovery_threshold=2))
    events = _run(engine, [DOWN, DOWN, UP, UP])
    kinds = [e.kind for e in events]
    assert kinds == [AlertKind.DOWN, AlertKind.RECOVERED]


def test_recovery_needs_confirmation():
    """1 lần UP lẻ khi đang DOWN chưa đủ -> chưa báo phục hồi."""
    engine = AlertEngine(AlertPolicy(retries=1, recovery_threshold=3))
    events = _run(engine, [DOWN, UP, DOWN, DOWN])
    recovered = [e for e in events if e.kind == AlertKind.RECOVERED]
    assert recovered == []
    assert engine.state_of(1) == CheckStatus.DOWN


def test_flapping_is_grouped():
    """Chập chờn liên tục -> phát FLAPPING đúng 1 lần, nén cảnh báo lẻ."""
    engine = AlertEngine(
        AlertPolicy(retries=1, recovery_threshold=1, flap_threshold=5,
                    flap_window=timedelta(minutes=30))
    )
    events = _run(engine, [DOWN, UP, DOWN, UP, DOWN, UP, DOWN, UP])
    flaps = [e for e in events if e.kind == AlertKind.FLAPPING]
    assert len(flaps) == 1


def test_flapping_then_stabilize():
    """Hết chập chờn -> phát đúng 1 STABILIZED."""
    engine = AlertEngine(
        AlertPolicy(retries=1, recovery_threshold=1, flap_threshold=5,
                    flap_window=timedelta(minutes=5))
    )
    flap = [DOWN, UP, DOWN, UP, DOWN, UP, DOWN, UP]
    stable = [UP] * 20
    events = _run(engine, flap + stable, step=30)
    stabilized = [e for e in events if e.kind == AlertKind.STABILIZED]
    assert len(stabilized) == 1


def test_ssl_warning_sent_once():
    """SSL sắp hết hạn -> chỉ cảnh báo 1 lần dù kiểm tra nhiều lần."""
    engine = AlertEngine(AlertPolicy(ssl_warn_days=14))
    near = CheckOutcome.up(ssl_days_left=5)
    events = _run(engine, [near, near, near, near])
    ssl_alerts = [e for e in events if e.kind == AlertKind.SSL_EXPIRING]
    assert len(ssl_alerts) == 1


def test_ssl_warning_resets_when_renewed():
    """Gia hạn (ngày tăng lại) rồi lại sắp hết -> được cảnh báo lần nữa."""
    engine = AlertEngine(AlertPolicy(ssl_warn_days=14))
    near = CheckOutcome.up(ssl_days_left=5)
    safe = CheckOutcome.up(ssl_days_left=90)
    events = _run(engine, [near, safe, near])
    ssl_alerts = [e for e in events if e.kind == AlertKind.SSL_EXPIRING]
    assert len(ssl_alerts) == 2


# --- Lưu/khôi phục trạng thái (chống mất state khi restart service) ---

def test_state_survives_restart_no_duplicate_down():
    """Mô phỏng restart: đã báo DOWN rồi, engine mới nạp lại state cũ
    -> KHÔNG báo DOWN lần nữa cho dịch vụ vẫn đang sập."""
    engine = AlertEngine(AlertPolicy(retries=3))
    events = _run(engine, [DOWN, DOWN, DOWN])  # xác nhận DOWN
    assert [e.kind for e in events] == [AlertKind.DOWN]

    # "Restart": dump state, tạo engine mới, nạp lại.
    saved = engine.dump_state(1)
    assert saved is not None
    engine2 = AlertEngine(AlertPolicy(retries=3))
    engine2.load_state(1, saved)
    assert engine2.state_of(1) == CheckStatus.DOWN

    # Vẫn đang sập -> không được báo DOWN trùng.
    more = engine2.process(1, "x", DOWN, now=_t(999))
    assert more == []


def test_state_restart_still_detects_recovery():
    """Sau restart (đang DOWN), khi dịch vụ sống lại vẫn báo RECOVERED đúng 1 lần."""
    engine = AlertEngine(AlertPolicy(retries=2, recovery_threshold=2))
    _run(engine, [DOWN, DOWN])
    saved = engine.dump_state(1)

    engine2 = AlertEngine(AlertPolicy(retries=2, recovery_threshold=2))
    engine2.load_state(1, saved)
    events = [e for e in [
        *engine2.process(1, "x", UP, now=_t(10)),
        *engine2.process(1, "x", UP, now=_t(20)),
    ]]
    assert [e.kind for e in events] == [AlertKind.RECOVERED]


def test_per_monitor_policy_no_interference():
    """2 monitor ngưỡng khác nhau, chạy xen kẽ -> không đạp ngưỡng của nhau.

    Monitor 1: retries=2 (nhạy). Monitor 2: retries=5 (lì).
    Cùng chuỗi DOWN xen kẽ: monitor 1 phải báo DOWN trước, monitor 2 chưa.
    """
    engine = AlertEngine()  # policy mặc định
    p1 = AlertPolicy(retries=2)
    p2 = AlertPolicy(retries=5)

    got1, got2 = [], []
    for i in range(3):  # 3 lần DOWN
        got1 += engine.process(1, "nhạy", DOWN, now=_t(i * 10), policy=p1)
        got2 += engine.process(2, "lì", DOWN, now=_t(i * 10), policy=p2)

    # Monitor 1 (retries=2) đã báo DOWN; monitor 2 (retries=5) thì chưa.
    assert [e.kind for e in got1] == [AlertKind.DOWN]
    assert got2 == []
    assert engine.state_of(1) == CheckStatus.DOWN
    assert engine.state_of(2) == CheckStatus.UP


def test_dump_load_preserves_streaks_and_transitions():
    """Round-trip giữ nguyên bộ đếm lỗi và danh sách mốc đổi trạng thái."""
    engine = AlertEngine(AlertPolicy(retries=5))
    _run(engine, [DOWN, DOWN])  # 2 lần lỗi, chưa đủ 5 -> chưa DOWN
    saved = engine.dump_state(1)

    engine2 = AlertEngine(AlertPolicy(retries=5))
    engine2.load_state(1, saved)
    reloaded = engine2.dump_state(1)
    assert reloaded["consecutive_failures"] == 2
    assert reloaded["confirmed"] == "up"
