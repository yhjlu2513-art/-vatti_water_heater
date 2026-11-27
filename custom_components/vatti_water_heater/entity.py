"""实体共享基类。"""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import VattiCoordinator
from .exceptions import VattiDeviceOfflineError, VattiError
from .models import DeviceState, VattiDevice
from .specs import ProductSpec


class VattiEntity(CoordinatorEntity[VattiCoordinator]):
    """华帝热水器实体基类。"""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: VattiCoordinator,
        device: VattiDevice,
        spec: ProductSpec,
    ) -> None:
        super().__init__(coordinator)
        self.device = device
        self.spec = spec
        state = coordinator.runtime.states.get(device.device_id)
        serial = ""
        if state is not None:
            serial = state.get("snCode") or state.get("sncode") or ""
        serial = serial or device.serial_number
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=device.model or spec.label,
            **({"serial_number": serial} if serial else {}),
        )

    def scoped_unique_id(self, suffix: str) -> str:
        """条目级唯一 ID，多账号/多家庭互不冲突。"""
        return f"{self.coordinator.entry.entry_id}_{self.device.device_id}_{suffix}"

    @property
    def state_obj(self) -> DeviceState | None:
        return self.coordinator.runtime.states.get(self.device.device_id)

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.device.device_id in self.coordinator.runtime.devices
            and self.device.device_id in self.coordinator.runtime.specs
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.state_obj
        attrs: dict[str, Any] = {
            "product_id": self.device.product_id,
            "device_kind": self.spec.kind,
        }
        if state is not None:
            reported = state.reported_at("owater_temp") or state.reported_at(
                "powerStat"
            )
            if reported is not None:
                attrs["last_reported"] = reported.isoformat()
        return attrs

    async def async_send(self, message: dict[str, Any]) -> None:
        """下发控制；失败时抛 HomeAssistantError 让界面给出反馈。"""
        try:
            await self.coordinator.async_send_command(self.device.device_id, message)
        except VattiDeviceOfflineError as err:
            raise HomeAssistantError(f"{self.device.name} 当前离线，指令未送达") from err
        except VattiError as err:
            raise HomeAssistantError(f"控制失败：{err}") from err
