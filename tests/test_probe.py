"""位域探针服务测试。"""

from __future__ import annotations

import copy

from homeassistant.setup import async_setup_component

from custom_components.vatti_water_heater.const import DOMAIN

from fixtures import PROPS


async def _snapshot(hass, **data):
    return await hass.services.async_call(
        DOMAIN, "snapshot", data, blocking=True, return_response=True
    )


async def _diff(hass, **data):
    return await hass.services.async_call(
        DOMAIN, "diff_snapshot", data, blocking=True, return_response=True
    )


async def test_diff_reports_flipped_bit(hass, entry, cloud_api) -> None:
    """App 侧翻一位，服务应指出来并给出 SwitchSpec 代码行。"""
    await async_setup_component(hass, "persistent_notification", {})
    result = await _snapshot(hass)
    assert result["count"] == 1
    assert result["devices"][0]["fields"] > 0

    changed = copy.deepcopy(PROPS)
    changed["func_switch"]["value"] = "10"  # 8 -> 10，bit1 翻转
    cloud_api["properties"].return_value = changed

    result = await _diff(hass)
    report = result["devices"][0]
    assert report["device_id"] == "dev-1"
    assert len(report["changes"]) == 1
    change = report["changes"][0]
    assert change["field"] == "func_switch"
    assert (change["before"], change["after"]) == ("8", "10")
    assert change["bits"] == [1]

    text = result["report"]
    assert "func_switch" in text
    assert 'SwitchSpec("new_func_switch_bit1", "func_switch", 1' in text


async def test_diff_without_snapshot(hass, entry) -> None:
    """没做快照时给出明确提示而不是报错。"""
    await async_setup_component(hass, "persistent_notification", {})
    result = await _diff(hass)
    assert "先调用一次 snapshot" in result["devices"][0]["error"]


async def test_diff_no_change_hint(hass, entry) -> None:
    """没有任何变化时给出排查建议。"""
    await async_setup_component(hass, "persistent_notification", {})
    await _snapshot(hass)
    result = await _diff(hass)
    assert result["devices"][0]["changes"] == []
    assert "未检测到任何字段变化" in result["report"]


async def test_snapshot_device_filter(hass, entry) -> None:
    """按设备名过滤；匹配不到应报错。"""
    assert (await _snapshot(hass, device="Kitchen"))["count"] == 1

    from homeassistant.exceptions import HomeAssistantError

    try:
        await _snapshot(hass, device="不存在的设备")
    except HomeAssistantError as err:
        assert "没有匹配" in str(err)
    else:  # pragma: no cover - 未抛错即失败
        raise AssertionError("应当抛出 HomeAssistantError")


def test_diff_props_detects_multiple_fields() -> None:
    from custom_components.vatti_water_heater.probe import _diff_props

    prev = {"func_switch": "8", "rssi": "80", "owater_temp": "41.5"}
    current = {"func_switch": "10", "rssi": "80", "owater_temp": "42.0"}
    events = _diff_props(prev, current)
    assert [e["field"] for e in events] == ["func_switch", "owater_temp"]
    assert events[0]["bits"] == [1]
    assert events[1]["bits"] == []


def test_render_watch_timeline() -> None:
    from custom_components.vatti_water_heater.probe import _render_watch

    text = _render_watch(
        [
            {
                "name": "厨房热水器",
                "product_id": "GH000174",
                "start": 0,
                "running": False,
                "events": [
                    {"at": 12.5, "field": "func_switch", "before": "0", "after": "8", "bits": [3]},
                    {"at": 48.0, "field": "func_switch", "before": "8", "after": "40", "bits": [5]},
                ],
            }
        ]
    )
    assert "+12.5s" in text
    assert "bit3" in text and "bit5" in text
    assert 'SwitchSpec("new_func_switch_bit3", "func_switch", 3' in text


async def test_watch_services_registered(hass, entry) -> None:
    from custom_components.vatti_water_heater.const import DOMAIN

    for service in ("snapshot", "diff_snapshot", "watch", "watch_report"):
        assert hass.services.has_service(DOMAIN, service)


async def test_snapshot_exposes_raw_props(hass, entry) -> None:
    """快照服务要返回全部原始字段，方便对照 App 状态标定位号。"""
    from homeassistant.setup import async_setup_component

    await async_setup_component(hass, "persistent_notification", {})
    result = await _snapshot(hass)
    props = result["devices"][0]["props"]
    assert props["func_switch"] == "8"
    assert props["heater_temp"] == "45"
