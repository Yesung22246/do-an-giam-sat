"""Multi-region probe — kiểm tra từ nhiều khu vực để phân biệt:

- Web SẬP THẬT: mọi khu vực đều không truy cập được.
- Lỗi ĐƯỜNG MẠNG: chỉ một vài khu vực không vào được, nơi khác vẫn bình thường
  -> không nên hô hoán "web sập" vì thực ra web vẫn sống.

Trong thực tế, mỗi "khu vực" là một agent chạy trên máy chủ ở vùng địa lý khác
nhau (vd Hà Nội, Singapore, US), tự kiểm tra rồi báo kết quả về. Module này lo
phần LÕI: tổng hợp kết quả từ các khu vực thành một kết luận chung + phân loại.

Đây là điểm giúp sản phẩm "xịn" hơn Uptime Kuma (vốn chỉ probe từ 1 chỗ).
"""
from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass
from typing import Awaitable, Callable

from .checkers import run_check
from .checkers.base import CheckOutcome
from .models import Monitor

# Một "runner" là hàm bất đồng bộ kiểm tra 1 monitor và trả về CheckOutcome.
RegionRunner = Callable[[Monitor], Awaitable[CheckOutcome]]


class RegionVerdict(str, enum.Enum):
    UP = "up"              # mọi khu vực đều vào được
    DEGRADED = "degraded"  # một số khu vực lỗi -> nghi lỗi đường mạng, chưa sập hẳn
    DOWN = "down"          # đủ số khu vực lỗi -> coi là sập thật


@dataclass
class RegionResult:
    """Kết quả kiểm tra từ 1 khu vực (do 1 agent báo về)."""
    region: str
    outcome: CheckOutcome


@dataclass
class AggregatedResult:
    verdict: RegionVerdict
    outcome: CheckOutcome          # kết quả gộp để đưa vào Alert Engine
    failed_regions: list[str]
    up_regions: list[str]
    total_regions: int
    message: str


def aggregate_regions(
    results: list[RegionResult],
    min_down_for_outage: int | None = None,
) -> AggregatedResult:
    """Gộp kết quả nhiều khu vực thành 1 kết luận.

    Quy tắc:
    - Không khu vực nào lỗi            -> UP.
    - Số khu vực lỗi >= ngưỡng sập     -> DOWN (sập thật).
    - Lỗi lác đác (dưới ngưỡng)        -> DEGRADED (nghi lỗi đường mạng).

    `min_down_for_outage`: số khu vực phải lỗi mới coi là sập thật.
    Mặc định = TẤT CẢ khu vực (strict nhất, tránh báo nhầm). Có thể hạ xuống
    (vd quá bán) nếu muốn nhạy hơn.

    Kết quả gộp (`outcome`) đưa vào Alert Engine:
    - DOWN     -> outcome DOWN (engine sẽ xác nhận & cảnh báo như bình thường).
    - UP/DEGRADED -> outcome UP (web vẫn tới được từ đâu đó), nhưng verdict giữ
      DEGRADED để lớp trên có thể cảnh báo mức "warning" nếu muốn.
    """
    if not results:
        raise ValueError("Cần ít nhất 1 kết quả khu vực để tổng hợp")

    total = len(results)
    failed = [r.region for r in results if not r.outcome.is_up]
    up = [r.region for r in results if r.outcome.is_up]
    threshold = min_down_for_outage if min_down_for_outage is not None else total

    # Thời gian phản hồi gộp = trung bình các khu vực vào được.
    resp = [
        r.outcome.response_time_ms
        for r in results
        if r.outcome.is_up and r.outcome.response_time_ms is not None
    ]
    avg_ms = round(sum(resp) / len(resp), 1) if resp else None

    if not failed:
        return AggregatedResult(
            verdict=RegionVerdict.UP,
            outcome=CheckOutcome.up(response_time_ms=avg_ms),
            failed_regions=[],
            up_regions=up,
            total_regions=total,
            message=f"Tất cả {total} khu vực đều truy cập được.",
        )

    if len(failed) >= threshold:
        return AggregatedResult(
            verdict=RegionVerdict.DOWN,
            outcome=CheckOutcome.down(
                error=f"Sập ở toàn bộ {len(failed)}/{total} khu vực kiểm tra"
            ),
            failed_regions=failed,
            up_regions=up,
            total_regions=total,
            message=f"SẬP THẬT: {len(failed)}/{total} khu vực không truy cập được.",
        )

    # Lỗi lác đác -> nghi lỗi đường mạng, web vẫn sống.
    return AggregatedResult(
        verdict=RegionVerdict.DEGRADED,
        outcome=CheckOutcome.up(response_time_ms=avg_ms),
        failed_regions=failed,
        up_regions=up,
        total_regions=total,
        message=(
            f"Chỉ {len(failed)}/{total} khu vực lỗi ({', '.join(failed)}) — "
            "nghi lỗi đường mạng, web vẫn truy cập được từ nơi khác."
        ),
    )


async def check_from_regions(
    monitor: Monitor,
    region_runners: dict[str, RegionRunner],
) -> list[RegionResult]:
    """Chạy kiểm tra từ nhiều khu vực SONG SONG, trả về kết quả từng khu vực.

    `region_runners`: map {tên khu vực -> hàm kiểm tra của khu vực đó}.
    - Thực tế: mỗi runner gọi tới agent chạy ở một máy chủ vùng khác nhau.
    - Mô phỏng/đồ án: dùng chung `run_check` cục bộ cho vài tên khu vực
      (xem helper `local_regions` bên dưới) — đúng cơ chế, chỉ khác là chưa đặt
      agent ở nhiều nơi thật.
    """
    names = list(region_runners.keys())

    async def one(name: str) -> RegionResult:
        outcome = await region_runners[name](monitor)
        return RegionResult(region=name, outcome=outcome)

    results = await asyncio.gather(*(one(n) for n in names))
    return list(results)


def local_regions(*names: str) -> dict[str, RegionRunner]:
    """Tạo nhanh bộ runner cục bộ (cùng dùng `run_check`) cho việc chạy thử.

    Khi triển khai thật, thay mỗi runner bằng lời gọi tới agent ở vùng tương ứng.
    """
    return {name: run_check for name in names}
