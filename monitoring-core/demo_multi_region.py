"""Demo multi-region — KHÔNG cần mạng, chạy tức thì.

Minh hoạ: cùng một website, kiểm tra từ nhiều khu vực để phân biệt
"web sập thật" với "chỉ một đường mạng chết".

Chạy:  python demo_multi_region.py
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.checkers.base import CheckOutcome
from app.regions import RegionResult, aggregate_regions

UP = lambda ms: CheckOutcome.up(response_time_ms=ms)  # noqa: E731
DOWN = CheckOutcome.down(error="Connection timeout")


def show(title: str, results: list[RegionResult], **kw) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)
    for r in results:
        mark = f"UP ({r.outcome.response_time_ms}ms)" if r.outcome.is_up else "DOWN"
        print(f"  {r.region:<10} {mark}")
    agg = aggregate_regions(results, **kw)
    print(f"  --> Kết luận: [{agg.verdict.value.upper()}] {agg.message}")
    print(f"      Đưa vào Alert Engine dưới dạng: "
          f"{'UP (không báo sập)' if agg.outcome.is_up else 'DOWN (sẽ báo sập)'}")


if __name__ == "__main__":
    regions = lambda **kw: [RegionResult(k, v) for k, v in kw.items()]  # noqa: E731

    show(
        "Kịch bản 1: Mọi khu vực đều vào được -> web khoẻ",
        regions(HaNoi=UP(40), Singapore=UP(120), US=UP(230)),
    )
    show(
        "Kịch bản 2: CHỈ 1 khu vực lỗi -> nghi lỗi đường mạng, KHÔNG báo sập",
        regions(HaNoi=DOWN, Singapore=UP(120), US=UP(230)),
    )
    show(
        "Kịch bản 3: MỌI khu vực đều lỗi -> web SẬP THẬT, báo ngay",
        regions(HaNoi=DOWN, Singapore=DOWN, US=DOWN),
    )
    show(
        "Kịch bản 4: 2/3 khu vực lỗi + hạ ngưỡng xuống 2 -> coi là sập",
        regions(HaNoi=DOWN, Singapore=DOWN, US=UP(230)),
        min_down_for_outage=2,
    )
    print()
