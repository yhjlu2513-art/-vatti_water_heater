"""华帝云异步客户端。

协议要点（与华帝智慧家 App 5.x 一致）：

- 业务接口统一 ``POST {API_BASE}{path}`` + JSON；
- 请求体固定带 ``accessKeyId`` / ``accessToken`` / ``timestamp``（毫秒字符串）；
- 签名放在请求头 ``sign``，算法见 signing.py；
- 登录后的业务接口额外带请求头 ``accesstoken``；
- 响应为 ``{"code": 200, "message": ..., "data": ...}``，``code == 200`` 为成功；
- 物模型属性值都是字符串。
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

import aiohttp

from .const import (
    ACCESS_KEY_ID,
    API_BASE,
    API_TIMEOUT,
    APP_VERSION,
    DEVICE_PAGE_SIZE,
    ECM_ACCESS_KEY_ID,
    ENERGY_TYPE_GAS,
    ENERGY_TYPE_WATER,
    EP_DEVICE_LIST,
    EP_DEVICE_RRPC,
    EP_ENERGY,
    EP_FAMILY_LIST,
    EP_LOGIN_CODE,
    EP_PROPERTY_STATUS,
    EP_QUERY_SMART_TEMP,
    EP_SAVE_SMART_TEMP,
    EP_SMS_CODE,
    EP_USER_INFO,
    LAST_LOGIN_TYPE,
    LOGIN_SOURCE,
    PHONE_MODEL,
    SMS_REGION,
    USER_AGENT,
)
from .energy import EnergyOverview, parse_overview
from .exceptions import (
    VattiApiError,
    VattiAuthError,
    VattiConnectionError,
    VattiDeviceOfflineError,
    VattiLoginError,
    VattiSmsError,
)
from .models import CaptchaTicket
from .signing import calc_sign, calc_sign_ecm

_AUTH_CODES = {401, 403}
_AUTH_KEYWORDS = ("token", "login", "auth", "credential", "expired")
_RRPC_TIMEOUT_MS = 5000


def _as_list(data: Any) -> list[dict[str, Any]]:
    """把响应 data 归一化为字典列表。"""
    if data is None:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("list", "records", "deviceList", "rows", "properties"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [data]
    return []


class VattiClient:
    """华帝云 API 客户端，token 由配置条目注入。"""

    def __init__(self, session: aiohttp.ClientSession, token: str | None = None) -> None:
        self._session = session
        self._token = token

    @property
    def token(self) -> str | None:
        return self._token

    def update_token(self, token: str | None) -> None:
        self._token = token

    def token_expired(self, leeway: int = 60) -> bool:
        """本地解析 JWT 的 exp 判断过期，不校验签名。"""
        if not self._token:
            return True
        try:
            payload_b64 = self._token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            exp = int(payload.get("exp") or 0)
        except (ValueError, IndexError, TypeError):
            # 不是标准 JWT 时交给服务端判断
            return False
        return exp > 0 and exp < time.time() + leeway

    async def close(self) -> None:
        """占位：session 由 HA 管理，不需要关闭。"""

    # ------------------------------------------------------------------
    # 请求封装
    # ------------------------------------------------------------------
    async def _post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        auth: bool = True,
        timeout: float = API_TIMEOUT,
    ) -> Any:
        payload: dict[str, Any] = {
            "accessKeyId": ACCESS_KEY_ID,
            "accessToken": self._token if auth else None,
            "timestamp": str(int(time.time() * 1000)),
        }
        if body:
            payload.update(body)
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "version": APP_VERSION,
            "User-Agent": USER_AGENT,
            "sign": calc_sign(payload),
        }
        if auth and self._token:
            headers["accesstoken"] = self._token
        data = await self._request_json(
            API_BASE + path, payload, headers, timeout=timeout
        )
        return self._unwrap(data, path)

    async def _request_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        *,
        timeout: float = API_TIMEOUT,
    ) -> Any:
        try:
            async with self._session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status in _AUTH_CODES:
                    raise VattiAuthError(f"HTTP {response.status}：登录已失效")
                if response.status >= 400:
                    text = await response.text()
                    raise VattiApiError(
                        f"HTTP {response.status}: {text[:200]}", code=response.status
                    )
                try:
                    return await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as err:
                    raise VattiApiError("云端返回的不是合法 JSON") from err
        except asyncio.TimeoutError as err:
            raise VattiConnectionError("请求超时") from err
        except aiohttp.ClientError as err:
            raise VattiConnectionError(f"网络错误：{err}") from err

    @staticmethod
    def _unwrap(data: Any, path: str) -> Any:
        if not isinstance(data, dict):
            return data
        code = data.get("code")
        message = str(data.get("message") or data.get("msg") or "")
        try:
            code_num = int(code)
        except (TypeError, ValueError):
            code_num = None
        if code_num == 200 or data.get("status") is True:
            return data.get("data")
        lowered = message.lower()
        if code_num in _AUTH_CODES or any(word in lowered for word in _AUTH_KEYWORDS):
            raise VattiAuthError(f"登录已失效（{code} {message}）", code=code)
        raise VattiApiError(f"{path} 调用失败：{code} {message}", code=code)

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------
    async def send_sms_code(self, phone: str, ticket: CaptchaTicket) -> None:
        """带滑块票据请求短信验证码；票据一次性，失败需重新滑块。"""
        body = {
            "phone": phone,
            "smsCode": SMS_REGION,
            "smsType": None,
            **ticket.to_request(),
        }
        try:
            await self._post(EP_SMS_CODE, body, auth=False)
        except VattiApiError as err:
            if isinstance(err, VattiAuthError):
                raise
            raise VattiSmsError(str(err), code=err.code) from err

    async def login_with_sms(self, phone: str, code: str) -> str:
        """短信验证码登录，成功后保存并返回 token。"""
        body = {
            "phone": phone,
            "smsCode": SMS_REGION,
            "verificationCode": code,
            "source": LOGIN_SOURCE,
            "lastLoginType": LAST_LOGIN_TYPE,
            "phoneModel": PHONE_MODEL,
        }
        try:
            data = await self._post(EP_LOGIN_CODE, body, auth=False)
        except VattiApiError as err:
            raise VattiLoginError(str(err), code=err.code) from err
        token = data.get("accessToken") if isinstance(data, dict) else None
        if not token:
            raise VattiLoginError("登录响应缺少 accessToken")
        self._token = str(token)
        return self._token

    async def user_info(self) -> Any:
        return await self._post(EP_USER_INFO)

    # ------------------------------------------------------------------
    # 账号、家庭与设备
    # ------------------------------------------------------------------
    async def families(self) -> list[dict[str, Any]]:
        return _as_list(await self._post(EP_FAMILY_LIST))

    async def devices(self, family_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for page in range(1, 11):
            body = {
                "familyId": family_id,
                "currentPage": page,
                "pageSize": DEVICE_PAGE_SIZE,
            }
            batch = _as_list(await self._post(EP_DEVICE_LIST, body))
            result.extend(batch)
            if len(batch) < DEVICE_PAGE_SIZE:
                break
        return result

    async def properties(self, device_id: str) -> dict[str, dict[str, Any]]:
        """拉取物模型属性快照。

        返回 ``{identifier: {"value": str, "time": int}}``；设备按事件上报，
        云端快照里不少字段是陈旧缓存，time 用于判断新鲜度。
        """
        data = await self._post(EP_PROPERTY_STATUS, {"deviceId": device_id})
        result: dict[str, dict[str, Any]] = {}
        for item in _as_list(data):
            identifier = item.get("identifier")
            if identifier is None or item.get("value") is None:
                continue
            try:
                reported = int(item.get("time") or 0)
            except (TypeError, ValueError):
                reported = 0
            result[str(identifier)] = {
                "value": str(item["value"]),
                "time": reported,
            }
        return result

    async def send_command(self, device_id: str, message: dict[str, Any]) -> None:
        """通过 RRPC 下发属性控制指令。"""
        content = {key: str(value) for key, value in message.items()}
        content.setdefault("controller", "1")
        body = {
            "deviceId": device_id,
            "messageContent": json.dumps(content, separators=(",", ":"), ensure_ascii=False),
            "timeout": _RRPC_TIMEOUT_MS,
            "isForce": None,
            "cancelAutoAdjTemp": None,
        }
        data = await self._post(EP_DEVICE_RRPC, body)
        code = data.get("rrpcCode") if isinstance(data, dict) else None
        if code and str(code).upper() != "SUCCESS":
            if "OFFLINE" in str(code).upper():
                raise VattiDeviceOfflineError("设备离线，指令未送达", code=code)
            raise VattiApiError(f"指令下发失败：{code}", code=code)

    # ------------------------------------------------------------------
    # 智慧云感温（云端开关，非位域）
    # ------------------------------------------------------------------
    async def query_smart_temp(
        self, device_name: str, product_key: str
    ) -> dict[str, Any]:
        data = await self._post(
            EP_QUERY_SMART_TEMP,
            {"deviceName": str(device_name), "productKey": str(product_key)},
        )
        return data if isinstance(data, dict) else {}

    async def save_smart_temp(
        self,
        device_name: str,
        product_key: str,
        enabled: bool,
        temp_adj_data: list[dict[str, Any]] | None = None,
    ) -> None:
        """开关智慧云感温；App 会回传完整温度映射表，缺失时先查询回填。"""
        if temp_adj_data is None:
            current = await self.query_smart_temp(device_name, product_key)
            temp_adj_data = current.get("tempAdjData")
        body: dict[str, Any] = {
            "deviceName": str(device_name),
            "productKey": str(product_key),
            "isEnabled": 1 if enabled else 0,
        }
        if temp_adj_data:
            body["tempAdjData"] = temp_adj_data
        await self._post(EP_SAVE_SMART_TEMP, body)

    # ------------------------------------------------------------------
    # 能耗统计
    # ------------------------------------------------------------------
    async def energy_overview(self, device_id: str, is_gas: bool) -> EnergyOverview:
        energy_type = ENERGY_TYPE_GAS if is_gas else ENERGY_TYPE_WATER
        payload: dict[str, Any] = {
            "deviceId": str(device_id),
            "energyType": energy_type,
            "timeUnit": "2",
            "timestamp": int(time.time() * 1000),
            "accessKeyId": ECM_ACCESS_KEY_ID,
            "accessToken": self._token or "",
        }
        payload["sign"] = calc_sign_ecm(payload)
        headers = {
            "authorization": f"Bearer {self._token}" if self._token else "",
            "Content-Type": "application/json",
        }
        data = await self._request_json(API_BASE + EP_ENERGY, payload, headers)
        content = self._unwrap(data, EP_ENERGY)
        if not isinstance(content, dict):
            raise VattiApiError("能耗接口缺少 data")
        return parse_overview(content, is_gas)
