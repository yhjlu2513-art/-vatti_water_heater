"""手动刷新按钮。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .const import DOMAIN
from .coordinator import VattiCoordinator
from .entity import VattiEntity
from .models import VattiDevice
from .specs import ProductSpec

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VattiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        VattiRefreshButton(coordinator, device, spec)
        for device_id, device in coordinator.runtime.devices.items()
        if (spec := coordinator.runtime.specs.get(device_id)) is not None
    )


class VattiRefreshButton(VattiEntity, ButtonEntity):
    """立即拉取一次设备状态。"""

    _attr_translation_key = "refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:refresh"

    def __init__(
        self, coordinator: VattiCoordinator, device: VattiDevice, spec: ProductSpec
    ) -> None:
        super().__init__(coordinator, device, spec)
        self._attr_unique_id = self.scoped_unique_id("button_refresh")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
