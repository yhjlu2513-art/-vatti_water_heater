"""能耗统计解析（纯函数）。

接口 ``/ecm/getNewWaterGas`` 一次返回年度汇总与最近若干周分桶，
分桶里带逐日明细。口径与华帝 App 能耗页一致：

- 气：年度值单位 m³，周桶/日明细为 0.01 m³ 定点；
- 水：年度值单位 L（App 显示吨），周桶/日明细单位 m³；
- 本周 = 包含今天的周桶的累计值；
- 今日 = 该周桶内与今天匹配的日明细，当天无用气/水时为 0。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(slots=True)
class EnergyOverview:
    year: float = 0.0
    buckets: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class EnergySummary:
    today: float | None = None
    week: float | None = None
    year: float | None = None
    week_series: dict[str, float] = field(default_factory=dict)


def _decode(value: Any, default: Any) -> Any:
    """接口的汇总字段是「JSON 字符串套 JSON」，逐层解码。"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return default if value is None else value


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        for key in ("value", "total", "c", "consumption"):
            parsed = _as_float(value.get(key))
            if parsed is not None:
                return parsed
    return None


def parse_overview(content: dict[str, Any], is_gas: bool) -> EnergyOverview:
    """解析年度汇总与周分桶。"""
    year_raw = _decode(content.get("totalYearGas" if is_gas else "totalYearWater"), {})
    year_value = _as_float(year_raw) or 0.0
    # 水的年度值单位是升，换算为立方米（App 显示吨）
    if not is_gas:
        year_value = round(year_value / 1000.0, 3)
    buckets = _decode(content.get("dataList"), [])
    return EnergyOverview(
        year=round(year_value, 3),
        buckets=[item for item in buckets if isinstance(item, dict)]
        if isinstance(buckets, list)
        else [],
    )


def _bucket_contains(bucket: dict[str, Any], today: date) -> bool:
    details = bucket.get("details")
    if isinstance(details, list):
        for item in details:
            try:
                if (
                    int(item.get("month", 0)) == today.month
                    and int(item.get("day", 0)) == today.day
                ):
                    return True
            except (TypeError, ValueError, AttributeError):
                continue
    # 没有今天的明细时按结束日期判断：本周桶的 endDay 尚未到
    try:
        end_day = int(bucket.get("endDay", 0))
        end_month = int(bucket.get("endMonth", bucket.get("beginMonth", 0)))
    except (TypeError, ValueError):
        return False
    return (end_month, end_day) >= (today.month, today.day)


def current_week_bucket(
    buckets: list[dict[str, Any]], today: date
) -> dict[str, Any] | None:
    for bucket in reversed(buckets):
        if _bucket_contains(bucket, today):
            return bucket
    return buckets[-1] if buckets else None


def _today_detail(bucket: dict[str, Any], today: date) -> float | None:
    details = bucket.get("details")
    if not isinstance(details, list):
        return None
    for item in details:
        try:
            if (
                int(item.get("month", 0)) == today.month
                and int(item.get("day", 0)) == today.day
            ):
                return _as_float(item.get("value")) or 0.0
        except (TypeError, ValueError, AttributeError):
            continue
    return None


def summarize(overview: EnergyOverview, is_gas: bool, today: date) -> EnergySummary:
    """把年度汇总与分桶压缩成今日/本周/年度三个值 + 周曲线。"""
    scale = 0.01 if is_gas else 1.0
    series: dict[str, float] = {}
    for bucket in overview.buckets:
        label = str(bucket.get("time") or "")
        if label:
            series[label] = round((_as_float(bucket.get("value")) or 0.0) * scale, 3)

    summary = EnergySummary(year=overview.year or None, week_series=series)
    bucket = current_week_bucket(overview.buckets, today)
    if bucket is None:
        return summary
    summary.week = round((_as_float(bucket.get("value")) or 0.0) * scale, 3)
    detail = _today_detail(bucket, today)
    summary.today = round(detail * scale, 4) if detail is not None else 0.0
    return summary
