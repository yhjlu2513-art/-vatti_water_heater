"""物模型响应到 DeviceState 的转换。"""

from __future__ import annotations

from typing import Any

from .models import DeviceState


def build_state(device_id: str, props: dict[str, dict[str, Any]]) -> DeviceState:
    """过滤空值，拆分 value 与上报时间。"""
    values: dict[str, str] = {}
    timestamps: dict[str, int] = {}
    for identifier, item in props.items():
        value = item.get("value")
        if value is None or value == "":
            continue
        values[identifier] = str(value)
        timestamps[identifier] = int(item.get("time") or 0)
    return DeviceState(device_id=device_id, props=values, props_ts=timestamps)
