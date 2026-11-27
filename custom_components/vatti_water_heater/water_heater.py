"""热水器实体。

状态字段（物模型，值均为字符串）：

- ``heater_temp`` 设定温度；``owater_temp`` / ``iwater_temp`` 出水/进水温度
- ``powerStat`` 电源 0/1
- ``func_switch`` / ``func_swit1`` / ``func_swit2`` 功能位域，按位解释

三种运行模式互斥（App 语义）：

- **标准**：清 AI 智洗位、关闭智慧云感温；
- **AI 智洗**：``func_swit1`` bit5 置位；
- **智慧云感温**：云端开关 ``saveGh00SmartAdjTemp``，不占位域。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.water_heater import (
    STATE_OFF,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, STATE_ON, UnitOfTemperature

from .const import DOMAIN
from .coordinator import VattiCoordinator
from .entity import VattiEntity
from .exceptions import VattiError
from .models import VattiDevice
from .specs import (
    MODE_AI_WASH,
    MODE_LABELS,
    MODE_SMART_TEMP,
    MODE_STANDARD,
    POWER_FIELD,
    ProductSpec,
    fault_text,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

_AI_WASH_FIELD = "func_swit1"
_AI_WASH_BIT = 5
_AI_WASH_MASK = 1 << _AI_WASH_BIT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VattiCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        VattiWaterHeater(coordinator, device, coordinator.runtime.specs[device_id])
        for device_id, device in coordinator.runtime.devices.items()
        if device_id in coordinator.runtime.specs
    ]
    async_add_entities(entities)


class VattiWaterHeater(VattiEntity, WaterHeaterEntity):
    """燃气/电热水器主实体。"""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _enable_turn_on_off_backwards_compat = False

    def __init__(
        self,
        coordinator: VattiCoordinator,
        device: VattiDevice,
        spec: ProductSpec,
    ) -> None:
        super().__init__(coordinator, device, spec)
        self._attr_unique_id = self.scoped_unique_id("water_heater")
        self._attr_min_temp = spec.temp_min
        self._attr_max_temp = spec.temp_max
        features = (
            WaterHeaterEntityFeature.TARGET_TEMPERATURE
            | WaterHeaterEntityFeature.ON_OFF
        )
        if spec.switches or spec.supports_smart_temp:
            features |= WaterHeaterEntityFeature.OPERATION_MODE
        self._attr_supported_features = features

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    @property
    def operation_list(self) -> list[str]:
        modes = [MODE_LABELS[MODE_STANDARD], MODE_LABELS[MODE_AI_WASH]]
        if self.spec.supports_smart_temp:
            modes.append(MODE_LABELS[MODE_SMART_TEMP])
        return modes

    @property
    def current_temperature(self) -> float | None:
        state = self.state_obj
        if state is None:
            return None
        for identifier in self.spec.current_temp_fields:
            value = state.get_float(identifier)
            if value is not None:
                return value
        return None

    @property
    def target_temperature(self) -> float | None:
        state = self.state_obj
        return None if state is None else state.get_float(self.spec.temp_field)

    @property
    def is_on(self) -> bool | None:
        state = self.state_obj
        if state is None:
            return None
        power = state.get_int(POWER_FIELD)
        return None if power is None else power == 1

    @property
    def current_operation(self) -> str | None:
        state = self.state_obj
        if state is None:
            return None
        if state.get_int(POWER_FIELD) == 0:
            return STATE_OFF
        if not self._attr_supported_features & WaterHeaterEntityFeature.OPERATION_MODE:
            return STATE_ON
        ai_bit = state.bit(_AI_WASH_FIELD, _AI_WASH_BIT)
        if ai_bit:
            return MODE_LABELS[MODE_AI_WASH]
        smart = self.coordinator.runtime.smart_temp.get(self.device.device_id) or {}
        if smart.get("isEnabled") == 1:
            return MODE_LABELS[MODE_SMART_TEMP]
        return MODE_LABELS[MODE_STANDARD]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = dict(super().extra_state_attributes)
        state = self.state_obj
        if state is not None:
            fault = fault_text(state.props)
            if fault:
                attrs["fault"] = fault
            energy = self.coordinator.runtime.energy.get(self.device.device_id) or {}
            gas = energy.get("gas")
            if gas is not None and gas.today is not None:
                attrs["gas_today_m3"] = gas.today
            water = energy.get("water")
            if water is not None and water.today is not None:
                attrs["water_today_m3"] = water.today
        return attrs

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------
    async def async_turn_on(self) -> None:
        await self.async_send({POWER_FIELD: "1"})

    async def async_turn_off(self) -> None:
        await self.async_send({POWER_FIELD: "0"})

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        clamped = int(
            round(max(self._attr_min_temp, min(self._attr_max_temp, temperature)))
        )
        await self.async_send({self.spec.temp_field: str(clamped)})

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        if operation_mode == MODE_LABELS[MODE_SMART_TEMP]:
            await self._select_smart_temp()
        elif operation_mode == MODE_LABELS[MODE_AI_WASH]:
            await self._select_ai_wash()
        elif operation_mode == MODE_LABELS[MODE_STANDARD]:
            await self._select_standard()
        else:
            _LOGGER.warning("忽略未知模式：%s", operation_mode)

    async def _select_smart_temp(self) -> None:
        """云感温：先清 AI 位，再打开云端开关。"""
        if self.state_obj is not None and self.state_obj.bit(
            _AI_WASH_FIELD, _AI_WASH_BIT
        ):
            await self._write_ai_bit(False)
        await self.coordinator.async_set_smart_temp(self.device.device_id, True)

    async def _select_ai_wash(self) -> None:
        """AI 智洗：先关云感温（互斥），再置位。"""
        smart = self.coordinator.runtime.smart_temp.get(self.device.device_id) or {}
        if smart.get("isEnabled") == 1:
            await self.coordinator.async_set_smart_temp(self.device.device_id, False)
        if not self.state_obj or not self.state_obj.bit(_AI_WASH_FIELD, _AI_WASH_BIT):
            await self._write_ai_bit(True)

    async def _select_standard(self) -> None:
        """标准：清 AI 位并关闭云感温。"""
        state = self.state_obj
        if state is not None and state.bit(_AI_WASH_FIELD, _AI_WASH_BIT):
            await self._write_ai_bit(False)
        smart = self.coordinator.runtime.smart_temp.get(self.device.device_id) or {}
        if smart.get("isEnabled") == 1:
            try:
                await self.coordinator.async_set_smart_temp(self.device.device_id, False)
            except VattiError as err:
                _LOGGER.error("关闭云感温失败（%s）：%s", self.device.name, err)

    async def _write_ai_bit(self, enabled: bool) -> None:
        """读改写 func_swit1，只动 AI 位，保留其它功能位。"""
        state = self.state_obj
        current = (state.get_int(_AI_WASH_FIELD) if state is not None else 0) or 0
        value = (current | _AI_WASH_MASK) if enabled else (current & ~_AI_WASH_MASK)
        await self.async_send({_AI_WASH_FIELD: str(value)})
