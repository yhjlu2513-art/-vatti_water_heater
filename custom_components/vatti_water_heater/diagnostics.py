"""诊断信息导出（设置 → 设备与服务 → 集成 → 下载诊断信息）。"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_FAMILY_ID, CONF_FAMILY_NAME, CONF_PHONE, CONF_TOKEN, DOMAIN
from .coordinator import VattiCoordinator


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}***{value[-4:]}"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: VattiCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = {
        "phone": _mask(str(entry.data.get(CONF_PHONE) or "")),
        "token": _mask(str(entry.data.get(CONF_TOKEN) or "")),
        "family_id": entry.data.get(CONF_FAMILY_ID),
        "family_name": entry.data.get(CONF_FAMILY_NAME),
    }
    options = dict(entry.options)
    if coordinator is None:
        return {"entry": data, "options": options, "loaded": False}

    runtime = coordinator.runtime
    return {
        "entry": data,
        "options": options,
        "loaded": True,
        "last_update_success": coordinator.last_update_success,
        "devices": [
            {
                "device_id": device.device_id,
                "name": device.name,
                "product_id": device.product_id,
                "model": device.model,
                "category": device.category,
                "online": device.online,
                "kind": runtime.specs[device_id].kind if device_id in runtime.specs else None,
            }
            for device_id, device in runtime.devices.items()
        ],
        "states": {
            device_id: {
                "props": state.props,
                "reported_at": state.props_ts,
            }
            for device_id, state in runtime.states.items()
        },
        "smart_temp": runtime.smart_temp,
        "energy": {
            device_id: {
                kind: {
                    "today": summary.today,
                    "week": summary.week,
                    "year": summary.year,
                    "week_series": summary.week_series,
                }
                for kind, summary in bucket.items()
            }
            for device_id, bucket in runtime.energy.items()
        },
    }
