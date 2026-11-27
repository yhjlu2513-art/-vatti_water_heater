"""在线状态与故障告警。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .const import DOMAIN
from .coordinator import VattiCoordinator
from .entity import VattiEntity
from .models import VattiDevice
from .specs import ProductSpec, is_problem_state

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
    entities: list[BinarySensorEntity] = []
    for device_id, device in coordinator.runtime.devices.items():
        spec = coordinator.runtime.specs.get(device_id)
        if spec is None:
            continue
        entities.append(VattiOnlineSensor(coordinator, device, spec))
        entities.append(VattiProblemSensor(coordinator, device, spec))
    async_add_entities(entities)


class VattiOnlineSensor(VattiEntity, BinarySensorEntity):
    """设备在线状态（来自设备列表，随清单刷新）。"""

    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: VattiCoordinator, device: VattiDevice, spec: ProductSpec
    ) -> None:
        super().__init__(coordinator, device, spec)
        self._attr_unique_id = self.scoped_unique_id("binary_online")

    @property
    def is_on(self) -> bool:
        return self.device.online


class VattiProblemSensor(VattiEntity, BinarySensorEntity):
    """故障告警：物模型故障字段非 0 时点亮。"""

    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, coordinator: VattiCoordinator, device: VattiDevice, spec: ProductSpec
    ) -> None:
        super().__init__(coordinator, device, spec)
        self._attr_unique_id = self.scoped_unique_id("binary_problem")

    @property
    def is_on(self) -> bool | None:
        state = self.state_obj
        return None if state is None else is_problem_state(state.props)
