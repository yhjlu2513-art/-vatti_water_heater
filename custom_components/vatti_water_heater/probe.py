"""位域探针：定位「零冷水 / 预热 / 巡航」等功能的真实字段与位号。

非官方云接口没有公开文档，同一品类不同机型的功能位定义并不统一。本模块提供
两个服务，用于在真机上反推位号：

``vatti_water_heater.snapshot``
    立即向云端拉一次实时属性，存成快照（不动设备）。
``vatti_water_heater.diff_snapshot``
    与上次快照对比，指出哪些字段变了、哪一位翻转了，并给出可直接粘贴到
    ``specs.py`` 的 ``SwitchSpec`` 代码行。

典型用法：先 snapshot → 在手机 App 里点一次「零冷水」→ 再 diff_snapshot。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .coordinator import VattiCoordinator
from .models import VattiDevice

PROBE_STORE = f"{DOMAIN}_probe"
SERVICE_SNAPSHOT = "snapshot"
SERVICE_DIFF = "diff_snapshot"
SERVICE_WATCH = "watch"
SERVICE_WATCH_REPORT = "watch_report"

WATCH_STORE = f"{DOMAIN}_watch"
DEFAULT_WATCH_SECONDS = 300
DEFAULT_WATCH_INTERVAL = 6
MIN_WATCH_SECONDS = 30
MAX_WATCH_SECONDS = 900

DEFAULT_ICON = "mdi:water-sync"


def _store(hass: HomeAssistant) -> dict[str, Any]:
    return hass.data.setdefault(PROBE_STORE, {})


def _matches(device: VattiDevice, selector: str | None) -> bool:
    if not selector:
        return True
    needle = selector.strip().lower()
    if not needle:
        return True
    return needle in device.device_id.lower() or needle in (device.name or "").lower()


def _targets(
    hass: HomeAssistant, selector: str | None
) -> list[tuple[VattiCoordinator, VattiDevice]]:
    """按设备名/ID 过滤出可探测的热水器。"""
    found: list[tuple[VattiCoordinator, VattiDevice]] = []
    for coordinator in hass.data.get(DOMAIN, {}).values():
        if not isinstance(coordinator, VattiCoordinator):
            continue
        for device_id, device in coordinator.runtime.devices.items():
            if not coordinator.runtime.is_heater(device_id):
                continue
            if _matches(device, selector):
                found.append((coordinator, device))
    return found


def _flipped_bits(old: Any, new: Any) -> list[int]:
    """两个取值之间翻转的位号；非整数返回空。"""
    left, right = str(old), str(new)
    # 带小数的字段（温度、流量、压力）做位运算没有意义，直接跳过
    if "." in left or "." in right:
        return []
    try:
        a, b = int(left), int(right)
    except (TypeError, ValueError):
        return []
    diff = a ^ b
    return [bit for bit in range(32) if (diff >> bit) & 1]


def _field_hint(field: str, bit: int) -> str:
    """给出可直接粘贴到 specs.py 的 SwitchSpec 代码行。"""
    return (
        f'SwitchSpec("new_{field.lower()}_bit{bit}", "{field}", {bit}, "{DEFAULT_ICON}"),'
    )


async def _capture(
    hass: HomeAssistant, targets: list[tuple[VattiCoordinator, VattiDevice]]
) -> dict[str, Any]:
    """实时拉取一次属性并写入快照。"""
    store = _store(hass)
    now = time.time()
    saved: list[dict[str, Any]] = []
    for coordinator, device in targets:
        try:
            await coordinator.async_refresh_device(device.device_id)
        except Exception as err:  # noqa: BLE001 - 单台失败不影响其它设备
            saved.append({"device": device.name, "error": str(err)})
            continue
        state = coordinator.runtime.states.get(device.device_id)
        props = dict(state.props) if state is not None else {}
        store[device.device_id] = {
            "name": device.name,
            "product_id": device.product_id,
            "at": now,
            "props": props,
        }
        saved.append(
            {
                "device": device.name,
                "device_id": device.device_id,
                "fields": len(props),
                "props": props,
            }
        )
    return {"count": len(saved), "devices": saved}


async def _diff(
    hass: HomeAssistant, targets: list[tuple[VattiCoordinator, VattiDevice]]
) -> dict[str, Any]:
    """快照与当前实时属性对比。"""
    store = _store(hass)
    reports: list[dict[str, Any]] = []

    for coordinator, device in targets:
        snapshot = store.get(device.device_id)
        if snapshot is None:
            reports.append(
                {
                    "device": device.name,
                    "error": "还没有快照，先调用一次 snapshot 服务",
                }
            )
            continue

        await coordinator.async_refresh_device(device.device_id)
        state = coordinator.runtime.states.get(device.device_id)
        current = dict(state.props) if state is not None else {}

        changes: list[dict[str, Any]] = []
        for field in sorted(set(snapshot["props"]) | set(current)):
            before = snapshot["props"].get(field)
            after = current.get(field)
            if before == after:
                continue
            changes.append(
                {
                    "field": field,
                    "before": before,
                    "after": after,
                    "bits": _flipped_bits(before, after),
                }
            )

        reports.append(
            {
                "device": device.name,
                "device_id": device.device_id,
                "product_id": device.product_id,
                "snapshot_at": datetime.fromtimestamp(snapshot["at"]).strftime(
                    "%H:%M:%S"
                ),
                "now_at": datetime.fromtimestamp(time.time()).strftime("%H:%M:%S"),
                "changes": changes,
            }
        )

    return {"devices": reports}


def _render(reports: list[dict[str, Any]]) -> str:
    """把对比结果渲染成一条通知。"""
    lines: list[str] = ["## 华帝热水器 · 位域对比"]
    for report in reports:
        name = report.get("device", "未知设备")
        if "error" in report:
            lines.append(f"\n**{name}**：{report['error']}")
            continue
        lines.append(
            f"\n**{name}**（{report.get('product_id') or '-'}）"
            f"  `{report['snapshot_at']}` → `{report['now_at']}`"
        )
        changes = report["changes"]
        if not changes:
            lines.append(
                "\n未检测到任何字段变化，可以依次排查：\n"
                "1. 设备上报有延迟，等 10–30 秒后再点一次对比；\n"
                "2. 该功能走独立接口（例如零冷水定时任务），不走物模型属性；\n"
                "3. App 操作的是别的设备分组或别的账号下的设备。"
            )
            continue

        lines.append("\n| 字段 | 之前 | 现在 | 翻转位 |")
        lines.append("| --- | --- | --- | --- |")
        hints: list[str] = []
        enum_fields: list[str] = []
        for change in changes:
            bits = change["bits"]
            if not bits:
                bit_text = "数值/文本变化"
                enum_fields.append(change["field"])
            elif len(bits) > 3:
                bit_text = f"{len(bits)} 位同时变化（像枚举值）"
                enum_fields.append(change["field"])
            else:
                bit_text = "、".join(f"bit{b}" for b in bits)
            lines.append(
                f"| `{change['field']}` | `{change['before']}` | "
                f"`{change['after']}` | {bit_text} |"
            )
            if len(bits) <= 3:
                for bit in bits:
                    hints.append("  " + _field_hint(change["field"], bit))

        if enum_fields:
            lines.append(
                "\n字段 "
                + "、".join(f"`{field}`" for field in enum_fields)
                + " 看起来是多值枚举，用开关表达不合适，"
                "建议做成 `select` 实体（`options` 里列出 App 上见到的几档）。"
            )

        if hints:
            lines.append("\n把翻转的那一位填进 `specs.py` 即可生成开关：\n")
            lines.append("```python")
            lines.extend(hints)
            lines.append("```")
            lines.append(
                "\n若 App 上这一项是多档选项（关 / 单次 / 定时），那它其实是枚举值，"
                "改用 `select` 实体更准确。"
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 连续监听：一段时间内记录每一次字段变化，适合一次性把 App 上多个功能点完
# ---------------------------------------------------------------------------


def _diff_props(prev: dict[str, str], current: dict[str, str]) -> list[dict[str, Any]]:
    """两次采样的字段差异。"""
    events: list[dict[str, Any]] = []
    for field in sorted(set(prev) | set(current)):
        before, after = prev.get(field), current.get(field)
        if before == after:
            continue
        events.append(
            {
                "field": field,
                "before": before,
                "after": after,
                "bits": _flipped_bits(before, after),
            }
        )
    return events


def _render_snapshot(devices: list[dict[str, Any]]) -> str:
    """把原始属性渲染成可读通知，便于直接对照 App 状态。"""
    lines = ["## 华帝热水器 · 原始状态"]
    for device in devices:
        name = device.get("device") or device.get("device_id") or "未知设备"
        if "error" in device:
            lines.append(f"\n**{name}**：{device['error']}")
            continue
        lines.append(
            f"\n**{name}**（{device.get('device_id') or '-'}）"
            f" · {device.get('fields', 0)} 个字段"
        )
        lines.append("\n| 字段 | 值 |")
        lines.append("| --- | --- |")
        for key, value in sorted((device.get("props") or {}).items()):
            lines.append(f"| `{key}` | `{value}` |")
    return "\n".join(lines)


def _render_watch(states: list[dict[str, Any]]) -> str:
    """把监听结果渲染成一条通知。"""
    if not states:
        return "还没有监听记录，先调用 `vatti_water_heater.watch` 开始监听。"

    lines = ["## 华帝热水器 · 位域监听"]
    for state in states:
        name = state.get("name") or state.get("device_id") or "未知设备"
        elapsed = int(time.time() - state.get("start", time.time()))
        status = "监听中" if state.get("running") else "已结束"
        lines.append(
            f"\n**{name}**（{state.get('product_id') or '-'}） "
            f"{status} · 已 {elapsed} 秒 · {len(state.get('events', []))} 次变化"
        )

        events = state.get("events") or []
        if not events:
            lines.append("\n还没有捕获到变化。在 App 上操作一次目标功能，稍等几秒再看。")
            continue

        lines.append("\n| 相对时间 | 字段 | 之前 | 现在 | 翻转位 |")
        lines.append("| --- | --- | --- | --- | --- |")
        hints: list[str] = []
        for event in events:
            bits = event["bits"]
            bit_text = "、".join(f"bit{b}" for b in bits) if bits else "数值变化"
            lines.append(
                f"| +{event.get('at', 0):.1f}s | `{event['field']}` | "
                f"`{event['before']}` | `{event['after']}` | {bit_text} |"
            )
            if len(bits) <= 3:
                for bit in bits:
                    hints.append("  " + _field_hint(event["field"], bit))

        if hints:
            lines.append("\n对照你操作的先后顺序，把对应那位填进 `specs.py`：\n")
            lines.append("```python")
            lines.extend(dict.fromkeys(hints))  # 去重且保持顺序
            lines.append("```")

    return "\n".join(lines)


def _watch_state(hass: HomeAssistant) -> dict[str, Any]:
    return hass.data.setdefault(WATCH_STORE, {})


async def _watch_loop(
    hass: HomeAssistant,
    coordinator: VattiCoordinator,
    device: VattiDevice,
    duration: int,
    interval: int,
) -> None:
    state = _watch_state(hass).setdefault(device.device_id, {})
    state.update(
        {
            "name": device.name,
            "device_id": device.device_id,
            "product_id": device.product_id,
            "start": time.time(),
            "events": [],
            "errors": 0,
            "running": True,
        }
    )
    events: list[dict[str, Any]] = state["events"]
    prev: dict[str, str] | None = None

    while time.time() - state["start"] < duration:
        try:
            props = await coordinator.client.properties(device.device_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 网络抖动不影响整段监听
            state["errors"] += 1
        else:
            current = {
                key: str(item.get("value"))
                for key, item in props.items()
                if isinstance(item, dict) and item.get("value") not in (None, "")
            }
            if prev is not None:
                for event in _diff_props(prev, current):
                    event["at"] = round(time.time() - state["start"], 1)
                    events.append(event)
            prev = current
        await asyncio.sleep(interval)

    state["running"] = False
    text = _render_watch([state])
    persistent_notification.async_create(
        hass, text, title="华帝热水器 · 位域监听结果", notification_id="vatti_probe_watch"
    )


async def async_setup_probe_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SNAPSHOT):
        return

    async def handle_snapshot(call: ServiceCall) -> dict[str, Any]:
        selector = call.data.get("device")
        targets = _targets(hass, selector)
        if not targets:
            raise HomeAssistantError(
                f"没有匹配「{selector}」的热水器，请留空 device 参数以探测全部设备"
            )
        result = await _capture(hass, targets)
        _store(hass)["__last__"] = result
        persistent_notification.async_create(
            hass,
            _render_snapshot(result["devices"]),
            title="华帝热水器 · 原始状态",
            notification_id="vatti_probe_snapshot",
        )
        return result

    async def handle_diff(call: ServiceCall) -> dict[str, Any]:
        selector = call.data.get("device")
        targets = _targets(hass, selector)
        if not targets:
            raise HomeAssistantError(
                f"没有匹配「{selector}」的热水器，请留空 device 参数以探测全部设备"
            )
        result = await _diff(hass, targets)
        text = _render(result["devices"])
        persistent_notification.async_create(
            hass, text, title="华帝热水器 · 位域对比", notification_id="vatti_probe_diff"
        )
        return {"report": text, **result}

    hass.services.async_register(
        DOMAIN,
        SERVICE_SNAPSHOT,
        handle_snapshot,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DIFF,
        handle_diff,
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_watch(call: ServiceCall) -> dict[str, Any]:
        selector = call.data.get("device")
        duration = int(call.data.get("duration") or DEFAULT_WATCH_SECONDS)
        duration = max(MIN_WATCH_SECONDS, min(MAX_WATCH_SECONDS, duration))
        interval = int(call.data.get("interval") or DEFAULT_WATCH_INTERVAL)
        interval = max(2, min(30, interval))

        targets = _targets(hass, selector)
        if not targets:
            raise HomeAssistantError(
                f"没有匹配「{selector}」的热水器，请留空 device 参数以监听全部设备"
            )

        store = _watch_state(hass)
        started: list[dict[str, Any]] = []
        tasks: set[asyncio.Task[Any]] = store.setdefault("__tasks__", set())
        for coordinator, device in targets:
            state = store.get(device.device_id)
            if isinstance(state, dict) and state.get("running"):
                started.append({"device": device.name, "error": "已在监听中"})
                continue
            task = hass.async_create_task(
                _watch_loop(hass, coordinator, device, duration, interval)
            )
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            started.append(
                {
                    "device": device.name,
                    "device_id": device.device_id,
                    "seconds": duration,
                    "interval": interval,
                }
            )
        return {"started": started}

    async def handle_watch_report(call: ServiceCall) -> dict[str, Any]:
        states = [
            state
            for state in _watch_state(hass).values()
            if isinstance(state, dict) and "events" in state
        ]
        text = _render_watch(states)
        persistent_notification.async_create(
            hass, text, title="华帝热水器 · 位域监听", notification_id="vatti_probe_watch"
        )
        return {"report": text, "devices": states}

    hass.services.async_register(
        DOMAIN,
        SERVICE_WATCH,
        handle_watch,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_WATCH_REPORT,
        handle_watch_report,
        supports_response=SupportsResponse.OPTIONAL,
    )


async def async_unload_probe_services(hass: HomeAssistant) -> None:
    for service in (SERVICE_SNAPSHOT, SERVICE_DIFF, SERVICE_WATCH, SERVICE_WATCH_REPORT):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)

    store = hass.data.pop(WATCH_STORE, None)
    if isinstance(store, dict):
        for task in list(store.get("__tasks__", ())):
            task.cancel()
    hass.data.pop(PROBE_STORE, None)
