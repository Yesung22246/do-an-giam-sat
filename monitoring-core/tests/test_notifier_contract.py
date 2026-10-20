"""Contract test ranh giới TV1 -> TV5 (Telegram bot).

TV5 nhận cảnh báo bằng model AlertPayload với các trường + kiểu + tập giá trị
cố định. Test này khoá đầu ra của TV1 (event_to_dict) luôn khớp hợp đồng đó,
để sau này có ai sửa code cũng không làm lệch khiến bot TV5 từ chối gói tin.

Nguồn hợp đồng: telegram-bot/app/main.py (class AlertPayload) của TV5 — đã chốt.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.alert_engine import AlertEvent, AlertKind
from app.checkers.base import CheckOutcome
from app.notifier import event_to_dict

# Hợp đồng TV5 đang mong đợi (giữ khớp với AlertPayload bên telegram-bot).
EXPECTED_KEYS = {
    "monitor_id", "monitor_name", "kind", "severity", "message", "at",
    "response_time_ms", "status_code", "ssl_days_left",
}
ALLOWED_KINDS = {"down", "recovered", "flapping", "stabilized", "ssl_expiring"}
ALLOWED_SEVERITY = {"critical", "warning", "info"}


def _event(kind: AlertKind, outcome: CheckOutcome) -> AlertEvent:
    return AlertEvent(
        monitor_id=1,
        monitor_name="Shop API",
        kind=kind,
        message="thông điệp mẫu",
        at=datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc),
        outcome=outcome,
    )


def test_payload_has_exactly_the_contract_keys():
    d = event_to_dict(_event(AlertKind.DOWN, CheckOutcome.down("x")))
    assert set(d.keys()) == EXPECTED_KEYS


def test_all_kinds_and_severities_are_within_tv5_accepted_sets():
    outcome = CheckOutcome.up(response_time_ms=120.0, status_code=200)
    for kind in AlertKind:
        d = event_to_dict(_event(kind, outcome))
        assert d["kind"] in ALLOWED_KINDS, f"kind lạ: {d['kind']}"
        assert d["severity"] in ALLOWED_SEVERITY, f"severity lạ: {d['severity']}"


def test_field_types_match_contract():
    d = event_to_dict(
        _event(AlertKind.DOWN, CheckOutcome.up(response_time_ms=99.5, status_code=200))
    )
    assert isinstance(d["monitor_id"], int) and d["monitor_id"] > 0
    assert isinstance(d["monitor_name"], str) and d["monitor_name"]
    assert isinstance(d["message"], str) and d["message"]
    assert isinstance(d["response_time_ms"], float)
    assert isinstance(d["status_code"], int)
    # 'at' phải là ISO string parse lại được thành datetime.
    assert isinstance(d["at"], str)
    datetime.fromisoformat(d["at"])


def test_nullable_fields_can_be_none():
    d = event_to_dict(_event(AlertKind.DOWN, CheckOutcome.down("refused")))
    assert d["response_time_ms"] is None
    assert d["status_code"] is None
    assert d["ssl_days_left"] is None
