# 华帝热水器 Home Assistant 集成

把「华帝智慧家」App 里的燃气/电热水器接进 Home Assistant：看水温、调温度、开关机、切换洗浴模式、读用气用水量，并参与自动化和语音控制。

这是一个独立的 HACS 自定义集成，只做热水器，不做灶具/油烟机，代码量和实体噪音都更小。

> 云端接口来自对华帝智慧家 App 的抓包分析，**非官方 API**。华帝若调整接口，集成可能需要跟进适配。

---

## 功能

| 能力 | 说明 |
|---|---|
| 开关机 | `water_heater.turn_on / turn_off` |
| 目标温度 | 燃气机 35–60 ℃、电热机 30–75 ℃，按机型自动限制 |
| 当前水温 | 取设备出水温度，和 App 显示一致 |
| 运行模式 | 标准 / AI 智洗 / 智慧云感温，三态互斥，切换时自动处理互斥关系 |
| 功能开关 | 一键预热、瀑布浴、节能洗、一键增容、循环恒温（按机型） |
| 零冷水 | 燃气零冷水机型可选预热/巡航位；位号可用内置探针现场标定，见「零冷水怎么接」 |
| 状态传感 | 进水温度、出水温度、水流量、WiFi 信号、故障码、最后上报时间 |
| 能耗统计 | 今日 / 本周 / 年度用气量与用水量，附本周逐日曲线 |
| 诊断 | 在线状态、故障告警、一键刷新、下载诊断信息 |
| 多账号 | 支持添加多个华帝账号，实体与设备互不冲突 |
| 自动重认证 | 登录失效时 HA 自动弹出重新认证，实体不丢失 |

---

## 支持的机型

| 机型 | 产品 ID | 状态 |
|---|---|---|
| 燃气恒温热水器 | `GH*`（如 GH000174） | ✅ 真机验证 |
| 零冷水燃气热水器 | `GH000190` / `GH000191` | ⚠️ 按抓包实现，未真机验证 |
| 零冷水 i12571 系列 | 型号含 `12571`（如 `i 12571b-16`） | ⚠️ 零冷水/瀑布浴位号沿用同物模型，其余待标定 |
| 电热水器 | `DR*` | ⚠️ 按抓包实现，未真机验证 |

非热水器设备（灶具、油烟机、集成厨电）会被自动跳过。

如果控制方向相反或某个开关无效，多半是位号/字段与你的固件不同，改 `custom_components/vatti_water_heater/specs.py` 里对应机型即可，不需要动其它代码。

---

## 安装

### 方式一：HACS（推荐）

1. HACS → 集成 → 右上角三个点 → **自定义仓库**
2. 仓库地址填本项目的 GitHub 地址，类别选 **Integration**
3. 搜索 “Vatti 华帝热水器” 下载，重启 Home Assistant

### 方式二：手动

1. 把 `custom_components/vatti_water_heater` 整个目录复制到 HA 配置目录的 `custom_components/` 下
2. 目录名必须是 `vatti_water_heater`（全小写）
3. 重启 Home Assistant

目录结构应为：

```
<HA配置目录>/custom_components/vatti_water_heater/
├── __init__.py
├── manifest.json
├── water_heater.py
├── sensor.py
├── switch.py
├── ...
└── translations/
```

---

## 添加集成

**设置 → 设备与服务 → 添加集成 → 搜索 “Vatti 华帝热水器”**

1. **手机号**：填华帝智慧家 App 注册的号码
2. **滑块验证**：点配置页里的链接，在新标签页完成阿里云盾滑块。完成后票据会自动回传，回到配置页直接提交。若自动回传失败，把页面上的票据文本粘贴到输入框
3. **短信验证码**：输入手机收到的 6 位验证码
4. **选择家庭**：账号下有多个家庭时出现，只有一个会自动跳过

> 滑块页挂在 HA 自己的 HTTP 端口下（`/api/vatti_water_heater_captcha/`），浏览器能打开 HA 就能打开它；滑块组件本身需要浏览器能访问外网。

### 强烈建议：给 HA 单独开一个账号

华帝云的登录 token 是**单点生效**的：同一账号在 HA 登录后，手机 App 会被顶下线；手机再登录，HA 的 token 就失效。

正确做法：

1. 用另一个手机号注册一个华帝账号
2. 在 App 里把热水器**共享**给这个新账号（家庭成员 / 设备共享）
3. HA 绑定新账号

