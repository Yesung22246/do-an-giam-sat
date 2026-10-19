"""Alert Engine — bộ não chống spam cảnh báo (phần nghiên cứu sâu của TV1).

Vấn đề: nếu cứ "lỗi là báo" thì khi web chập chờn, người dùng nhận hàng chục
tin nhắn rác -> mất tin tưởng, bỏ qua cả cảnh báo thật.

Giải pháp: một máy trạng thái (state machine) cho từng monitor, với 4 cơ chế:

1. XÁC NHẬN LỖI (retries): chỉ coi là DOWN khi lỗi liên tiếp đủ số lần.
   -> lọc nhiễu mạng tạm thời, tránh báo nhầm.
2. XÁC NHẬN PHỤC HỒI: chỉ coi là UP lại khi thành công liên tiếp đủ số lần.
3. PHÁT HIỆN FLAPPING: nếu trạng thái đổi UP<->DOWN quá nhiều lần trong một
   khoảng thời gian -> gộp thành 1 cảnh báo "chập chờn" duy nhất, nín các
   cảnh báo lên/xuống lẻ tẻ cho tới khi ổn định trở lại.
4. CHỐNG LẶP (dedup): mỗi lần chuyển trạng thái chỉ phát đúng 1 sự kiện;
   cảnh báo SSL sắp hết hạn chỉ gửi 1 lần cho tới khi trở lại an toàn.

Engine KHÔNG tự gửi tin nhắn. Nó chỉ trả về danh sách AlertEvent;
việc gửi đi do Notifier lo (tách bạch để test và để TV5 cắm Telegram vào).
"""
from __future__ import annotations

import enum
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .checkers.base import CheckOutcome
from .models import CheckStatus


class AlertKind(str, enum.Enum):
    DOWN = "down"              # dịch vụ sập (đã xác nhận)
    RECOVERED = "recovered"    # dịch vụ hoạt động trở lại
    FLAPPING = "flapping"      # chập chờn lên xuống liên tục
    STABILIZED = "stabilized"  # hết chập chờn, chốt trạng thái cuối cùng
    SSL_EXPIRING = "ssl_expiring"  # chứng chỉ SSL sắp hết hạn


SEVERITY = {
    AlertKind.DOWN: "critical",
    AlertKind.RECOVERED: "info",
    AlertKind.FLAPPING: "warning",
    AlertKind.STABILIZED: "info",
    AlertKind.SSL_EXPIRING: "warning",
}


@dataclass
class AlertEvent:
    monitor_id: int
    monitor_name: str
    kind: AlertKind
    message: str
    at: datetime
    outcome: CheckOutcome | None = None

    @property
    def severity(self) -> str:
        return SEVERITY[self.kind]


@dataclass
class AlertPolicy:
    """Các ngưỡng điều chỉnh hành vi cảnh báo."""
    retries: int = 3                 # số lần lỗi liên tiếp để xác nhận DOWN
    recovery_threshold: int = 2      # số lần OK liên tiếp để xác nhận phục hồi
    flap_window: timedelta = timedelta(minutes=10)  # cửa sổ xét flapping
    flap_threshold: int = 5          # số lần đổi trạng thái trong cửa sổ -> flapping
    ssl_warn_days: int = 14          # cảnh báo khi SSL còn <= số ngày này


