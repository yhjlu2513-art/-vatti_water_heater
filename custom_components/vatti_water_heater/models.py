"""设备与状态数据模型（不依赖 Home Assistant）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .exceptions import VattiCaptchaError

_ONLINE_DESC = {"online", "在线"}


@dataclass(slots=True)
class CaptchaTicket:
    """阿里云盾滑块通过后的票据五元组。"""

    captcha_id: str
    lot_number: str
    captcha_output: str
    pass_token: str
    gen_time: str

    def to_request(self) -> dict[str, str]:
        return {
            "captchaId": self.captcha_id,
            "lotNumber": self.lot_number,
            "captchaOutput": self.captcha_output,
            "passToken": self.pass_token,
            "genTime": self.gen_time,
        }

    @classmethod
    def from_json(cls, value: Any) -> CaptchaTicket:
        """解析滑块页输出的票据，兼容下划线/驼峰键名与 result 包装。"""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError as err:
                raise VattiCaptchaError("票据不是合法 JSON") from err
        if not isinstance(value, dict):
            raise VattiCaptchaError("票据格式无法识别")

        def has_ticket(data: dict[str, Any]) -> bool:
            return bool(data.get("captcha_id") or data.get("captchaId"))

        if not has_ticket(value):
            for wrapper in ("result", "data"):
                nested = value.get(wrapper)
                if isinstance(nested, dict) and has_ticket(nested):
                    value = nested
                    break

        def pick(*keys: str) -> str:
            for key in keys:
                item = value.get(key)
                if item:
                    return str(item)
            return ""

        ticket = cls(
            captcha_id=pick("captcha_id", "captchaId"),
            lot_number=pick("lot_number", "lotNumber"),
            captcha_output=pick("captcha_output", "captchaOutput"),
            pass_token=pick("pass_token", "passToken"),
            gen_time=pick("gen_time", "genTime"),
        )
        missing = [
            name
            for name in (
                "captcha_id",
                "lot_number",
                "captcha_output",
                "pass_token",
                "gen_time",
            )
            if not getattr(ticket, name)
        ]
        if missing:
            raise VattiCaptchaError("票据缺少字段: " + ", ".join(missing))
        return ticket


@dataclass(slots=True)
class VattiDevice:
    """设备列表条目。"""

    device_id: str
    name: str
    product_id: str
    product_key: str
    device_name: str
    model: str
    category: str
    family_id: str
    online: bool
    serial_number: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> VattiDevice:
        device_id = str(data.get("id") or data.get("deviceId") or "")
        if not device_id:
            raise ValueError("设备数据缺少 id")
        name = (
            data.get("nickname")
            or data.get("deviceName")
            or data.get("model")
            or device_id
        )
        return cls(
            device_id=device_id,
            name=str(name),
            product_id=str(data.get("productId") or ""),
            product_key=str(data.get("productKey") or ""),
            device_name=str(data.get("deviceName") or ""),
            model=str(data.get("model") or ""),
            category=str(data.get("categoryName") or ""),
            family_id=str(data.get("familyId") or ""),
            online=_parse_online(data),
            serial_number=str(data.get("snCode") or ""),
            raw=data,
        )


def _parse_online(data: dict[str, Any]) -> bool:
    status = data.get("status")
    if status in (1, "1", True):
        return True
    return str(data.get("statusDesc") or "").strip().lower() in _ONLINE_DESC


@dataclass(slots=True)
class DeviceState:
    """一台设备的物模型属性快照（值统一为字符串）。"""

    device_id: str
    props: dict[str, str] = field(default_factory=dict)
    props_ts: dict[str, int] = field(default_factory=dict)
    fetched_at: float = 0.0

    def get(self, identifier: str) -> str | None:
        return self.props.get(identifier)

    def get_int(self, identifier: str) -> int | None:
        raw = self.get(identifier)
        if raw is None or raw == "":
            return None
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    def get_float(self, identifier: str) -> float | None:
        raw = self.get(identifier)
        if raw is None or raw == "":
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def bit(self, identifier: str, bit: int) -> bool | None:
        value = self.get_int(identifier)
        if value is None:
            return None
        return bool((value >> bit) & 1)

    def reported_at(self, identifier: str) -> datetime | None:
        ts = self.props_ts.get(identifier, 0)
        if ts <= 0:
            return None
        return datetime.fromtimestamp(ts / 1000).astimezone()
