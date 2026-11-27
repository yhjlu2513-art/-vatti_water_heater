"""滑块验证：本地托管验证页 + 票据回收。

华帝发短信验证码前要求通过阿里云盾滑块。集成把验证页挂到 HA 自己的
HTTP 端口（``/api/vatti_water_heater_captcha/``），用户在浏览器完成滑块后，
页面把票据 POST 回来，配置流程直接取用；页面同时展示票据文本，自动回传
失败时可手动粘贴。

票据一次性：发送短信失败后需要重新滑块。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import CAPTCHA_PATH, CAPTCHA_TICKET_TTL, DEFAULT_CAPTCHA_ID
from .exceptions import VattiCaptchaError
from .models import CaptchaTicket

_LOGGER = logging.getLogger(__name__)

_ASSETS = Path(__file__).parent / "captcha_assets"
_NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate"}


class TicketStore:
    """页面回传的票据暂存区。"""

    def __init__(self) -> None:
        self._ticket: CaptchaTicket | None = None
        self._received_at = 0.0

    def put(self, ticket: CaptchaTicket) -> None:
        self._ticket = ticket
        self._received_at = time.time()
        _LOGGER.debug("收到滑块票据（lot_number=%s）", ticket.lot_number)

    def take(self) -> CaptchaTicket | None:
        ticket = self.peek()
        self._ticket = None
        return ticket

    def peek(self) -> CaptchaTicket | None:
        if self._ticket is None:
            return None
        if time.time() - self._received_at > CAPTCHA_TICKET_TTL:
            self._ticket = None
            return None
        return self._ticket


STORE = TicketStore()
_VIEWS_REGISTERED = False


def parse_ticket_text(text: str) -> CaptchaTicket:
    """解析用户粘贴的票据，容忍空白与代码围栏。"""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip().strip("`\"'").strip()
    if not cleaned:
        raise VattiCaptchaError("票据为空")
    return CaptchaTicket.from_json(cleaned)


async def _read_asset(hass: HomeAssistant, name: str) -> str:
    return await hass.async_add_executor_job(
        lambda: (_ASSETS / name).read_text(encoding="utf-8")
    )


def register_views(hass: HomeAssistant) -> bool:
    """把验证页注册到 HA 的 HTTP 组件；已注册或 http 不可用时返回状态。"""
    global _VIEWS_REGISTERED
    if _VIEWS_REGISTERED:
        return True
    if getattr(hass, "http", None) is None:
        return False

    class CaptchaPageView(HomeAssistantView):
        url = CAPTCHA_PATH
        extra_urls = [CAPTCHA_PATH + "/"]
        name = "api:vatti_water_heater:captcha"
        requires_auth = False

        async def get(self, request: web.Request) -> web.Response:
            page = await _read_asset(request.app["hass"], "index.html")
            return web.Response(
                text=page.replace("__CAPTCHA_ID__", DEFAULT_CAPTCHA_ID),
                content_type="text/html",
                charset="utf-8",
                headers=_NO_CACHE,
            )

    class CaptchaScriptView(HomeAssistantView):
        url = CAPTCHA_PATH + "/ct4.js"
        name = "api:vatti_water_heater:captcha_js"
        requires_auth = False

        async def get(self, request: web.Request) -> web.Response:
            script = await _read_asset(request.app["hass"], "ct4.js")
            return web.Response(
                text=script,
                content_type="application/javascript",
                charset="utf-8",
                headers=_NO_CACHE,
            )

    class CaptchaTicketView(HomeAssistantView):
        url = CAPTCHA_PATH + "/ticket"
        name = "api:vatti_water_heater:captcha_ticket"
        requires_auth = False

        async def post(self, request: web.Request) -> web.Response:
            try:
                payload: Any = await request.json()
                ticket = CaptchaTicket.from_json(payload)
            except (ValueError, VattiCaptchaError) as err:
                return web.json_response(
                    {"ok": False, "error": str(err)},
                    status=400,
                    headers=_NO_CACHE,
                )
            STORE.put(ticket)
            flow_id = payload.get("flow_id") if isinstance(payload, dict) else None
            if flow_id:
                request.app["hass"].async_create_task(
                    _advance_flow(request.app["hass"], str(flow_id))
                )
            return web.json_response({"ok": True}, headers=_NO_CACHE)

    hass.http.register_view(CaptchaPageView())
    hass.http.register_view(CaptchaScriptView())
    hass.http.register_view(CaptchaTicketView())
    _VIEWS_REGISTERED = True
    return True


async def _advance_flow(hass: HomeAssistant, flow_id: str) -> None:
    """滑块完成后直接推进配置流程，省掉「回到 HA 点提交」这一步。"""
    progress = {
        item["flow_id"]: item
        for item in hass.config_entries.flow.async_progress()
    }
    flow = progress.get(flow_id)
    if flow is None or flow.get("step_id") != "captcha":
        return
    try:
        await hass.config_entries.flow.async_configure(
            flow_id, user_input={"ticket": ""}
        )
    except Exception:  # noqa: BLE001 - 用户可能已关闭页面，静默失败即可
        _LOGGER.debug("滑块票据自动推进流程失败：%s", flow_id, exc_info=True)


def captcha_page_url(hass: HomeAssistant) -> str | None:
    """验证页的完整访问地址。"""
    if not register_views(hass):
        return None
    base: str | None = None
    try:
        from homeassistant.helpers.network import get_url

        base = get_url(hass, allow_cloud=False, prefer_external=False)
    except Exception:  # noqa: BLE001 - 未配置外部地址时用 mDNS 兜底
        port = getattr(getattr(hass, "http", None), "server_port", None) or 8123
        base = f"http://homeassistant.local:{port}"
    return f"{str(base).rstrip('/')}{CAPTCHA_PATH}/"


def ticket_or_error(text: str) -> CaptchaTicket:
    """优先用粘贴的票据，留空时取页面自动回传的票据。"""
    if text and text.strip():
        return parse_ticket_text(text)
    ticket = STORE.take()
    if ticket is None:
        raise VattiCaptchaError("还没收到滑块票据，请先完成滑块，或把票据粘贴到下方")
    return ticket