这样手机和 HA 各用各的，互不影响。

---

## 实体一览

以设备名「厨房热水器」为例：

| 实体 | 类型 | 说明 |
|---|---|---|
| `water_heater.kitchen_heater` | 热水器 | 开关、目标温度、当前水温、运行模式 |
| `sensor.kitchen_heater_outlet_temperature` | 传感器 | 出水温度 |
| `sensor.kitchen_heater_inlet_temperature` | 传感器 | 进水温度 |
| `sensor.kitchen_heater_water_flow` | 传感器 | 水流量 L/min |
| `sensor.kitchen_heater_wifi_signal` | 诊断 | WiFi 信号 % |
| `sensor.kitchen_heater_fault_code` | 诊断 | 故障码（正常时为空） |
| `sensor.kitchen_heater_last_reported` | 诊断 | 设备最后一次上报时间 |
| `sensor.kitchen_heater_gas_today` | 传感器 | 今日用气量 m³ |
| `sensor.kitchen_heater_gas_this_week` | 传感器 | 本周用气量 m³（属性含逐日曲线） |
| `sensor.kitchen_heater_gas_this_year` | 传感器 | 年度用气量 m³ |
| `sensor.kitchen_heater_water_today` | 传感器 | 今日用水量 m³ |
| `sensor.kitchen_heater_water_this_week` | 传感器 | 本周用水量 m³ |
| `sensor.kitchen_heater_water_this_year` | 传感器 | 年度用水量 m³ |
| `switch.kitchen_heater_one_key_preheat` | 开关 | 一键预热 |
| `switch.kitchen_heater_waterfall_bath` | 开关 | 瀑布浴 |
| `switch.kitchen_heater_eco_wash` | 开关 | 节能洗（与一键增容互斥） |
| `switch.kitchen_heater_capacity_boost` | 开关 | 一键增容（与节能洗互斥） |
| `switch.kitchen_heater_constant_temperature` | 开关 | 循环恒温 |
| `binary_sensor.kitchen_heater_online` | 诊断 | 设备在线 |
| `binary_sensor.kitchen_heater_problem` | 告警 | 故障告警 |
| `button.kitchen_heater_refresh_now` | 诊断 | 立即刷新一次状态 |

实体 ID 由设备名生成，实际以你 HA 里显示的为准。

**关于“点了按钮界面先变、两秒后又变回去”**：控制指令下发后集成会先乐观更新界面，2 秒后再按设备真实上报校正。如果设备离线或没执行，界面会回到真实状态——这是刻意设计，避免“点了没反应”的错觉。

---

## 自动化示例

### 下班前预热

```yaml
automation:
  - alias: 下班前预热热水器
    triggers:
      - trigger: time
        at: "17:30:00"
    conditions:
      - condition: state
        entity_id: binary_sensor.kitchen_heater_online
        state: "on"
    actions:
      - action: water_heater.turn_on
        target:
          entity_id: water_heater.kitchen_heater
      - action: water_heater.set_temperature
        target:
          entity_id: water_heater.kitchen_heater
        data:
          temperature: 45
```

### 故障推送

```yaml
automation:
  - alias: 热水器故障提醒
    triggers:
      - trigger: state
        entity_id: binary_sensor.kitchen_heater_problem
        to: "on"
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: 热水器告警
          message: "故障码：{{ states('sensor.kitchen_heater_fault_code') }}"
```

### 洗澡模式一键切换

```yaml
script:
  bath_time:
    alias: 洗澡模式
    sequence:
      - action: water_heater.set_operation_mode
        target:
          entity_id: water_heater.kitchen_heater
        data:
          operation_mode: AI智洗
      - action: water_heater.set_temperature
        target:
          entity_id: water_heater.kitchen_heater
        data:
          temperature: 42
```

### 仪表盘卡片

```yaml
type: entities
title: 热水器
entities:
  - entity: water_heater.kitchen_heater
  - entity: sensor.kitchen_heater_outlet_temperature
  - entity: sensor.kitchen_heater_water_flow
  - entity: switch.kitchen_heater_one_key_preheat
  - entity: binary_sensor.kitchen_heater_problem
```

---

## 服务

