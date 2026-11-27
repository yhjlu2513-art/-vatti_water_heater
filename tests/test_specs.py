"""产品能力表测试。"""

from __future__ import annotations

from custom_components.vatti_water_heater.models import VattiDevice
from custom_components.vatti_water_heater.specs import (
    KIND_ELECTRIC,
    KIND_GAS,
    KIND_ZERO_COLD,
    fault_text,
    is_problem_state,
    spec_for_device,
)


def _device(product_id: str, category: str = "") -> VattiDevice:
    return VattiDevice(
        device_id="d",
        name="heater",
        product_id=product_id,
        product_key="pk",
        device_name="dn",
        model="m",
        category=category,
        family_id="f",
        online=True,
    )


def test_spec_by_product_prefix() -> None:
    assert spec_for_device(_device("GH000174")).kind == KIND_GAS
    assert spec_for_device(_device("GH000190")).kind == KIND_ZERO_COLD
    assert spec_for_device(_device("DR000001")).kind == KIND_ELECTRIC


def test_spec_by_category() -> None:
    assert spec_for_device(_device("", "燃气热水器")).kind == KIND_GAS
    assert spec_for_device(_device("", "零冷水热水器")).kind == KIND_ZERO_COLD
    assert spec_for_device(_device("", "电热水器")).kind == KIND_ELECTRIC
    assert spec_for_device(_device("", "油烟机")) is None


def test_temperature_ranges() -> None:
    gas = spec_for_device(_device("GH000174"))
    assert (gas.temp_min, gas.temp_max, gas.temp_field) == (35, 60, "heater_temp")
    electric = spec_for_device(_device("DR000001"))
    assert (electric.temp_min, electric.temp_max, electric.temp_field) == (
        30,
        75,
        "temp",
    )


def test_gas_switch_bits() -> None:
    gas = spec_for_device(_device("GH000174"))
    bits = {(item.field, item.bit) for item in gas.switches}
    assert ("func_switch", 3) in bits  # 一键预热
    assert ("func_switch", 5) in bits  # 瀑布浴
    assert ("func_swit1", 3) in bits  # 节能洗
    assert ("func_swit2", 2) in bits  # 一键增容
    assert ("func_swit2", 3) in bits  # 循环恒温

    eco = next(item for item in gas.switches if item.key == "eco")
    boost = next(item for item in gas.switches if item.key == "boost")
    assert eco.clears == (("func_swit2", 2),)
    assert boost.clears == (("func_swit1", 3),)


def test_problem_state() -> None:
    assert is_problem_state({}) is False
    assert is_problem_state({"master_err": "0"}) is False
    assert is_problem_state({"master_err": "12"}) is True
    assert is_problem_state({"err_lock": "E1"}) is True
    assert fault_text({"master_err": "12"}) == "master_err=12"
    assert fault_text({"master_err": "0"}) is None


def test_kind_override() -> None:
    """productId 不在零冷水名单里，也能强制套用零冷水能力表。"""
    device = _device("GH000999")
    assert spec_for_device(device).kind == KIND_GAS
    assert spec_for_device(device, KIND_ZERO_COLD).kind == KIND_ZERO_COLD
    assert spec_for_device(device, KIND_ELECTRIC).kind == KIND_ELECTRIC
    # 未知取值按自动识别处理
    assert spec_for_device(device, "nonsense").kind == KIND_GAS


def test_kind_override_never_takes_over_other_appliances() -> None:
    """强制机型只对热水器生效，不会把油烟机也接管。"""
    assert spec_for_device(_device("", "油烟机"), KIND_GAS) is None


def test_i12571_detected_by_model() -> None:
    """型号串里带 12571 就套用零冷水能力表，无需 productId 命中名单。"""
    device = _device("GH000174")
    device.model = "i 12571b-16"  # type: ignore[misc]
    spec = spec_for_device(device)
    assert spec is not None
    assert spec.kind == KIND_ZERO_COLD
    keys = [switch.key for switch in spec.switches]
    assert keys[0] == "zero_cold"
    assert "jet_cycle" in keys
    assert 35 <= spec.temp_min < spec.temp_max <= 60
