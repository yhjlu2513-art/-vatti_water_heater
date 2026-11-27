"""华帝热水器集成入口。"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VattiClient
from .const import CONF_TOKEN, DOMAIN, PLATFORMS
from .coordinator import VattiCoordinator, VattiRuntime
from .exceptions import VattiError
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """建立云端客户端、首次拉取数据并转发到各平台。"""
    token = str(entry.data.get(CONF_TOKEN) or "")
    client = VattiClient(async_get_clientsession(hass), token=token)
    if client.token_expired():
        raise ConfigEntryAuthFailed("登录已过期，请重新认证")

    runtime = VattiRuntime(client=client)
    coordinator = VattiCoordinator(hass, entry, client, runtime)
    try:
        await coordinator.async_config_entry_first_refresh()
    except VattiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(coordinator.async_shutdown)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await async_setup_services(hass)

    _LOGGER.info(
        "华帝热水器已加载：%d 台设备（%s）",
        len(coordinator.runtime.specs),
        entry.title,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unloaded:
        return False
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if not hass.data.get(DOMAIN):
        await async_unload_services(hass)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """选项变更后重载，让轮询间隔/能耗开关立即生效。"""
    await hass.config_entries.async_reload(entry.entry_id)