| 服务 | 作用 |
|---|---|
| `vatti_water_heater.refresh` | 立刻拉取所有设备状态，不等下一个轮询周期 |
| `vatti_water_heater.snapshot` | 记录一次原始属性快照（不改设备），用于对比 |
| `vatti_water_heater.diff_snapshot` | 与上次快照对比，指出变化的字段与翻转的位号 |
| `vatti_water_heater.watch` | 连续监听若干分钟，记录每次变化的相对时间 |
| `vatti_water_heater.watch_report` | 查看当前/上一次监听结果 |

开发者工具 → 服务 → 选服务 → 调用即可。后两个是给「功能位号对不上」时现场定位用的，见下节。

---

## 零冷水（即开即热）怎么接

零冷水不是软件开关，它靠机器里的**循环泵**把管路里的冷水抽回去重新加热。所以先分两步看：

**第一步：确认机器支持**

在华帝智慧家 App 里打开这台热水器，看有没有「零冷水 / 预热 / 循环 / 即开即热」入口。

- 有 → 机器带循环泵，HA 里可以控
- 没有 → 硬件不支持，HA 也变不出来。这种情况只能靠「提前开机 + 放水等待」，或者装外置回水泵

**第二步：确认走哪种控制方式**

App 的零冷水页面通常会长这样，不同机型差别很大：

| App 里的形态 | 云端表现 | HA 侧能否控制 |
|---|---|---|
| 一个「预热 / 零冷水」开关 | 物模型某个位翻转 | ✅ 能，做成开关实体 |
| 单次预热（点一下跑一轮） | 同上，但设备跑完会自己复位 | ✅ 能，做成 button 更合适 |
| 定时巡航（工作日 7:00–9:00） | 多半是独立接口，不在物模型里 | ⚠️ 用 HA 自动化替代 |
| 水控 / 点动（开龙头触发） | 纯硬件行为 | ❌ 抓不到，只能间接感知 |

### 方式 A：先试现成的开关（1 分钟）

已识别为零冷水机型（`GH000190` / `GH000191`，或品类名含「零冷水」）时，会生成这几个开关：

`switch.*_quick_heat`、`switch.*_comfort_bath`、`switch.*_boost`、`switch.*_bathtub`、`switch.*_ai_wash`、`switch.*_waterfall`

逐个点一下，同时盯着 App 的零冷水页面看有没有跟着变。哪个对上了，那个就是零冷水位——名字不重要，把它的字段和位号记下来即可。

> 这些位号是按抓包推的，未做真机验证。点错了只会打开别的功能（瀑布浴之类），不会损坏设备，大胆试。

### 方式 B：连续监听（一次点完所有功能，最省事）

机器上功能多的时候（i12571 有零冷水、点动循环、瀑布浴、AI 智洗、全水路自清洁五项），
逐个 `snapshot` → 操作 → `diff_snapshot` 太累。用监听一次做完：

1. **开发者工具 → 服务** → `vatti_water_heater.watch` → 调用（默认监听 300 秒，6 秒采样一次）
2. 拿手机，在 App 上**从上到下依次**点开每个功能，每点一个停 15 秒左右
3. 5 分钟后自动结束，HA 弹出结果通知；中途想看进度就调 `watch_report`

输出长这样，时间轴和你的操作顺序一一对应：

```
厨房热水器（GH000190） 已结束 · 已 300 秒 · 4 次变化

| 相对时间 | 字段         | 之前 | 现在 | 翻转位 |
| +12.5s  | func_switch  | 0    | 8    | bit3   |
| +48.0s  | func_switch  | 8    | 40   | bit5   |
| +95.3s  | func_swit1   | 0    | 2    | bit1   |
```

对照你点的顺序，就知道「零冷水 = func_switch bit3」「瀑布浴 = func_switch bit5」等等。

### 方式 B2：单点对比（只想确认一个功能）

不用猜，直接对比「操作前」和「操作后」的原始属性：

1. **开发者工具 → 服务** → `vatti_water_heater.snapshot` → 调用（`device` 留空表示全部设备）
2. 打开手机 App，点一次「零冷水 / 预热」，等 10 秒
3. 回到 HA，调用 `vatti_water_heater.diff_snapshot`

HA 会弹出一条通知，长得像这样：

```
**厨房热水器**（GH000190）  `15:30:12` → `15:31:20`

| 字段 | 之前 | 现在 | 翻转位 |
| --- | --- | --- | --- |
| func_switch | 8 | 10 | bit1 |

把翻转的那一位填进 specs.py 即可生成开关：

SwitchSpec("new_func_switch_bit1", "func_switch", 1, "mdi:water-sync"),
```

