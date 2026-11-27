"""纯函数单元测试：签名算法。"""

from __future__ import annotations

import hashlib

from custom_components.vatti_water_heater.const import ECM_SECRET, SIGN_SECRET
from custom_components.vatti_water_heater.signing import calc_sign, calc_sign_ecm


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def test_sign_sorts_and_skips_empty() -> None:
    payload = {"b": "x", "a": "1", "c": None, "d": "", "sign": "ignored"}
    assert calc_sign(payload) == _md5("a=1&b=x&" + SIGN_SECRET)


def test_sign_renders_bool_and_numbers() -> None:
    payload = {"flag": True, "off": False, "count": 3, "ratio": 1.5}
    expected = _md5("count=3&flag=true&off=false&ratio=1.5&" + SIGN_SECRET)
    assert calc_sign(payload) == expected


def test_sign_nested_list_keeps_order() -> None:
    payload = {"items": [{"b": 1, "a": 2}, 3]}
    expected = _md5('items=[{"a":2,"b":1},3]&' + SIGN_SECRET)
    assert calc_sign(payload) == expected


def test_sign_ecm_canonical() -> None:
    payload = {"b": "2", "a": "1", "skip": None}
    canonical = "a=1&b=2"
    assert calc_sign_ecm(payload) == _md5(canonical + "&" + ECM_SECRET)


def test_sign_is_stable() -> None:
    payload = {
        "accessKeyId": "key",
        "accessToken": "token",
        "timestamp": "1700000000000",
        "deviceId": "d1",
    }
    assert calc_sign(payload) == calc_sign(dict(payload))
