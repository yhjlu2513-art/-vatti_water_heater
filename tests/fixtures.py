"""测试用设备与物模型数据。"""

DEVICE = {
    "id": "dev-1",
    "nickname": "Kitchen Heater",
    "productId": "GH000174",
    "productKey": "pk-1",
    "deviceName": "gh000174-abc",
    "model": "i12031",
    "categoryName": "燃气热水器",
    "familyId": "f1",
    "status": 1,
    "snCode": "SN123",
}

PROPS = {
    "heater_temp": {"value": "45", "time": 1_700_000_000_000},
    "powerStat": {"value": "1", "time": 1_700_000_000_000},
    "func_switch": {"value": "8", "time": 1_700_000_000_000},
    "func_swit1": {"value": "0", "time": 1_700_000_000_000},
    "func_swit2": {"value": "0", "time": 1_700_000_000_000},
    "owater_temp": {"value": "41.5", "time": 1_700_000_000_000},
    "iwater_temp": {"value": "18.0", "time": 1_700_000_000_000},
    "water_flow": {"value": "6.2", "time": 1_700_000_000_000},
    "rssi": {"value": "80", "time": 1_700_000_000_000},
    "snCode": {"value": "SN123", "time": 1_700_000_000_000},
}
