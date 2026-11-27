"""配置流程测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries, data_entry_flow
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vatti_water_heater.api import VattiClient
from custom_components.vatti_water_heater.const import (
    CONF_FAMILY_ID,
    CONF_PHONE,
    CONF_TOKEN,
    DOMAIN,
)

PHONE = "13800138000"
TICKET = json.dumps(
    {
        "captcha_id": "cid",
        "lot_number": "lot",
        "captcha_output": "out",
        "pass_token": "pass",
        "gen_time": "gen",
    }
)


async def test_user_form(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_invalid_phone(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PHONE: "123"}
    )
    assert result["errors"] == {CONF_PHONE: "invalid_phone"}


async def test_duplicate_account_aborts(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_PHONE: PHONE, CONF_TOKEN: "tk"}, unique_id=PHONE
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PHONE: PHONE}
    )
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_full_flow(hass) -> None:
    assert await async_setup_component(hass, "http", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch.object(VattiClient, "send_sms_code", new=AsyncMock()) as send:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PHONE: PHONE}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "captcha"
        assert "captcha_link" in result["description_placeholders"]

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"ticket": TICKET}
        )
        send.assert_awaited_once()
        assert result["step_id"] == "sms"

    with patch.object(
        VattiClient, "login_with_sms", new=AsyncMock(return_value="new-token")
    ), patch.object(VattiClient, "user_info", new=AsyncMock(return_value={})), patch.object(
        VattiClient,
        "families",
        new=AsyncMock(return_value=[{"familyId": "f1", "name": "Home"}]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"code": "1234"}
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TOKEN] == "new-token"
    assert result["data"][CONF_PHONE] == PHONE


async def test_family_selection(hass) -> None:
    assert await async_setup_component(hass, "http", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch.object(VattiClient, "send_sms_code", new=AsyncMock()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PHONE: PHONE}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"ticket": TICKET}
        )
    with patch.object(
        VattiClient, "login_with_sms", new=AsyncMock(return_value="tk")
    ), patch.object(VattiClient, "user_info", new=AsyncMock()), patch.object(
        VattiClient,
        "families",
        new=AsyncMock(
            return_value=[
                {"familyId": "f1", "name": "Home"},
                {"familyId": "f2", "name": "Villa"},
            ]
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"code": "1234"}
        )
        assert result["step_id"] == "family"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_FAMILY_ID: "f2"}
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_FAMILY_ID] == "f2"


async def test_reauth_flow(hass) -> None:
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PHONE: PHONE, CONF_TOKEN: "old", CONF_FAMILY_ID: "f1"},
        unique_id=PHONE,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "captcha"

    with patch.object(VattiClient, "send_sms_code", new=AsyncMock()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"ticket": TICKET}
        )
    with patch.object(
        VattiClient, "login_with_sms", new=AsyncMock(return_value="fresh")
    ), patch.object(VattiClient, "user_info", new=AsyncMock()), patch.object(
        hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"code": "0000"}
        )

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == "fresh"
    assert entry.data[CONF_FAMILY_ID] == "f1"


async def test_options_flow(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PHONE: PHONE, CONF_TOKEN: "tk", CONF_FAMILY_ID: "f1"},
        options={},
        unique_id=PHONE,
    )
    entry.add_to_hass(hass)

    with patch.object(
        VattiClient,
        "families",
        new=AsyncMock(
            return_value=[
                {"familyId": "f1", "name": "Home"},
                {"familyId": "f2", "name": "Villa"},
            ]
        ),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["step_id"] == "init"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"poll_interval": 30, "enable_energy": False, "family_id": "f2"},
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert entry.options["poll_interval"] == 30
    assert entry.options["enable_energy"] is False
    assert entry.data[CONF_FAMILY_ID] == "f2"


async def test_stale_flow_does_not_block_retry(hass) -> None:
    """上一次流程卡在滑块步骤时，重新添加不能被 already_in_progress 挡住。"""
    assert await async_setup_component(hass, "http", {})

    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    first = await hass.config_entries.flow.async_configure(
        first["flow_id"], {CONF_PHONE: PHONE}
    )
    assert first["step_id"] == "captcha"

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    second = await hass.config_entries.flow.async_configure(
        second["flow_id"], {CONF_PHONE: PHONE}
    )
    assert second["type"] == data_entry_flow.FlowResultType.FORM
    assert second["step_id"] == "captcha"
    # 旧流程已被清理
    remaining = {
        item["flow_id"] for item in hass.config_entries.flow.async_progress()
    }
    assert first["flow_id"] not in remaining


async def test_captcha_url_carries_flow_id(hass) -> None:
    """滑块页地址要带上 flow_id，才能自动推进流程。"""
    assert await async_setup_component(hass, "http", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PHONE: PHONE}
    )
    url = result["description_placeholders"]["captcha_url"]
    assert f"flow_id={result['flow_id']}" in url


async def test_advance_flow_after_ticket(hass) -> None:
    """滑块页回传票据后，流程应自动推进到短信验证码步骤。"""
    from custom_components.vatti_water_heater.captcha import STORE, _advance_flow
    from custom_components.vatti_water_heater.models import CaptchaTicket

    assert await async_setup_component(hass, "http", {})
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_PHONE: PHONE}
    )
    assert flow["step_id"] == "captcha"

    STORE.put(CaptchaTicket.from_json(json.loads(TICKET)))
    with patch.object(VattiClient, "send_sms_code", new=AsyncMock()) as send:
        await _advance_flow(hass, flow["flow_id"])
        await hass.async_block_till_done()

    send.assert_awaited_once()
    progress = {
        item["flow_id"]: item for item in hass.config_entries.flow.async_progress()
    }
    assert progress[flow["flow_id"]]["step_id"] == "sms"


async def test_advance_flow_ignores_unknown_flow(hass) -> None:
    """flow 已经结束（用户关了页面）时不应抛异常。"""
    from custom_components.vatti_water_heater.captcha import _advance_flow

    assert await async_setup_component(hass, "http", {})
    await _advance_flow(hass, "nonexistent-flow-id")