@dataclass
class _MonitorState:
    confirmed: CheckStatus = CheckStatus.UP  # trạng thái đã "công bố"
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    transitions: deque[datetime] = field(default_factory=deque)  # mốc đổi trạng thái
    flapping_active: bool = False
    ssl_notified: bool = False
    last_cause: str | None = None

    def to_dict(self) -> dict:
        """Chuyển thành dict để lưu xuống DB."""
        return {
            "confirmed": self.confirmed.value,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "transitions": [t.isoformat() for t in self.transitions],
            "flapping_active": self.flapping_active,
            "ssl_notified": self.ssl_notified,
            "last_cause": self.last_cause,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "_MonitorState":
        """Khôi phục từ dict đã lưu trong DB (khi service khởi động lại)."""
        return cls(
            confirmed=CheckStatus(data["confirmed"]),
            consecutive_failures=data.get("consecutive_failures", 0),
            consecutive_successes=data.get("consecutive_successes", 0),
            transitions=deque(
                datetime.fromisoformat(t) for t in data.get("transitions", [])
            ),
            flapping_active=data.get("flapping_active", False),
            ssl_notified=data.get("ssl_notified", False),
            last_cause=data.get("last_cause"),
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AlertEngine:
    """Giữ trạng thái của mọi monitor và quyết định khi nào phát cảnh báo.

    Dùng: engine.process(monitor_id, name, outcome) -> list[AlertEvent].
    Thuần trong bộ nhớ, không chạm DB, nên unit-test rất dễ.
    """

    def __init__(self, policy: AlertPolicy | None = None) -> None:
        self.policy = policy or AlertPolicy()
        self._states: dict[int, _MonitorState] = {}

    def state_of(self, monitor_id: int) -> CheckStatus:
        return self._states.setdefault(monitor_id, _MonitorState()).confirmed

    def has_state(self, monitor_id: int) -> bool:
        return monitor_id in self._states

    def load_state(self, monitor_id: int, data: dict) -> None:
        """Nạp trạng thái đã lưu (gọi khi service khởi động lại)."""
        self._states[monitor_id] = _MonitorState.from_dict(data)

    def dump_state(self, monitor_id: int) -> dict | None:
        """Lấy trạng thái hiện tại để lưu xuống DB."""
        st = self._states.get(monitor_id)
        return st.to_dict() if st else None

    def process(
        self,
        monitor_id: int,
        monitor_name: str,
        outcome: CheckOutcome,
        now: datetime | None = None,
        policy: AlertPolicy | None = None,
    ) -> list[AlertEvent]:
        # Mỗi monitor có thể có ngưỡng riêng (retries, ssl_warn_days...).
        # Truyền policy riêng vào đây thay vì sửa self.policy dùng chung — tránh
        # việc các monitor chạy song song (async) đạp ngưỡng của nhau.
        now = now or _utcnow()
        p = policy or self.policy
        st = self._states.setdefault(monitor_id, _MonitorState())
        events: list[AlertEvent] = []

        # 1) Cập nhật chuỗi thành công / thất bại liên tiếp.
        if outcome.is_up:
            st.consecutive_successes += 1
            st.consecutive_failures = 0
        else:
            st.consecutive_failures += 1
            st.consecutive_successes = 0
            if outcome.error:
                st.last_cause = outcome.error

        # 2) Cảnh báo SSL sắp hết hạn (độc lập với UP/DOWN, chỉ gửi 1 lần).
        days = outcome.ssl_days_left
        if days is not None and 0 <= days <= p.ssl_warn_days:
            if not st.ssl_notified:
                st.ssl_notified = True
                events.append(
                    AlertEvent(
                        monitor_id, monitor_name, AlertKind.SSL_EXPIRING,
                        f"Chứng chỉ SSL còn {days} ngày là hết hạn.",
                        now, outcome,
                    )
                )
        elif days is not None and days > p.ssl_warn_days:
            st.ssl_notified = False  # trở lại an toàn -> cho phép cảnh báo lần sau

        # 3) Xác định có chuyển trạng thái đã-xác-nhận hay không.
        transition: AlertKind | None = None
        if (
            st.confirmed == CheckStatus.UP
            and not outcome.is_up
            and st.consecutive_failures >= p.retries
        ):
            st.confirmed = CheckStatus.DOWN
            transition = AlertKind.DOWN
        elif (
            st.confirmed == CheckStatus.DOWN
            and outcome.is_up
            and st.consecutive_successes >= p.recovery_threshold
        ):
            st.confirmed = CheckStatus.UP
            transition = AlertKind.RECOVERED

        if transition is not None:
            st.transitions.append(now)

        # 4) Dọn các mốc chuyển trạng thái đã quá cũ, rồi xét flapping.
        cutoff = now - p.flap_window
        while st.transitions and st.transitions[0] < cutoff:
            st.transitions.popleft()
        flapping_now = len(st.transitions) >= p.flap_threshold

        if transition is not None:
            if flapping_now:
                # Đang chập chờn: nén cảnh báo lẻ, chỉ báo flapping đúng 1 lần.
                if not st.flapping_active:
                    st.flapping_active = True
                    events.append(
                        AlertEvent(
                            monitor_id, monitor_name, AlertKind.FLAPPING,
                            "Dịch vụ chập chờn (lên/xuống liên tục). "
                            "Tạm gộp cảnh báo cho tới khi ổn định.",
                            now, outcome,
                        )
                    )
            else:
                events.append(self._state_event(st, monitor_id, monitor_name, now, outcome))
        else:
            # Không có chuyển trạng thái lần này: kiểm tra xem flapping đã chấm dứt chưa.
            if st.flapping_active and not flapping_now:
                st.flapping_active = False
                events.append(
                    AlertEvent(
                        monitor_id, monitor_name, AlertKind.STABILIZED,
                        f"Đã ổn định trở lại — trạng thái hiện tại: "
                        f"{'HOẠT ĐỘNG' if st.confirmed == CheckStatus.UP else 'SẬP'}.",
                        now, outcome,
                    )
                )

        return events

    def _state_event(
        self,
        st: _MonitorState,
        monitor_id: int,
        monitor_name: str,
        now: datetime,
        outcome: CheckOutcome,
    ) -> AlertEvent:
        if st.confirmed == CheckStatus.DOWN:
            cause = st.last_cause or (outcome.error or "không rõ nguyên nhân")
            return AlertEvent(
                monitor_id, monitor_name, AlertKind.DOWN,
                f"Dịch vụ SẬP. Nguyên nhân: {cause}", now, outcome,
            )
        return AlertEvent(
            monitor_id, monitor_name, AlertKind.RECOVERED,
            "Dịch vụ đã HOẠT ĐỘNG trở lại.", now, outcome,
        )
