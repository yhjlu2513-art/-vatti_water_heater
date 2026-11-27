"""状态与能耗传感器。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfVolume

from .const import CONF_ENABLE_ENERGY, DEFAULT_ENABLE_ENERGY, DOMAIN
from .coordinator import VattiCoordinator
from .entity import VattiEntity
from .models import DeviceState, VattiDevice
from .specs import KIND_ELECTRIC, ProductSpec, fault_text

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

ValueFn = Callable[[DeviceState, VattiCoordinator, str], Any]


@dataclass(frozen=True, kw_only=True)
class VattiSensorDescription(SensorEntityDescription):
    """带取值函数的传感器描述。"""

    value_fn: ValueFn
    gas_only: bool = False
    energy: bool = False


def _energy_value(kind: str, field: str) -> ValueFn:
    def getter(state: DeviceState, coordinator: VattiCoordinator, device_id: str) -> Any:
        bucket = coordinator.runtime.energy.get(device_id) or {}
        summary = bucket.get(kind)
        return None if summary is None else getattr(summary, field, None)

    return getter


def _prop(identifier: str) -> ValueFn:
    def getter(state: DeviceState, coordinator: VattiCoordinator, device_id: str) -> Any:
        return state.get_float(identifier)

    return getter


def _last_reported(
    state: DeviceState, coordinator: VattiCoordinator, device_id: str
) -> Any:
    for identifier in ("owater_temp", "powerStat", "iwater_temp"):
        reported = state.reported_at(identifier)
        if reported is not None:
            return reported
    return None


SENSORS: tuple[VattiSensorDescription, ...] = (
    VattiSensorDescription(
        key="outlet_temp",
        translation_key="outlet_temp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_prop("owater_temp"),
    ),
    VattiSensorDescription(
        key="inlet_temp",
        translation_key="inlet_temp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_prop("iwater_temp"),
    ),
    VattiSensorDescription(
        key="water_flow",
        translation_key="water_flow",
        native_unit_of_measurement="L/min",
        icon="mdi:water-pump",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_prop("water_flow"),
    ),
    VattiSensorDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        native_unit_of_measurement="%",
        icon="mdi:wifi",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_prop("rssi"),
    ),
    VattiSensorDescription(
        key="fault_code",
        translation_key="fault_code",
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state, coordinator, device_id: fault_text(state.props),
    ),
    VattiSensorDescription(
        key="last_reported",
        translation_key="last_reported",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_last_reported,
    ),
    VattiSensorDescription(
        key="gas_today",
        translation_key="gas_today",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        icon="mdi:fire",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        gas_only=True,
        energy=True,
        value_fn=_energy_value("gas", "today"),
    ),
    VattiSensorDescription(
        key="gas_week",
        translation_key="gas_week",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        icon="mdi:fire",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        gas_only=True,
        energy=True,
        value_fn=_energy_value("gas", "week"),
    ),
    VattiSensorDescription(
        key="gas_year",
        translation_key="gas_year",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        icon="mdi:fire",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        gas_only=True,
        energy=True,
        value_fn=_energy_value("gas", "year"),
    ),
    VattiSensorDescription(
        key="water_today",
        translation_key="water_today",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        icon="mdi:water",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        energy=True,
        value_fn=_energy_value("water", "today"),
    ),
    VattiSensorDescription(
        key="water_week",
        translation_key="water_week",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        icon="mdi:water",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        energy=True,
        value_fn=_energy_value("water", "week"),
    ),
    VattiSensorDescription(
        key="water_year",
        translation_key="water_year",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        icon="mdi:water",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        energy=True,
        value_fn=_energy_value("water", "year"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VattiCoordinator = hass.data[DOMAIN][entry.entry_id]
    energy_enabled = entry.options.get(CONF_ENABLE_ENERGY, DEFAULT_ENABLE_ENERGY)
    entities: list[VattiSensor] = []
    for device_id, device in coordinator.runtime.devices.items():
        spec = coordinator.runtime.specs.get(device_id)
        if spec is None:
            continue
        for description in SENSORS:
            if description.energy and not energy_enabled:
                continue
            if description.gas_only and spec.kind == KIND_ELECTRIC:
                continue
            entities.append(VattiSensor(coordinator, device, spec, description))
    async_add_entities(entities)


class VattiSensor(VattiEntity, SensorEntity):
    """通用只读传感器。"""

    entity_description: VattiSensorDescription

    def __init__(
        self,
        coordinator: VattiCoordinator,
        device: VattiDevice,
        spec: ProductSpec,
        description: VattiSensorDescription,
    ) -> None:
        super().__init__(coordinator, device, spec)
        self.entity_description = description
        self._attr_unique_id = self.scoped_unique_id(f"sensor_{description.key}")
        self._attr_translation_key = description.translation_key

    @property
    def native_value(self) -> Any:
        state = self.state_obj
        if state is None:
            return None
        return self.entity_description.value_fn(state, self.coordinator, self.device.device_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = dict(super().extra_state_attributes)
        if self.entity_description.key == "gas_week":
            gas = (self.coordinator.runtime.energy.get(self.device.device_id) or {}).get("gas")
            if gas is not None:
                attrs["daily_series"] = gas.week_series
        elif self.entity_description.key == "water_week":
            water = (self.coordinator.runtime.energy.get(self.device.device_id) or {}).get("water")
            if water is not None:
                attrs["daily_series"] = water.week_series
        return attrs