**一个字段都没变**的话，说明该功能不走物模型（表格里第 3、4 行），继续看下面的替代方案。

### 方式 C：改 specs.py 落地

打开 `custom_components/vatti_water_heater/specs.py`，把探针给出的那行填进 `ZERO_COLD_SWITCHES`，起个看得懂的名字：

```python
ZERO_COLD_SWITCHES = (
    SwitchSpec("zero_cold", "func_switch", 1, "mdi:water-sync"),   # ← 新增
    SwitchSpec("quick_heat", "func_switch", 1, "mdi:flash"),
    ...
)
```

再到 `translations/zh-Hans.json` 的 `entity.switch` 里加一个名字：

```json
"zero_cold": { "name": "零冷水" }
```

重启 HA，`switch.厨房热水器_zero_cold` 就出现了。

如果它是「点一下跑一轮、自己复位」的类型，用 `button` 比 `switch` 更贴切：把 `SwitchSpec` 换到 `button.py` 的按钮表里，调用 `async_send_command` 下发同样的位即可。

### 方式 D：定时巡航用 HA 自动化替代

云端没开放定时的话，用 HA 自己排班，效果几乎一样——到点开预热，跑够时间关掉：

```yaml
automation:
  - alias: 早高峰零冷水
    triggers:
      - trigger: time
        at: "06:50:00"
    conditions:
      - condition: state
        entity_id: binary_sensor.kitchen_heater_online
        state: "on"
    actions:
      - action: switch.turn_on
        target:
          entity_id: switch.kitchen_heater_zero_cold
      - delay: "00:20:00"
      - action: switch.turn_off
        target:
          entity_id: switch.kitchen_heater_zero_cold
```

配合「人在传感器 / 门锁 / 手机到家」触发更省气：

```yaml
    triggers:
      - trigger: state
        entity_id: person.me
        to: home
```

---

## 选项

**设置 → 设备与服务 → 集成 → 华帝热水器 → 配置**

| 选项 | 默认 | 说明 |
|---|---|---|
| 状态刷新间隔 | 15 秒 | 5–300 秒。越短越及时，云端请求也越多 |
| 机型识别 | 自动 | 自动按 productId/品类推断；零冷水机型若没被认出，可手动指定 |
| 启用用气/用水统计 | 开 | 关闭后不再请求能耗接口，也不生成能耗实体 |
| 家庭 | 自动 | 多家庭账号可切换，切换后自动重载 |

能耗数据变化慢，固定每 10 分钟刷新一次，不受状态轮询间隔影响。

---

## 目录之外的配套

- `tests/`：57 个单元与集成测试（签名、解析、能耗、API、配置流程、实体与控制、位域探针）
- `.github/workflows/tests.yml`：GitHub Actions 自动跑测试
- `vatti_water_heater.zip`：手动安装包，解压后把 `custom_components/vatti_water_heater` 放进 HA 配置目录即可

## 常见问题

**Q：手机 App 总是被踢下线？**
华帝云 token 单点生效。按上文「给 HA 单独开一个账号」处理，不要和手机共用。

**Q：提示“登录已失效”怎么办？**
HA 会自动弹出重新认证流程，重新走一遍滑块 + 验证码即可，实体和历史数据都不会丢。

**Q：滑块页打不开 / 一直转圈？**
- 用 HA 的内网地址打开，不要用 `127.0.0.1`
- 浏览器需要能访问外网（滑块 SDK 从阿里云盾加载）
- 反向代理场景确认 `/api/vatti_water_heater_captcha/` 没被拦截
- 华帝若更换滑块参数，可在链接后加 `?captchaId=xxx` 覆盖

**Q：控制没反应？**
1. 看 `binary_sensor.*_online` 是否在线
2. 看日志里是否有 `设备离线，指令未送达`
3. 设备在线但仍无效：可能是位号不同，改 `specs.py`

**Q：零冷水开关点了没反应？**
先确认机器带循环泵（App 里有没有「零冷水 / 预热」入口），再用 `snapshot` + `diff_snapshot` 对比 App 操作的位号。详见上文「零冷水（即开即热）怎么接」。

