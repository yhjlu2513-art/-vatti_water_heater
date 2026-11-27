"""产品能力表：不同机型的状态字段、温度范围与功能位。

字段取值来自华帝智慧家 App 抓包（GH 系列燃气热水器已真机验证）。
其它机型若出现控制无效或方向相反，通常只需调整本文件里的位号或字段名。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import VattiDevice

KIND_GAS = "gas"
KIND_ZERO_COLD = "zero_cold"
KIND_ELECTRIC = "electric"

SUPPORTED_KINDS = (KIND_GAS, KIND_ZERO_COLD, KIND_ELECTRIC)

MODE_STANDARD = "standard"
MODE_AI_WASH = "ai_wash"
MODE_SMART_TEMP = "smart_temp"
MODE_LABELS = {
    MODE_STANDARD: "标准",
    MODE_AI_WASH: "AI智洗",
    MODE_SMART_TEMP: "智慧云感温",
}

POWER_FIELD = "powerStat"
FAULT_FIELDS = ("master_err", "err_lock")


@dataclass(frozen=True, slots=True)
class SensorSpec:
    """只读状态传感器。"""

    identifier: str
    key: str
    unit: str | None = None
    device_class: str | None = None
    diagnostic: bool = False
    factor: float | None = None


@dataclass(frozen=True, slots=True)
class SwitchSpec:
    """功能位开关（位域读改写）。"""

    key: str
    field: str
    bit: int
    icon: str = "mdi:toggle-switch-outline"
    # 打开本开关时需要同时清掉的其它位：(字段, 位号)
    clears: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class ProductSpec:
    kind: str
    label: str
    temp_field: str
    temp_min: int
    temp_max: int
    current_temp_fields: tuple[str, ...]
    switches: tuple[SwitchSpec, ...] = ()
    supports_smart_temp: bool = False
    sensors: tuple[SensorSpec, ...] = field(default_factory=tuple)


BASE_SENSORS = (
    SensorSpec("iwater_temp", "inlet_temp", "°C", "temperature"),
    SensorSpec("owater_temp", "outlet_temp", "°C", "temperature"),
    SensorSpec("water_flow", "water_flow", "L/min", None),
    SensorSpec("rssi", "wifi_signal", "%", None, diagnostic=True),
)

# 燃气恒温机（GH000174 真机标定）
GAS_SWITCHES = (
    SwitchSpec("preheat", "func_switch", 3, "mdi:fire"),
    SwitchSpec("waterfall", "func_switch", 5, "mdi:waves"),
    SwitchSpec(
        "eco",
        "func_swit1",
        3,
        "mdi:leaf",
        clears=(("func_swit2", 2),),
    ),
    SwitchSpec(
        "boost",
        "func_swit2",
        2,
        "mdi:rocket-launch-outline",
        clears=(("func_swit1", 3),),
    ),
    SwitchSpec("constant_temp", "func_swit2", 3, "mdi:thermostat-auto"),
)

# i12571 系列零冷水机型（i 12571b-16 等）。
# App 上的功能项：零冷水 / 瀑布浴 / 温度模式 / AI 智洗 / 点动循环 / 全水路自清洁。
# 「零冷水」与「瀑布浴」沿用 GH000174 同物模型的位号（bit3 / bit5），置信度高；
# 「点动循环」「全水路自清洁」为推测值，用 vatti_water_heater.watch 在真机标定后修正。
I12571_SWITCHES = (
    SwitchSpec("zero_cold", "func_switch", 3, "mdi:water-sync"),
    SwitchSpec("jet_cycle", "func_switch", 4, "mdi:sync"),
    SwitchSpec("waterfall", "func_switch", 5, "mdi:waves"),
    SwitchSpec("ai_wash", "func_switch", 1, "mdi:auto-fix"),
    SwitchSpec("self_clean", "func_swit1", 1, "mdi:water-outline"),
)

# 零冷水机型（按抓包实现，未真机实测）
ZERO_COLD_SWITCHES = (
    SwitchSpec("quick_heat", "func_switch", 1, "mdi:flash"),
    SwitchSpec("comfort_bath", "func_switch", 2, "mdi:shower"),
    SwitchSpec("boost", "func_switch", 3, "mdi:rocket-launch-outline"),
    SwitchSpec("bathtub", "func_switch", 4, "mdi:bathtub-outline"),
    SwitchSpec("ai_wash", "func_switch", 5, "mdi:auto-fix"),
    SwitchSpec("waterfall", "func_swit2", 2, "mdi:waves"),
)

SPEC_GAS = ProductSpec(
    kind=KIND_GAS,
    label="燃气热水器",
    temp_field="heater_temp",
    temp_min=35,
    temp_max=60,
    current_temp_fields=("owater_temp", "iwater_temp"),
    switches=GAS_SWITCHES,
    supports_smart_temp=True,
    sensors=BASE_SENSORS,
)

SPEC_ZERO_COLD = ProductSpec(
    kind=KIND_ZERO_COLD,
    label="零冷水燃气热水器",
    temp_field="heater_temp",
    temp_min=35,
    temp_max=60,
    current_temp_fields=("owater_temp", "iwater_temp"),
    switches=ZERO_COLD_SWITCHES,
    supports_smart_temp=False,
    sensors=BASE_SENSORS,
)

SPEC_I12571 = ProductSpec(
    kind=KIND_ZERO_COLD,
    label="零冷水燃气热水器 i12571",
    temp_field="heater_temp",
    temp_min=35,
    temp_max=60,
    current_temp_fields=("owater_temp", "iwater_temp"),
    switches=I12571_SWITCHES,
    supports_smart_temp=False,
    sensors=BASE_SENSORS,
)

SPEC_ELECTRIC = ProductSpec(
    kind=KIND_ELECTRIC,
    label="电热水器",
    temp_field="temp",
    temp_min=30,
    temp_max=75,
    current_temp_fields=("owater_temp", "temp"),
    switches=(),
    supports_smart_temp=False,
    sensors=BASE_SENSORS,
)

_ZERO_COLD_PRODUCTS = {"GH000190", "GH000191"}
# 机型串里出现这些片段即认定为零冷水 i12571 系列（App 设备详情里的 model）
_I12571_MODELS = ("12571",)

# 用户在选项里强制指定机型时使用的能力表
_OVERRIDES = {
    KIND_GAS: SPEC_GAS,
    KIND_ZERO_COLD: SPEC_ZERO_COLD,
    KIND_ELECTRIC: SPEC_ELECTRIC,
}


def spec_for_device(
    device: VattiDevice, override: str | None = None
) -> ProductSpec | None:
    """按 productId 前缀与品类名匹配热水器能力表；非热水器返回 None。

    ``override`` 来自选项里的「机型识别」，用于 productId 不在表内、
    但确定是某类热水器的情况。非热水器仍然返回 None，不会被强行接管。
    """
    detected = _detect_spec(device)
    if detected is None:
        return None
    forced = _OVERRIDES.get(override or "")
    return forced or detected


def _detect_spec(device: VattiDevice) -> ProductSpec | None:
    product_id = (device.product_id or "").upper()
    model = (device.model or "").lower()
    if any(token in model for token in _I12571_MODELS) or any(
        token in product_id.lower() for token in _I12571_MODELS
    ):
        return SPEC_I12571
    if product_id in _ZERO_COLD_PRODUCTS:
        return SPEC_ZERO_COLD
    if product_id.startswith("GH"):
        return SPEC_GAS
    if product_id.startswith("DR"):
        return SPEC_ELECTRIC

    category = device.category or ""
    if "零冷水" in category:
        return SPEC_ZERO_COLD
    if "电热" in category:
        return SPEC_ELECTRIC
    if "热水器" in category:
        return SPEC_GAS
    return None


def is_problem_state(state_props: dict[str, str]) -> bool:
    """故障标志：任一故障字段存在且不为 0 即视为告警。"""
    for identifier in FAULT_FIELDS:
        raw = state_props.get(identifier)
        if raw in (None, "", "0"):
            continue
        try:
            if float(raw) != 0:
                return True
        except ValueError:
            return True
    return False


def fault_text(state_props: dict[str, str]) -> str | None:
    """故障码文本（E 码或原始值），无故障返回 None。"""
    parts = []
    for identifier in FAULT_FIELDS:
        raw = state_props.get(identifier)
        if raw and raw != "0":
            parts.append(f"{identifier}={raw}")
    return ", ".join(parts) or None
