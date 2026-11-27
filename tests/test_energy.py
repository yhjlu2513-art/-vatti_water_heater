"""能耗解析测试。"""

from __future__ import annotations

import json
from datetime import date

from custom_components.vatti_water_heater.energy import (
    current_week_bucket,
    parse_overview,
    summarize,
)

TODAY = date(2026, 11, 24)

BUCKETS = [
    {
        "time": "2026-11-17",
        "value": 100,
        "beginDay": 17,
        "endDay": 23,
        "endMonth": 11,
        "details": [{"month": 11, "day": 17, "value": 20}],
    },
    {
        "time": "2026-11-24",
        "value": 200,
        "beginDay": 24,
        "endDay": 30,
        "endMonth": 11,
        "details": [{"month": 11, "day": 24, "value": 35}],
    },
]

GAS_PAYLOAD = {
    "totalYearGas": json.dumps({"value": 123.4}),
    "totalYearWater": json.dumps({"value": 56000}),
    "dataList": json.dumps(BUCKETS),
}


def test_parse_overview_decodes_double_json() -> None:
    gas = parse_overview(GAS_PAYLOAD, is_gas=True)
    assert gas.year == 123.4
    assert len(gas.buckets) == 2

    water = parse_overview(GAS_PAYLOAD, is_gas=False)
    # 年度水耗原始单位升，换算为立方米
    assert water.year == 56.0


def test_current_bucket_prefers_today() -> None:
    bucket = current_week_bucket(BUCKETS, TODAY)
    assert bucket is not None
    assert bucket["time"] == "2026-11-24"


def test_summarize_gas_scales_by_0_01() -> None:
    overview = parse_overview(GAS_PAYLOAD, is_gas=True)
    summary = summarize(overview, is_gas=True, today=TODAY)
    assert summary.year == 123.4
    assert summary.week == 2.0
    assert summary.today == 0.35
    assert summary.week_series["2026-11-17"] == 1.0
    assert summary.week_series["2026-11-24"] == 2.0


def test_summarize_water_uses_cubic_meters() -> None:
    overview = parse_overview(GAS_PAYLOAD, is_gas=False)
    summary = summarize(overview, is_gas=False, today=TODAY)
    assert summary.year == 56.0
    assert summary.week == 200.0
    assert summary.today == 35.0


def test_summarize_without_buckets() -> None:
    overview = parse_overview({"totalYearGas": '{"value": 1}'}, is_gas=True)
    summary = summarize(overview, is_gas=True, today=TODAY)
    assert summary.year == 1.0
    assert summary.week is None
    assert summary.today is None
