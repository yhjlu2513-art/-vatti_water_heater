"""配置、重新认证与选项流程。

添加集成：手机号 → 滑块 → 短信验证码 → 选择家庭
重新认证：确认 → 滑块 → 短信验证码（保留原家庭与选项）
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .api import VattiClient
from .captcha import captcha_page_url, ticket_or_error
from .const import (
    CONF_DEVICE_KIND,
    CONF_ENABLE_ENERGY,
    CONF_FAMILY_ID,
    CONF_FAMILY_NAME,
    CONF_PHONE,
    CONF_POLL_INTERVAL,
    CONF_TOKEN,
    DEFAULT_ENABLE_ENERGY,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    INTEGRATION_NAME,
    KIND_AUTO,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from .specs import KIND_ELECTRIC, KIND_GAS, KIND_ZERO_COLD
from .exceptions import (
    VattiApiError,
    VattiAuthError,
    VattiCaptchaError,
    VattiConnectionError,
    VattiLoginError,
    VattiSmsError,
)

_LOGGER = logging.getLogger(__name__)
_PHONE_RE = re.compile(r"^1\d{10}$")

# 机型识别：auto 会按 productId / 品类名推断，其余强制套用对应能力表
KIND_CHOICES = [
    {"value": KIND_AUTO, "label": "自动识别"},
    {"value": KIND_GAS, "label": "燃气热水器（普通恒温）"},
    {"value": KIND_ZERO_COLD, "label": "零冷水燃气热水器"},
    {"value": KIND_ELECTRIC, "label": "电热水器"},
]
_VALID_KINDS = {item["value"] for item in KIND_CHOICES}


def _normalize_phone(raw: str) -> str:
    phone = re.sub(r"[\s\-+]", "", raw or "")
    if len(phone) == 13 and phone.startswith("86"):
        phone = phone[2:]
    return phone


def _mask_phone(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else phone


def _family_key(family: dict[str, Any]) -> str:
    return str(family.get("familyId") or family.get("id") or "")


def _family_options(families: list[dict[str, Any]]) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for family in families:
        key = _family_key(family)
        if not key or key in seen:
            continue
        seen.add(key)
        options.append({"value": key, "label": str(family.get("name") or key)})
    return options


def _link(url: str) -> str:
    """描述里的主链接必须是带 target=_blank 的锚点，否则会被前端路由拦截。"""
    safe = html.escape(url, quote=True)
    return f'<a href="{safe}" target="_blank">{safe}</a>'


class VattiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """华帝热水器配置流程。"""

    VERSION = 1

    def __init__(self) -> None:
        self._phone: str | None = None
        self._token: str | None = None
        self._families: list[dict[str, Any]] = []
        self._reauth_entry: config_entries.ConfigEntry | None = None

    # ------------------------------------------------------------------
    # 添加
    # ------------------------------------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            phone = _normalize_phone(str(user_input.get(CONF_PHONE, "")))
            if not _PHONE_RE.match(phone):
                errors[CONF_PHONE] = "invalid_phone"
            else:
                # 用户中途切到浏览器做滑块、回来时对话框可能已经丢了，旧流程会一直
                # 占着这个手机号的 unique_id，再次添加就报 already_in_progress。
                # 这里先清掉同一手机号下没走完的旧流程，保证随时能重来。
                self._async_abort_stale_user_flows(phone)
                await self.async_set_unique_id(phone, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                if any(
                    entry.data.get(CONF_PHONE) == phone
                    for entry in self.hass.config_entries.async_entries(DOMAIN)
                ):
                    return self.async_abort(reason="already_configured")
                self._phone = phone
                return await self.async_step_captcha()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_PHONE): TextSelector(
                TextSelectorConfig(type="tel")
            )}),
            errors=errors,
        )

    def _async_abort_stale_user_flows(self, phone: str) -> None:
        """中止同一手机号下未完成的添加流程，避免卡住后无法重新添加。"""
        for progress in self._async_in_progress(
            include_uninitialized=True, match_context={"unique_id": phone}
        ):
            if progress["flow_id"] == self.flow_id:
                continue
            if progress.get("context", {}).get("source") != config_entries.SOURCE_USER:
                continue
            _LOGGER.info("清理未完成的添加流程：%s", progress["flow_id"])
            self.hass.config_entries.flow.async_abort(progress["flow_id"])

    async def async_step_captcha(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        url = captcha_page_url(self.hass)
        if url is None:
            return self.async_abort(reason="http_unavailable")
        # 带上 flow_id：滑块页完成验证后会直接推进这个流程，用户不必回来点提交
        url = f"{url}?flow_id={self.flow_id}"

        placeholders = {
            "phone": _mask_phone(self._phone or ""),
            "captcha_link": _link(url),
            "captcha_url": url,
        }
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                ticket = ticket_or_error(str(user_input.get("ticket") or ""))
                await VattiClient(
                    async_get_clientsession(self.hass)
                ).send_sms_code(self._phone or "", ticket)
            except VattiCaptchaError as err:
                errors["base"] = "invalid_ticket"
                placeholders["detail"] = str(err)
            except VattiSmsError as err:
                errors["base"] = "sms_failed"
                placeholders["detail"] = str(err)
            except VattiConnectionError:
                errors["base"] = "cannot_connect"
            except VattiAuthError:
                errors["base"] = "cannot_connect"
            except VattiApiError as err:
                errors["base"] = "sms_failed"
                placeholders["detail"] = str(err)
            else:
                return await self.async_step_sms()

        return self.async_show_form(
            step_id="captcha",
            data_schema=vol.Schema(
                {
                    vol.Optional("ticket", default=""): TextSelector(
                        TextSelectorConfig(multiline=True)
                    )
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_sms(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        placeholders = {"phone": _mask_phone(self._phone or "")}
        if user_input is not None:
            client = VattiClient(async_get_clientsession(self.hass))
            try:
                token = await client.login_with_sms(
                    self._phone or "", str(user_input.get("code", ""))
                )
                await client.user_info()
            except VattiLoginError as err:
                errors["base"] = "invalid_code"
                placeholders["detail"] = str(err)
            except VattiAuthError:
                errors["base"] = "invalid_code"
            except VattiConnectionError:
                errors["base"] = "cannot_connect"
            except VattiApiError as err:
                errors["base"] = "login_failed"
                placeholders["detail"] = str(err)
            else:
                self._token = token
                if self._reauth_entry is not None:
                    return self._finish_reauth()
                return await self.async_step_family()

        return self.async_show_form(
            step_id="sms",
            data_schema=vol.Schema({vol.Required("code"): TextSelector(
                TextSelectorConfig(type="number")
            )}),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_family(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None and self._families:
            family_id = str(user_input[CONF_FAMILY_ID])
            family_name = next(
                (
                    str(family.get("name") or "")
                    for family in self._families
                    if _family_key(family) == family_id
                ),
                "",
            )
            return self._create_entry(family_id, family_name)

        try:
            client = VattiClient(async_get_clientsession(self.hass), self._token)
            self._families = await client.families()
        except (VattiConnectionError, VattiApiError):
            # 家庭列表拉取失败不阻塞添加，运行时自动取第一个家庭
            return self._create_entry(None, None)

        if len(self._families) <= 1:
            family_id = _family_key(self._families[0]) if self._families else None
            return self._create_entry(family_id, None)

        return self.async_show_form(
            step_id="family",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_FAMILY_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=_family_options(self._families),
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    def _create_entry(self, family_id: str | None, family_name: str | None) -> FlowResult:
        data: dict[str, Any] = {
            CONF_PHONE: self._phone,
            CONF_TOKEN: self._token,
        }
        if family_id:
            data[CONF_FAMILY_ID] = family_id
            data[CONF_FAMILY_NAME] = family_name or family_id
        return self.async_create_entry(
            title=f"{INTEGRATION_NAME} {_mask_phone(self._phone or '')}",
            data=data,
        )

    # ------------------------------------------------------------------
    # 重新认证
    # ------------------------------------------------------------------
    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        entry_id = self.context.get("entry_id")
        entry = (
            self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        )
        self._phone = _normalize_phone(str(entry_data.get(CONF_PHONE) or ""))
        if entry is None or not self._phone:
            return self.async_abort(reason="reauth_failed")
        self._reauth_entry = entry
        if entry.unique_id and entry.unique_id != self._phone:
            return self.async_abort(reason="reauth_failed")
        await self.async_set_unique_id(self._phone)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return await self.async_step_captcha()
        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"phone": _mask_phone(self._phone or "")},
        )

    def _finish_reauth(self) -> FlowResult:
        entry = self._reauth_entry
        if entry is None:
            return self.async_abort(reason="reauth_failed")
        self.hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_PHONE: self._phone, CONF_TOKEN: self._token},
        )
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(entry.entry_id)
        )
        return self.async_abort(reason="reauth_successful")

    # ------------------------------------------------------------------
    # 选项
    # ------------------------------------------------------------------
    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> VattiOptionsFlow:
        return VattiOptionsFlow()


class VattiOptionsFlow(config_entries.OptionsFlow):
    """轮询间隔、能耗统计开关与家庭切换。"""

    def _entry(self) -> config_entries.ConfigEntry:
        """取当前条目。

        HA 2024.3 不会给 OptionsFlow 注入 config_entry，新版才有
        ``self.config_entry``；``self.handler`` 始终等于条目 ID，跨版本可用。
        """
        entry = self.hass.config_entries.async_get_entry(self.handler)
        if entry is None:  # pragma: no cover - 条目被删除时流程会被中止
            raise RuntimeError("配置条目不存在")
        return entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self._entry()
        families: list[dict[str, str]] = []
        errors: dict[str, str] = {}
        try:
            client = VattiClient(
                async_get_clientsession(self.hass),
                str(entry.data.get(CONF_TOKEN) or ""),
            )
            families = _family_options(await client.families())
        except (VattiConnectionError, VattiApiError):
            errors["base"] = "cannot_connect"

        if user_input is not None:
            try:
                interval = int(user_input.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
            except (TypeError, ValueError):
                interval = DEFAULT_POLL_INTERVAL
            kind = str(user_input.get(CONF_DEVICE_KIND, KIND_AUTO))
            if kind not in _VALID_KINDS:
                kind = KIND_AUTO
            options = {
                CONF_DEVICE_KIND: kind,
                CONF_POLL_INTERVAL: max(
                    MIN_POLL_INTERVAL, min(MAX_POLL_INTERVAL, interval)
                ),
                CONF_ENABLE_ENERGY: bool(
                    user_input.get(CONF_ENABLE_ENERGY, DEFAULT_ENABLE_ENERGY)
                ),
            }
            family_id = str(user_input.get(CONF_FAMILY_ID) or "")
            if family_id and family_id != str(entry.data.get(CONF_FAMILY_ID) or ""):
                name = next(
                    (item["label"] for item in families if item["value"] == family_id),
                    family_id,
                )
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_FAMILY_ID: family_id, CONF_FAMILY_NAME: name},
                )
            return self.async_create_entry(title="", data=options)

        schema: dict[Any, Any] = {
            vol.Required(
                CONF_POLL_INTERVAL,
                default=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL, step=5
                )
            ),
            vol.Required(
                CONF_ENABLE_ENERGY,
                default=entry.options.get(CONF_ENABLE_ENERGY, DEFAULT_ENABLE_ENERGY),
            ): BooleanSelector(),
            vol.Required(
                CONF_DEVICE_KIND,
                default=entry.options.get(CONF_DEVICE_KIND, KIND_AUTO),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=KIND_CHOICES, mode=SelectSelectorMode.DROPDOWN
                )
            ),
        }
        current_family = str(entry.data.get(CONF_FAMILY_ID) or "")
        if current_family and all(item["value"] != current_family for item in families):
            families.insert(
                0,
                {
                    "value": current_family,
                    "label": str(entry.data.get(CONF_FAMILY_NAME) or current_family),
                },
            )
        if len(families) > 1:
            schema[
                vol.Required(CONF_FAMILY_ID, default=current_family or families[0]["value"])
            ] = SelectSelector(
                SelectSelectorConfig(options=families, mode=SelectSelectorMode.LIST)
            )
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema), errors=errors
        )
