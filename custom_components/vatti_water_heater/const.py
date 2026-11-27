"""华帝热水器集成常量。"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "vatti_water_heater"
INTEGRATION_NAME: Final = "华帝热水器"
MANUFACTURER: Final = "Vatti"

# ---------------------------------------------------------------------------
# 云端接口
# ---------------------------------------------------------------------------
API_BASE: Final = "https://api.vcoo.cloud"
APP_VERSION: Final = "5.2.0"
USER_AGENT: Final = "okhttp/4.12.0"
API_TIMEOUT: Final = 15

# 登录链路固定参数（与华帝智慧家 App 5.x 一致）
SMS_REGION: Final = "86"
LOGIN_SOURCE: Final = 1
LAST_LOGIN_TYPE: Final = 1
PHONE_MODEL: Final = "HomeAssistant-Vatti"

ACCESS_KEY_ID: Final = "LTAI4GDu81NvNwcTUui3KAMV"
SIGN_SECRET: Final = "ImRL3iMesANyytkf8tSuZdDq0DrqL5"

EP_SMS_CODE: Final = "/api/app/v1/user/verification/code"
EP_LOGIN_CODE: Final = "/api/app/v1/user/login/code"
EP_USER_INFO: Final = "/api/app/v1/user/info"
EP_FAMILY_LIST: Final = "/api/app/v1/family/list"
EP_DEVICE_LIST: Final = "/api/app/v1/device/list"
EP_PROPERTY_STATUS: Final = "/api/app/v1/device/property/status"
EP_DEVICE_RRPC: Final = "/api/app/v1/device/rrpc"

# 智慧云感温：纯云端开关，请求体用 deviceName + productKey，不走 RRPC
EP_QUERY_SMART_TEMP: Final = "/api/app/v1/device/queryGh00SmartAdjTemp"
EP_SAVE_SMART_TEMP: Final = "/api/app/v1/device/saveGh00SmartAdjTemp"

# 能耗统计（App 能耗页 H5 接口，Bearer 鉴权，另一套签名）
EP_ENERGY: Final = "/ecm/getNewWaterGas"
ECM_ACCESS_KEY_ID: Final = "0123456789abcdef0123456789abcdef"
ECM_SECRET: Final = "5a026ec93de14f4186e0135a7c4722fc"
ENERGY_TYPE_GAS: Final = "0"
ENERGY_TYPE_WATER: Final = "2"

# 阿里云盾滑块 captchaId；华帝更换时可在滑块页地址后加 ?captchaId=xxx 覆盖
DEFAULT_CAPTCHA_ID: Final = "ffff91a30eea7c6e20d8e9aa7857f38b"
CAPTCHA_PATH: Final = "/api/vatti_water_heater_captcha"
CAPTCHA_TICKET_TTL: Final = 300

# ---------------------------------------------------------------------------
# 配置项
# ---------------------------------------------------------------------------
CONF_PHONE: Final = "phone"
CONF_TOKEN: Final = "token"
CONF_FAMILY_ID: Final = "family_id"
CONF_FAMILY_NAME: Final = "family_name"
CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_ENABLE_ENERGY: Final = "enable_energy"
# 机型识别：auto 按 productId / 品类推断，也可强制指定以套用对应能力表
CONF_DEVICE_KIND: Final = "device_kind"
KIND_AUTO: Final = "auto"

DEFAULT_POLL_INTERVAL: Final = 15
MIN_POLL_INTERVAL: Final = 5
MAX_POLL_INTERVAL: Final = 300
DEFAULT_ENABLE_ENERGY: Final = True

# 能耗数据变化慢，单独按固定周期刷新（秒）
ENERGY_REFRESH_INTERVAL: Final = 600
# 设备清单刷新周期（按轮询次数计），新绑定设备最迟约 5 分钟可见
DEVICE_LIST_REFRESH_CYCLES: Final = 20
# 智慧云感温配置刷新周期（按轮询次数计）
SMART_TEMP_REFRESH_CYCLES: Final = 10

DEVICE_PAGE_SIZE: Final = 200
MAX_DEVICE_PAGES: Final = 10
MAX_CONCURRENT_STATUS: Final = 4
MAX_BACKOFF_SECONDS: Final = 120

# 控制后等待设备上报、再做一次确认刷新的延时（秒）
CONFIRM_REFRESH_DELAY: Final = 2.0

PLATFORMS: Final = ["water_heater", "sensor", "switch", "binary_sensor", "button"]
