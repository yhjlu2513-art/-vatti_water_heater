"""功能位开关（瀑布浴、节能洗、一键预热等）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN
from .coordinator import VattiCoordinator
from .entity import VattiEntity
from .models import VattiDevice
from .specs import ProductSpec, SwitchSpec

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
    entities: list[VattiBitSwitch] = []
    for device_id, device in coordinator.runtime.devices.items():
        spec = coordinator.runtime.specs.get(device_id)
        if spec is None:
            continue
        entities.extend(
            VattiBitSwitch(coordinator, device, spec, switch)
            for switch in spec.switches
        )
    async_add_entities(entities)


class VattiBitSwitch(VattiEntity, SwitchEntity):
    """按位读改写功能位域，保留同一字段的其它位。"""

    def __init__(
        self,
        coordinator: VattiCoordinator,
        device: VattiDevice,
        product: ProductSpec,
        spec: SwitchSpec,
    ) -> None:
        super().__init__(coordinator, device, product)
        self.product = product
        self.switch = spec
        self._attr_unique_id = self.scoped_unique_id(f"switch_{spec.key}")
        self._attr_translation_key = spec.key
        self._attr_icon = spec.icon

    @property
    def is_on(self) -> bool | None:
        state = self.state_obj
        if state is None:
            return None
        return state.bit(self.switch.field, self.switch.bit)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.async_send(self._build_message(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_send(self._build_message(False))

    def _build_message(self, enabled: bool) -> dict[str, str]:
        state = self.state_obj
        field = self.switch.field
        current = (state.get_int(field) if state is not None else 0) or 0
        mask = 1 << self.switch.bit
        value = (current | mask) if enabled else (current & ~mask)
        message: dict[str, str] = {field: str(value)}
        if enabled:
            # 互斥组：开本开关时显式清掉对方位，与 App 行为一致
            for other_field, other_bit in self.switch.clears:
                other_current = (
                    state.get_int(other_field) if state is not None else 0
                ) or 0
                message[other_field] = str(other_current & ~(1 << other_bit))
        return message
