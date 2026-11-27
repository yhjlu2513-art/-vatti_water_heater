"""集成加载、实体与控制测试。"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.vatti_water_heater.api import VattiClient
from custom_components.vatti_water_heater.const import (
    CONF_FAMILY_ID,
    CONF_PHONE,
    CONF_TOKEN,
    DOMAIN,
)
from custom_components.vatti_water_heater.coordinator import (
    VattiCoordinator,
    VattiRuntime,
)
from custom_components.vatti_water_heater.exceptions import VattiAuthError

PHONE = "13800138000"


async def test_entities_created(hass, entry) -> None:
    water_heater = hass.states.get("water_heater.kitchen_heater")
    assert water_heater is not None
    assert water_heater.state == "标准"
    assert water_heater.attributes["temperature"] == 45
    assert water_heater.attributes["current_temperature"] == 41.5
    assert water_heater.attributes["operation_list"] == ["标准", "AI智洗", "智慧云感温"]

    outlet = hass.states.get("sensor.kitchen_heater_outlet_temperature")
    assert outlet is not None and outlet.state == "41.5"

    preheat = hass.states.get("switch.kitchen_heater_one_key_preheat")
    assert preheat is not None and preheat.state == "on"

    waterfall = hass.states.get("switch.kitchen_heater_waterfall_bath")
    assert waterfall is not None and waterfall.state == "off"

    online = hass.states.get("binary_sensor.kitchen_heater_online")
    assert online is not None and online.state == "on"

    assert hass.states.get("sensor.kitchen_heater_gas_today") is not None
    assert hass.states.get("button.kitchen_heater_refresh_now") is not None


async def test_turn_off_optimistic_and_confirm(hass, entry, cloud_api) -> None:
    await hass.services.async_call(
        "water_heater",
        "turn_off",
        {"entity_id": "water_heater.kitchen_heater"},
        blocking=True,
    )
    cloud_api["send_command"].assert_awaited_with("dev-1", {"powerStat": "0"})
    assert hass.states.get("water_heater.kitchen_heater").state == "off"

    # 2 秒后确认刷新，设备仍上报开机，状态应回到真实值
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert hass.states.get("water_heater.kitchen_heater").state == "标准"


async def test_switch_bit_math(hass, entry, cloud_api) -> None:
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.kitchen_heater_waterfall_bath"},
        blocking=True,
    )
    # func_switch 原值 8（一键预热），打开 bit5 瀑布浴后应为 40
    cloud_api["send_command"].assert_awaited_with("dev-1", {"func_switch": "40"})


async def test_set_temperature_clamped(hass, entry, cloud_api) -> None:
    await hass.services.async_call(
        "water_heater",
        "set_temperature",
        {"entity_id": "water_heater.kitchen_heater", "temperature": 80},
        blocking=True,
    )
    cloud_api["send_command"].assert_awaited_with("dev-1", {"heater_temp": "60"})


async def test_refresh_service(hass, entry, cloud_api) -> None:
    count = cloud_api["properties"].await_count
    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    assert cloud_api["properties"].await_count > count


async def test_operation_mode_ai_wash(hass, entry, cloud_api) -> None:
    await hass.services.async_call(
        "water_heater",
        "set_operation_mode",
        {
            "entity_id": "water_heater.kitchen_heater",
            "operation_mode": "AI智洗",
        },
        blocking=True,
    )
    cloud_api["send_command"].assert_awaited_with("dev-1", {"func_swit1": "32"})


async def test_unload(hass, entry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("water_heater.kitchen_heater")
    # 卸载后实体由 restore_state 标记为 unavailable
    assert state is None or state.state == "unavailable"


async def test_auth_failure_triggers_reauth(hass, cloud_api) -> None:
    cloud_api["properties"].side_effect = VattiAuthError("token expired")
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PHONE: PHONE, CONF_TOKEN: "tk", CONF_FAMILY_ID: "f1"},
        unique_id=PHONE,
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert any(
        flow["context"].get("source") == SOURCE_REAUTH for flow in flows
    ), flows


async def test_coordinator_raises_auth_failed(hass, cloud_api) -> None:
    config_entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_PHONE: PHONE, CONF_TOKEN: "tk"}
    )
    config_entry.add_to_hass(hass)
    client = VattiClient(AsyncMock(), token="tk")
    cloud_api["properties"].side_effect = VattiAuthError("expired")
    coordinator = VattiCoordinator(
        hass, config_entry, client, VattiRuntime(client=client)
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_force_zero_cold_kind(hass, cloud_api) -> None:
    """选项里指定零冷水机型后，应按零冷水能力表生成预热类开关。"""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Vatti zero cold",
        data={CONF_PHONE: PHONE, CONF_TOKEN: "tk", CONF_FAMILY_ID: "f1"},
        options={"device_kind": "zero_cold"},
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("switch.kitchen_heater_quick_heat") is not None
    assert hass.states.get("switch.kitchen_heater_bathtub_fill") is not None
    # 燃气恒温机才有的「节能洗 / 循环恒温」，说明确实换了能力表
    assert hass.states.get("switch.kitchen_heater_eco") is None