**Q：温度只能设到 35–60？**
这是燃气恒温机的硬件范围。电热水器是 30–75，程序按机型自动切换，不要强行下发超范围值。

**Q：实体显示不可用？**
协调器连续拉取失败会指数退避（15→30→60→120 秒）。检查 HA 出网、华帝云状态，或调用 `vatti_water_heater.refresh` 手动重试。

**Q：数据看起来是旧的？**
华帝云端快照里有不少字段是几天前的缓存。集成以设备上报时间为准，`sensor.*_last_reported` 可以看到真实新鲜度。能耗数据本身按天聚合，属于正常延迟。

---

## 工作原理（给想改代码的人）

### 接口

- 基址：`https://api.vcoo.cloud`，全部 `POST + JSON`
- 请求体固定带 `accessKeyId` / `accessToken` / `timestamp`（毫秒字符串）
- 签名在请求头 `sign`：`md5(按键字典序拼接 "k=v&" + SECRET)`
- 登录后业务接口额外带请求头 `accesstoken`
- 响应 `{"code": 200, "data": ...}`，非 200 抛业务异常

关键端点：

| 端点 | 用途 |
|---|---|
| `/api/app/v1/user/verification/code` | 带滑块票据发送短信 |
| `/api/app/v1/user/login/code` | 短信验证码登录 |
| `/api/app/v1/family/list` | 家庭列表 |
| `/api/app/v1/device/list` | 设备列表 |
| `/api/app/v1/device/property/status` | 物模型属性快照 |
| `/api/app/v1/device/rrpc` | 下发控制（属性键值） |
| `/api/app/v1/device/queryGh00SmartAdjTemp` | 查询智慧云感温 |
| `/api/app/v1/device/saveGh00SmartAdjTemp` | 开关智慧云感温 |
| `/ecm/getNewWaterGas` | 用气/用水统计（另一套签名 + Bearer） |

### 燃气机位域（GH000174 实测）

| 功能 | 字段 | 位 | 开 | 关 |
|---|---|---|---|---|
| 一键预热 | `func_switch` | 3 | +8 | -8 |
| 瀑布浴 | `func_switch` | 5 | +32 | -32 |
| 节能洗 | `func_swit1` | 3 | +8 | -8 |
| AI 智洗 | `func_swit1` | 5 | +32 | -32 |
| 一键增容 | `func_swit2` | 2 | +4 | -4 |
| 循环恒温 | `func_swit2` | 3 | +8 | -8 |

位域是**整值读改写**：例如当前 `func_switch=8`，打开瀑布浴要下发 `40`，不能只发 `32`，否则会把一键预热关掉。节能洗与一键增容互斥，打开一个时会在同一条指令里清掉对方。

### 目录

```
custom_components/vatti_water_heater/
├── __init__.py          # 条目生命周期
├── api.py               # 云端客户端
├── signing.py           # 两套签名算法
├── coordinator.py       # 轮询、乐观更新、能耗调度
├── config_flow.py       # 添加 / 重认证 / 选项
├── captcha.py           # 滑块页托管与票据回收
├── specs.py             # 机型能力表（改这里适配新机型）
├── water_heater.py      # 主实体
├── sensor.py / switch.py / binary_sensor.py / button.py
├── energy.py            # 能耗解析（纯函数）
├── diagnostics.py
└── translations/
```

---

## 开发与测试

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

测试覆盖签名、物模型解析、能耗口径、API 请求结构、配置流程、实体创建与位运算控制。测试依赖 `pytest-homeassistant-custom-component`，它会锁定一个 HA 版本。

本地调试可以把仓库软链到 HA 配置目录：

```bash
ln -s "$PWD/custom_components/vatti_water_heater" \
      /path/to/ha/config/custom_components/vatti_water_heater
```

---

## 免责声明

- 本项目与华帝股份有限公司无关联，使用非官方接口，存在因云端变更而失效的风险
- 账号、设备数据均在华帝云与本机之间传输，集成不上传任何数据到第三方
- 请勿将本项目用于商业用途；由此产生的账号风险、设备异常请自行承担

## 致谢

- 协议细节（GH000174 的位域标定、能耗接口口径）参考并复核自社区项目 [cdcp998/Vatti-Smart-Ha](https://github.com/cdcp998/Vatti-Smart-Ha)（MIT）
- 滑块验证页使用阿里云盾官方 GT4 加载器 `ct4.js`

## License

MIT
