"""华帝云接口签名。

两套算法：

1. App 业务接口（``calc_sign``）
   ``sign = md5(<外层键字典序拼接> + SECRET)``，每项形如 ``k=v&``。
   空键、``sign`` 自身、None 与空串跳过；布尔渲染为 true/false；
   嵌套容器按 fastjson（Java HashMap 迭代序）渲染。

2. 能耗 H5 接口（``calc_sign_ecm``）
   ``sign = md5(<键字典序 "k=v&" 拼接去掉末尾 &> + "&" + ECM_SECRET)``；
   嵌套 dict 递归排序后紧凑 JSON 化。

两套算法都是纯函数，不依赖 Home Assistant，便于单元测试。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .const import ECM_SECRET, SIGN_SECRET


def _java_hash(value: str) -> int:
    """Java String.hashCode 的 int32 结果（无符号保存）。"""
    result = 0
    for char in value:
        result = (31 * result + ord(char)) & 0xFFFFFFFF
    return result


def _hashmap_order(mapping: dict[str, Any]) -> list[str]:
    """按 Java HashMap 迭代序返回键顺序。

    服务端把 JSON 反序列化成 HashMap 后再取值参与签名，所以嵌套对象
    必须按 HashMap 的桶顺序渲染，普通字典序会对不上。
    """
    keys = list(mapping)
    if len(keys) <= 1:
        return keys
    capacity = 16
    while len(keys) > (capacity * 3) >> 2:
        capacity <<= 1
    buckets: list[list[str]] = [[] for _ in range(capacity)]
    for key in keys:
        hashed = _java_hash(key)
        buckets[(hashed ^ (hashed >> 16)) & (capacity - 1)].append(key)
    order: list[str] = []
    for bucket in buckets:
        order.extend(bucket)
    return order


def _fastjson_dump(value: Any) -> str:
    """fastjson 风格序列化：紧凑、无多余空格、嵌套对象按 HashMap 序。"""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    if isinstance(value, list):
        return "[" + ",".join(_fastjson_dump(item) for item in value) + "]"
    if isinstance(value, dict):
        items = (
            json.dumps(key, ensure_ascii=False) + ":" + _fastjson_dump(value[key])
            for key in _hashmap_order(value)
        )
        return "{" + ",".join(items) + "}"
    return str(value)


def calc_sign(payload: dict[str, Any], secret: str = SIGN_SECRET) -> str:
    """计算 App 业务接口的 sign。"""
    parts: list[str] = []
    for key in sorted(payload):
        value = payload[key]
        if key in ("sign", "") or value is None or value == "":
            continue
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (dict, list)):
            rendered = _fastjson_dump(value)
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}&")
    return hashlib.md5(("".join(parts) + secret).encode()).hexdigest()


def _ecm_canonical(value: Any) -> Any:
    """递归按键排序并剔除 None，用于嵌套对象。"""
    if isinstance(value, dict):
        return {
            key: _ecm_canonical(value[key])
            for key in sorted(value)
            if value[key] is not None
        }
    return value


def _ecm_render(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return json.dumps(_ecm_canonical(value), separators=(",", ":"), ensure_ascii=False)
    if isinstance(value, list):
        items = [
            _ecm_render(item) if isinstance(item, (dict, list)) else item
            for item in value
        ]
        return "[" + ",".join(str(item) for item in items) + "]"
    return str(value)


def calc_sign_ecm(payload: dict[str, Any], secret: str = ECM_SECRET) -> str:
    """计算能耗统计接口的 sign。"""
    parts = [
        f"{key}={_ecm_render(payload[key])}&"
        for key in sorted(payload)
        if payload[key] is not None
    ]
    canonical = "".join(parts)[:-1]
    return hashlib.md5((canonical + "&" + secret).encode()).hexdigest()
