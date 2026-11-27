"""服务注册。"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN
from .probe import async_setup_probe_services, async_unload_probe_services

_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH = "refresh"


async def async_setup_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    async def handle_refresh(call: ServiceCall) -> None:
        for coordinator in list(hass.data.get(DOMAIN, {}).values()):
            await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, handle_refresh)
    await async_setup_probe_services(hass)


async def async_unload_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
    await async_unload_probe_services(hass)
