"""测试夹具。"""

from __future__ import annotations

from pathlib import Path

from unittest.mock import AsyncMock

import pytest

from homeassistant import loader
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vatti_water_heater.api import VattiClient
from custom_components.vatti_water_heater.const import (
    CONF_FAMILY_ID,
    CONF_PHONE,
    CONF_TOKEN,
    DOMAIN,
)
from custom_components.vatti_water_heater.energy import EnergyOverview

from fixtures import DEVICE, PROPS

pytest_plugins = ["pytest_homeassistant_custom_component"]

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(hass, enable_custom_integrations):
    """让 HA 从仓库根目录的 custom_components 加载本集成。"""
    hass.config.config_dir = str(REPO_ROOT)
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
    yield


PHONE = "13800138000"


@pytest.fixture
def cloud_api(monkeypatch):
    """把客户端所有网络方法替换为固定返回值。"""
    mocks = {
        "families": AsyncMock(return_value=[{"familyId": "f1", "name": "Home"}]),
        "devices": AsyncMock(return_value=[DEVICE]),
        "properties": AsyncMock(return_value=PROPS),
        "send_command": AsyncMock(return_value=None),
        "query_smart_temp": AsyncMock(return_value={"isEnabled": 0, "tempAdjData": []}),
        "save_smart_temp": AsyncMock(return_value=None),
        "energy_overview": AsyncMock(
            return_value=EnergyOverview(year=12.3, buckets=[])
        ),
        "user_info": AsyncMock(return_value={}),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(VattiClient, name, mock)
    return mocks


@pytest.fixture
async def entry(hass, cloud_api):
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Vatti test",
        data={
            CONF_PHONE: PHONE,
            CONF_TOKEN: "tk",
            CONF_FAMILY_ID: "f1",
        },
        options={},
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
