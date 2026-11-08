# astrbot_plugin_weather

基于 [wttr.in](https://github.com/chubin/wttr.in) 的**免费** AstrBot 天气查询插件。免 API Key、免注册、零成本，直接用 wttr.in 的公开服务。

## 安装

把整个 `astrbot_plugin_weather` 目录放进 AstrBot 的 `data/plugins/`，在 WebUI「插件」页重载即可。依赖 `aiohttp`（见 `requirements.txt`）。

> 若发布到插件市场，官方建议目录名以 `astrbot_plugin_` 开头，可自行改名（改名不影响功能）。

## 命令

统一用 `/weather`，**地点在前、参数在后**；参数写在地点前也兼容：

| 命令 | 说明 |
|---|---|
| `/weather` | 查默认城市的当前天气（**不是**帮助） |
| `/weather 上海` | 当前天气实况 |
| `/weather 上海 now` | 一行速览，适合状态栏 |
| `/weather 上海 forecast` | 未来 3 天预报 |
| `/weather 上海 3` | 未来 3 天预报（末尾数字 1~3 指定天数，**上游最多 3 天**） |
| `/weather 上海 img` / `/weather 上海 图片` | wttr.in 的 PNG 天气图 |
| `/weather help` / `/weather 帮助` | 显示帮助（**只有这两个才是帮助**） |

参数也支持写在地点前，例如 `/weather now 上海`、`/weather pic 上海`，两种方式等价。

参数别名：`now`=`速览`/`一行`/`oneline`；`forecast`=`预报`/`多日`；`pic`=`img`/`png`/`图片`/`天气图`；`help`=`帮助`。

命令别名：`/天气`、`/tianqi`、`/wttr`（都走同一入口）；预报另有快捷命令 `/forecast [地点]`（别名 `/天气预报`、`/预报`）。

## 地点怎么写

**`Shenzhen` 这样填就行**，大小写不敏感（`shenzhen` 一样）。也可以填进配置项 `default_location`，之后 `/weather` 不带地点就查该城市。

关于预报天数：wttr.in 的 `format=j1` 固定只返回 **今天 + 后 2 天，共 3 天**，且不支持指定任意日期（实测 `?days=5`、`?date=...`、`地点@日期` 要么 500、要么日期不变 —— `@日期` 只用于月相查询）。因此命令里的天数上限是 3，写 `/weather 上海 5` 会被当成地点的一部分而不是天数。

以下写法均经实测可用（2026-11-07，参考 [wttr.in/:help](https://wttr.in/:help)）：

| 类型 | 示例 | 说明 |
|---|---|---|
| 英文城市名 | `Shenzhen`、`London` | 大小写不敏感 |
| 中文（Unicode） | `深圳`、`北京`、`上海`、`广州`、`成都`、`杭州`、`武汉`、`西安`、`重庆`、`香港`、`台北`、`東京` | 任意语言地名，插件自动做 UTF-8 百分号编码 |
| 拼音 | `Beijing`、`Shanghai`、`Chengdu` | 与中文等价 |
| 带空格 / 地标 | `Salt Lake City`、`New York`、`Eiffel Tower` | 直接写空格，插件编码为 `%20` |
| 机场三字码 | `SZX`、`szx`、`muc` | IATA 代码 |
| 域名 / IP | `@github.com`、`8.8.8.8` | 按域名或 IP 定位 |
| GPS 坐标 | `31.23,121.47`、`-78.46,106.79` | 逗号编码成 `%2C` 实测等价 |
| 邮编 / 区号 | `94107`（美国）、`518000`（深圳） | |
| `~` 前缀 | `~Eiffel Tower` | 等同地标写法 |
| 留空 | — | 用配置里的 `default_location`（默认 `Beijing`）；只有 `/weather help` 或 `/weather 帮助` 才显示帮助 |

两点注意：

- 中文区名或同名城市可能解析到别处。想精确就用 GPS 坐标，或看实况输出第一行 —— 那是 wttr.in 的 `nearest_area` 解析结果。
- 查不到的地点 wttr.in 返回 HTTP 500，插件会主域名 `wttr.in` 和备用域名 `wttr.is` 各试一次，然后回复一句失败提示，不会崩溃或卡住。

## LLM 工具

配置里开启「LLM 天气工具」后，大模型可调用两个工具，用户用自然语言即可问天气：

- `getweather(location, view)` —— `view` 为 `current` 或 `forecast`
- `getweatheroneline(location)` —— 简短一行结果

关闭该开关则纯命令模式，不消耗 token。

## 配置项

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `default_location` | 地点留空时查询的城市 | `Beijing` |
| `units` | `metric` / `imperial` / `metric_ms` | `metric` |
| `language` | 传给 wttr.in 的语言 | `zh` |
| `forecast_days` | 预报天数（1~3） | `3` |
| `enable_llm_tools` | LLM 工具开关 | `true` |
| `use_full_address` | 文字/预报/LLM 用完整地址（见下） | `true` |
| `timeout` | 单次请求超时秒数 | `12` |

## 数据来源与实现说明

- 数据来自 [wttr.in](https://github.com/chubin/wttr.in) 公开的 `format=j1` / `j2` JSON 与 `format=3` 一行格式，备用域名 [wttr.is](https://wttr.is) 自动兜底（两者由同一后端服务）。
- 天气名称与 emoji 映射取自 wttr.in 仓库 `internal/renderer/oneline/constants.go` 的 `WWOCodeToName` / `WeatherSymbol`，在本插件里做了中文化。
- 上游对中文天气描述支持有限（实测 `lang=zh` 仍可能返回英文），因此天气状况以 `weatherCode` 本地映射为准，避免输出英文。
- **完整地址（`use_full_address`）**：JSON 的 `nearest_area` 是天气供应商 WWO 返回的"最近气象站名"，边界城市会偏（实测「深圳」返回 `Ma Tso Lung, Hong Kong`）。wttr.in 渲染 PNG/终端时用的是内部地理编码的 `Location.FullAddress`，该字段不进 JSON，但会出现在 `?T1` 纯文本输出的 `Location:` 行里。因此本插件额外请求一次 `?T1` 抽取完整地址作为标题，取不到则自动回退 `nearest_area`。开启后每次文字查询多一个 HTTP 请求；关闭可省掉它。
- PNG 视图的选项需要拼进 URL 路径（如 `/London_m.png`），而不是查询串；实测 `?`/`&` 形式会返回 500。
- 网络请求使用 `aiohttp`，符合 AstrBot 插件规范；未使用 `requests`。
- 所有持久化数据：无。PNG 以 base64 直接发送，不落盘。

## 许可与致谢

### 插件图标

`logo.png` 来自 [OpenMoji](https://openmoji.org/) 的 [U+1F326 「晴间阵雨」](https://github.com/hfg-gmuend/openmoji/blob/master/color/618x618/1F326.png)，由 OpenMoji 项目以 **CC BY-SA 4.0** 发布（[许可全文](https://github.com/hfg-gmuend/openmoji/blob/master/LICENSE.txt)）。本插件对其做了**居中裁切为正方形并缩放到 256×256**（保留透明背景），未改动图形本身。按 CC BY-SA 4.0 的要求，此处提供署名、原作链接、许可链接与修改说明；若分发本插件的改编版本，图标部分需以 CC BY-SA 4.0 或兼容许可提供。

### 数据来源

wttr.in 以 Apache-2.0 许可发布，本插件只调用其公开 HTTP 接口，未复制其源码；天气代码到中文名称/emoji 的映射关系参考自其源码，已在上方注明出处。

参考文档：

- [wttr.in 仓库](https://github.com/chubin/wttr.in)
- [AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot 插件配置](https://docs.astrbot.app/dev/star/guides/plugin-config.html)
