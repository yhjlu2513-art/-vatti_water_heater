"""数据协调器：设备清单、物模型状态、能耗与云感温配置。

- 状态按选项间隔轮询（默认 15 秒，5–300 秒可调）；
- 单台设备状态失败不影响其它设备；
- 连续失败指数退避（15 → 30 → 60 → 120 封顶），恢复后复位；
- 控制指令下发后先乐观更新界面，2 秒后再用设备真实上报校正；
- 能耗数据变化慢，独立按 10 分钟周期刷新，不占用状态轮询。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import VattiClient
from .const import (
    CONF_DEVICE_KIND,
    CONF_ENABLE_ENERGY,
    CONF_FAMILY_ID,
    CONF_POLL_INTERVAL,
    CONFIRM_REFRESH_DELAY,
    DEFAULT_ENABLE_ENERGY,
    DEFAULT_POLL_INTERVAL,
    KIND_AUTO,
    DEVICE_LIST_REFRESH_CYCLES,
    DOMAIN,
    ENERGY_REFRESH_INTERVAL,
    MAX_BACKOFF_SECONDS,
    MAX_CONCURRENT_STATUS,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    SMART_TEMP_REFRESH_CYCLES,
)
from .device_helpers import build_state
from .energy import EnergyOverview, EnergySummary, summarize
from .exceptions import (
    VattiApiError,
    VattiAuthError,
    VattiConnectionError,
)
from .models import DeviceState, VattiDevice
from .specs import ProductSpec, spec_for_device

_LOGGER = logging.getLogger(__name__)

_ENVELOPE_KEYS = frozenset({"controller", "timeout"})

# config_entry 参数是 HA 2024.4 才加的，旧版本不能传
_SUPPORTS_CONFIG_ENTRY = (
    "config_entry"
    in inspect.signature(DataUpdateCoordinator.__init__).parameters
)


@dataclass
class VattiRuntime:
    """配置条目的运行时数据（挂在 hass.data 上）。"""

    client: VattiClient
    devices: dict[str, VattiDevice] = field(default_factory=dict)
    specs: dict[str, ProductSpec] = field(default_factory=dict)
    states: dict[str, DeviceState] = field(default_factory=dict)
    energy: dict[str, dict[str, EnergySummary]] = field(default_factory=dict)
    smart_temp: dict[str, dict[str, Any]] = field(default_factory=dict)
    family_id: str | None = None
    energy_updated_at: float = 0.0

    def is_heater(self, device_id: str) -> bool:
        return device_id in self.specs


class VattiCoordinator(DataUpdateCoordinator[dict[str, DeviceState]]):
    """轮询华帝云并保存每台设备的属性快照。"""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: VattiClient,
        runtime: VattiRuntime,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=_clamp_interval(entry)),
            **({"config_entry": entry} if _SUPPORTS_CONFIG_ENTRY else {}),
        )
        self.entry = entry
        self._device_kind = str(entry.options.get(CONF_DEVICE_KIND, KIND_AUTO))
        self.client = client
        self.runtime = runtime
        self._failures = 0
        self._cycles = 0
        self._status_failed: set[str] = set()
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._cancel_handles: list[Any] = []
        self._energy_task: asyncio.Task[Any] | None = None
        self._smart_task: asyncio.Task[Any] | None = None

    # ------------------------------------------------------------------
    # 轮询
    # ------------------------------------------------------------------
    async def _async_update_data(self) -> dict[str, DeviceState]:
        try:
            return await self._async_poll()
        except VattiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (VattiConnectionError, VattiApiError) as err:
            self._apply_backoff()
            raise UpdateFailed(str(err)) from err

    async def _async_poll(self) -> dict[str, DeviceState]:
        family_id = await self._async_resolve_family()
        if not self.runtime.devices or self._cycles % DEVICE_LIST_REFRESH_CYCLES == 0:
            await self._async_refresh_devices(family_id)

        devices = list(self.runtime.devices.values())
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_STATUS)
        states: dict[str, DeviceState] = {}

        async def load(device: VattiDevice) -> None:
            async with semaphore:
                try:
                    props = await self.client.properties(device.device_id)
                except VattiAuthError:
                    raise
                except (VattiConnectionError, VattiApiError) as err:
                    if device.device_id not in self._status_failed:
                        self._status_failed.add(device.device_id)
                        _LOGGER.warning("读取设备状态失败（%s）：%s", device.name, err)
                    return
            self._status_failed.discard(device.device_id)
            states[device.device_id] = build_state(device.device_id, props)

        await asyncio.gather(*(load(device) for device in devices))
        if devices and not states:
            raise VattiConnectionError("所有设备状态均读取失败")

        self.runtime.states = states
        self._failures = 0
        self._set_interval(self._interval_seconds())
        self._cycles += 1

        self._maybe_refresh_energy(devices)
        self._maybe_refresh_smart_temp()
        return states

    # ------------------------------------------------------------------
    # 家庭与设备清单
    # ------------------------------------------------------------------
    async def _async_resolve_family(self) -> str:
        if self.runtime.family_id:
            return self.runtime.family_id
        families = await self.client.families()
        if not families:
            raise VattiApiError("账号下没有家庭")
        configured = str(self.entry.data.get(CONF_FAMILY_ID) or "")
        for family in families:
            family_id = str(family.get("familyId") or family.get("id") or "")
            if configured and family_id == configured:
                self.runtime.family_id = family_id
                return family_id
        if configured:
            _LOGGER.warning("配置的家庭 %s 不存在，改用第一个家庭", configured)
        first = str(families[0].get("familyId") or families[0].get("id") or "")
        if not first:
            raise VattiApiError("家庭数据缺少 familyId")
        self.runtime.family_id = first
        return first

    async def _async_refresh_devices(self, family_id: str) -> None:
        previous = set(self.runtime.devices)
        raw_devices = await self.client.devices(family_id)
        devices: dict[str, VattiDevice] = {}
        specs: dict[str, ProductSpec] = {}
        for item in raw_devices:
            try:
                device = VattiDevice.from_api(item)
            except ValueError:
                continue
            devices[device.device_id] = device
            spec = spec_for_device(device, self._device_kind)
            if spec is not None:
                specs[device.device_id] = spec
            else:
                _LOGGER.debug("跳过非热水器设备：%s（%s）", device.name, device.category)
        self.runtime.devices = devices
        self.runtime.specs = specs
        self._sync_device_registry(devices)

        current = set(devices)
        if previous and previous != current:
            _LOGGER.info("设备清单变化（%d → %d），重载集成", len(previous), len(current))
            self.hass.async_create_task(self.hass.config_entries.async_reload(self.entry.entry_id))

    @callback
    def _sync_device_registry(self, devices: dict[str, VattiDevice]) -> None:
        from homeassistant.helpers import device_registry as dr

        registry = dr.async_get(self.hass)
        for device in devices.values():
            registry.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                identifiers={(DOMAIN, device.device_id)},
                manufacturer="Vatti",
                name=device.name,
                model=device.model,
            )

    # ------------------------------------------------------------------
    # 能耗
    # ------------------------------------------------------------------
    def _maybe_refresh_energy(self, devices: list[VattiDevice]) -> None:
        if not self.entry.options.get(CONF_ENABLE_ENERGY, DEFAULT_ENABLE_ENERGY):
            return
        if time.time() - self.runtime.energy_updated_at < ENERGY_REFRESH_INTERVAL:
            return
        if self._energy_task is not None and not self._energy_task.done():
            return
        self._energy_task = self._spawn(self._async_refresh_energy(devices))

    async def _async_refresh_energy(self, devices: list[VattiDevice]) -> None:
        today = date.today()
        for device in devices:
            if device.device_id not in self.runtime.specs:
                continue
            for is_gas in (True, False):
                try:
                    overview: EnergyOverview = await self.client.energy_overview(
                        device.device_id, is_gas
                    )
                except VattiAuthError:
                    raise
                except (VattiConnectionError, VattiApiError) as err:
                    _LOGGER.debug(
                        "能耗读取失败（%s %s）：%s",
                        device.name,
                        "气" if is_gas else "水",
                        err,
                    )
                    continue
                bucket = self.runtime.energy.setdefault(device.device_id, {})
                bucket["gas" if is_gas else "water"] = summarize(overview, is_gas, today)
        self.runtime.energy_updated_at = time.time()
        self.async_update_listeners()

    # ------------------------------------------------------------------
    # 智慧云感温
    # ------------------------------------------------------------------
    def _maybe_refresh_smart_temp(self) -> None:
        if self._cycles % SMART_TEMP_REFRESH_CYCLES != 0:
            return
        if self._smart_task is not None and not self._smart_task.done():
            return
        self._smart_task = self._spawn(self.async_refresh_smart_temp())

    async def async_refresh_smart_temp(self) -> None:
        for device in self.runtime.devices.values():
            spec = self.runtime.specs.get(device.device_id)
            if spec is None or not spec.supports_smart_temp:
                continue
            if not device.device_name or not device.product_key:
                continue
            try:
                data = await self.client.query_smart_temp(
                    device.device_name, device.product_key
                )
            except (VattiConnectionError, VattiApiError) as err:
                _LOGGER.debug("云感温配置读取失败（%s）：%s", device.name, err)
                continue
            self.runtime.smart_temp[device.device_id] = {
                "isEnabled": data.get("isEnabled"),
                "tempAdjData": data.get("tempAdjData"),
            }
        self.async_update_listeners()

    async def async_set_smart_temp(self, device_id: str, enabled: bool) -> None:
        device = self.runtime.devices.get(device_id)
        if device is None:
            raise VattiApiError("未知设备")
        cached = self.runtime.smart_temp.get(device_id) or {}
        if cached.get("isEnabled") is not None and bool(cached["isEnabled"]) == enabled:
            return
        await self.client.save_smart_temp(
            device.device_name,
            device.product_key,
            enabled,
            temp_adj_data=cached.get("tempAdjData"),
        )
        stored = self.runtime.smart_temp.setdefault(device_id, {})
        stored["isEnabled"] = 1 if enabled else 0
        self.async_update_listeners()

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------
    async def async_send_command(self, device_id: str, message: dict[str, Any]) -> None:
        """下发控制指令；成功后乐观更新，稍后按设备上报校正。"""
        lock = self._locks.setdefault(device_id, asyncio.Lock())
        async with lock:
            await self.client.send_command(device_id, message)
        self._apply_optimistic(device_id, message)
        self.async_update_listeners()
        handle = async_call_later(
            self.hass, CONFIRM_REFRESH_DELAY, self._async_confirm(device_id)
        )
        self._cancel_handles.append(handle)
        # 只保留最近一批确认句柄，避免长期运行无限增长
        while len(self._cancel_handles) > 50:
            self._cancel_handles.pop(0)()

    def _apply_optimistic(self, device_id: str, message: dict[str, Any]) -> None:
        state = self.runtime.states.get(device_id)
        if state is None:
            return
        for key, value in message.items():
            if key in _ENVELOPE_KEYS:
                continue
            state.props[key] = str(value)
        state.fetched_at = time.time()

    def _async_confirm(self, device_id: str):
        async def run(_now: datetime | None = None) -> None:
            await self.async_refresh_device(device_id)

        return run

    async def async_refresh_device(self, device_id: str) -> None:
        try:
            props = await self.client.properties(device_id)
        except (VattiConnectionError, VattiApiError) as err:
            _LOGGER.debug("控制后刷新失败：%s", err)
            return
        self.runtime.states[device_id] = build_state(device_id, props)
        self.async_update_listeners()

    # ------------------------------------------------------------------
    # 后台任务与退避
    # ------------------------------------------------------------------
    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        task = self.hass.async_create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _interval_seconds(self) -> int:
        return _clamp_interval(self.entry)

    def _apply_backoff(self) -> None:
        self._failures += 1
        delay = min(self._interval_seconds() * (2**self._failures), MAX_BACKOFF_SECONDS)
        self._set_interval(delay)
        _LOGGER.debug("轮询失败 %d 次，%d 秒后重试", self._failures, delay)

    def _set_interval(self, seconds: int) -> None:
        self.update_interval = timedelta(seconds=seconds)

    async def async_shutdown(self) -> None:
        for handle in self._cancel_handles:
            handle()
        self._cancel_handles.clear()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)
        # 新版 HA 的 Coordinator 自己管理刷新定时器，需要一并关闭
        parent_shutdown = getattr(super(), "async_shutdown", None)
        if parent_shutdown is not None:
            await parent_shutdown()


def _clamp_interval(entry: ConfigEntry) -> int:
    try:
        value = int(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
    except (TypeError, ValueError):
        return DEFAULT_POLL_INTERVAL
    return max(MIN_POLL_INTERVAL, min(MAX_POLL_INTERVAL, value))
