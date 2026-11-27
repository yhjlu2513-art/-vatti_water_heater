"""数据模型测试。"""

from __future__ import annotations

import pytest

from custom_components.vatti_water_heater.exceptions import VattiCaptchaError
from custom_components.vatti_water_heater.models import (
    CaptchaTicket,
    DeviceState,
    VattiDevice,
)

DEVICE_PAYLOAD = {
    "id": "dev-1",
    "nickname": "厨房热水器",
    "productId": "GH000174",
    "productKey": "pk",
    "deviceName": "gh000174-abc",
    "model": "i12031",
    "categoryName": "燃气热水器",
    "familyId": "f1",
    "status": 1,
    "snCode": "SN123",
}


def test_device_from_api() -> None:
    device = VattiDevice.from_api(DEVICE_PAYLOAD)
    assert device.device_id == "dev-1"
    assert device.name == "厨房热水器"
    assert device.product_id == "GH000174"
    assert device.online is True
    assert device.serial_number == "SN123"


def test_device_online_by_description() -> None:
    payload = {**DEVICE_PAYLOAD, "status": 0, "statusDesc": "在线"}
    assert VattiDevice.from_api(payload).online is True
    payload = {**DEVICE_PAYLOAD, "status": 0, "statusDesc": "offline"}
    assert VattiDevice.from_api(payload).online is False


def test_device_requires_id() -> None:
    with pytest.raises(ValueError):
        VattiDevice.from_api({"nickname": "x"})


def test_state_helpers() -> None:
    state = DeviceState(
        device_id="d",
        props={"heater_temp": "45.0", "func_switch": "40", "bad": "x"},
        props_ts={"heater_temp": 1_700_000_000_000},
    )
    assert state.get_float("heater_temp") == 45.0
    assert state.get_int("func_switch") == 40
    assert state.bit("func_switch", 3) is True
    assert state.bit("func_switch", 2) is False
    assert state.bit("missing", 1) is None
    assert state.get_float("bad") is None
    assert state.reported_at("heater_temp") is not None
    assert state.reported_at("bad") is None


def test_captcha_ticket_camel_case() -> None:
    ticket = CaptchaTicket.from_json(
        {
            "captchaId": "cid",
            "lotNumber": "lot",
            "captchaOutput": "out",
            "passToken": "pass",
            "genTime": "t",
        }
    )
    assert ticket.to_request()["captchaId"] == "cid"
    assert ticket.to_request()["genTime"] == "t"


def test_captcha_ticket_wrapped_and_underscored() -> None:
    ticket = CaptchaTicket.from_json(
        {
            "result": {
                "captcha_id": "cid",
                "lot_number": "lot",
                "captcha_output": "out",
                "pass_token": "pass",
                "gen_time": "t",
            }
        }
    )
    assert ticket.captcha_id == "cid"


def test_captcha_ticket_missing_field() -> None:
    with pytest.raises(VattiCaptchaError):
        CaptchaTicket.from_json({"captcha_id": "cid"})
    with pytest.raises(VattiCaptchaError):
        CaptchaTicket.from_json("not json")
