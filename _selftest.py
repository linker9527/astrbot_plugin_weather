"""Self-test for the astrbot_plugin_weather plugin.

Stubs the astrbot API so main.py can be imported outside AstrBot, then exercises
the formatting, URL building, commands, LLM tools and PNG path against the real
wttr.in service. Run: python _selftest.py
"""

import asyncio
import json
import sys
import types

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---- stub the astrbot package -------------------------------------------------
astrbot = types.ModuleType("astrbot")
api = types.ModuleType("astrbot.api")
star = types.ModuleType("astrbot.api.star")
event_mod = types.ModuleType("astrbot.api.event")
components = types.ModuleType("astrbot.api.message_components")
all_mod = types.ModuleType("astrbot.api.all")


class _Logger:
    def warning(self, msg):
        print("  [warn]", msg)

    def info(self, msg):
        print("  [info]", msg)

    def error(self, msg):
        print("  [error]", msg)


api.logger = _Logger()


class Context:
    pass


class Star:
    def __init__(self, context):
        self.context = context


def register(*args, **kwargs):
    def deco(cls):
        cls._register_args = args
        return cls

    return deco


star.Context = Context
star.Star = Star
star.register = register


def _decorator(*args, **kwargs):
    def deco(fn):
        fn._filter = (args, kwargs)
        return fn

    return deco


class _Filter(types.ModuleType):
    def __getattr__(self, name):
        return _decorator


filter = _Filter("astrbot.api.event.filter")
filter.command = _decorator
filter.llm_tool = _decorator


class AstrMessageEvent:
    """模拟真实 AstrBot 命令解析器：只把第一个 token 填进 location 参数。

    真实 command.py 的 validate_and_convert_params 只遍历 handler_params，
    多余 token 被静默丢弃。之前 stub 把整串塞进去，正是 B1/B2 漏测的根因。
    """

    def __init__(self, text=""):
        self.message_str = text
        parts = text.strip().split()
        # 剥掉命令名后的第一个 token，就是 AstrBot 实际传给 location 的值
        rest = (
            parts[1:]
            if parts
            and parts[0].lstrip("/").lower()
            in (
                "weather",
                "天气",
                "tianqi",
                "wttr",
                "forecast",
                "天气预报",
                "预报",
            )
            else parts
        )
        self.first_token = rest[0] if rest else ""

    def plain_result(self, text):
        return ("plain", text)

    def chain_result(self, chain):
        return ("chain", chain)


event_mod.filter = filter
event_mod.AstrMessageEvent = AstrMessageEvent


class Plain:
    def __init__(self, text):
        self.text = text


class Image:
    def __init__(self, file=None, **kwargs):
        self.file = file

    @staticmethod
    def fromBytes(bs):
        return Image(file="base64://" + __import__("base64").b64encode(bs).decode())


components.Plain = Plain
components.Image = Image


def llm_tool(*args, **kwargs):
    return _decorator(*args, **kwargs)


all_mod.llm_tool = llm_tool

# ---- stub mcp.types（真实 AstrBot 自带；此处仅用于验证工具返回结构）----
mcp = types.ModuleType("mcp")
mcp_types = types.ModuleType("mcp.types")


class _TextContent:
    def __init__(self, type=None, text=None, **kwargs):
        self.type = type
        self.text = text


class _ImageContent:
    def __init__(self, type=None, data=None, mimeType=None, **kwargs):
        self.type = type
        self.data = data
        self.mimeType = mimeType


class _CallToolResult:
    def __init__(self, content=None, **kwargs):
        self.content = content or []


mcp_types.TextContent = _TextContent
mcp_types.ImageContent = _ImageContent
mcp_types.CallToolResult = _CallToolResult
mcp.types = mcp_types
sys.modules["mcp"] = mcp
sys.modules["mcp.types"] = mcp_types

sys.modules["astrbot"] = astrbot
sys.modules["astrbot.api"] = api
sys.modules["astrbot.api.star"] = star
sys.modules["astrbot.api.event"] = event_mod
sys.modules["astrbot.api.message_components"] = components
sys.modules["astrbot.api.all"] = all_mod

import main

# ---- helpers -----------------------------------------------------------------
PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(
        ("  PASS " if cond else "  FAIL ") + label + (f" :: {detail}" if detail else "")
    )


async def collect(agen):
    return [x async for x in agen]


def text_of(results):
    return "\n".join(r[1] for r in results if r[0] == "plain")


with open("metadata.yaml", encoding="utf-8") as f:
    META = f.read()
with open("_conf_schema.json", encoding="utf-8") as f:
    SCHEMA = json.load(f)
with open("README.md", encoding="utf-8") as f:
    README = f.read()


async def run():
    print("== static ==")
    # metadata / schema consistency
    meta, schema = META, SCHEMA
    check("metadata name", "name: astrbot_plugin_weather" in meta)
    check("display_name", "display_name: 天气查询" in meta)
    check("author", "author: linker9527" in meta)
    check(
        "repo",
        "repo: https://github.com/linker9527/astrbot_plugin_weather" in meta,
    )
    check("register author", main.WeatherPlugin._register_args[1] == "linker9527")
    check("metadata version", "version: 1.2.2" in meta)
    check(
        "N7 astrbot_version 门槛",
        'astrbot_version: ">=4.22.0,<5"' in meta,
    )
    check(
        "N2 schema hint 列全三个工具",
        all(
            n in schema["enable_llm_tools"]["hint"]
            for n in ("getweather", "getweatheroneline", "getweatherimage")
        ),
    )
    check(
        "N2 已删除不消耗 token 说法",
        "不消耗 token" not in README
        and "不消耗 token" not in schema["enable_llm_tools"]["hint"],
    )
    check(
        "N2 兼容性说明",
        ">=4.22.0" in README and "4.22.0+" in README,
    )
    check(
        "Q1/Q2 文档措辞已修正",
        "版本门槛已保证 mcp 存在" in README
        and "旧版无法安装" in README
        and "旧版缺该依赖时自动降级" not in README,
    )
    check(
        "Q4 schema language 补 zh-cn / zh-tw",
        "zh-cn" in schema["language"]["options"]
        and "zh-tw" in schema["language"]["options"],
    )
    check(
        "N5 README 有 /forecast 表格行",
        "| `/forecast 北京`" in README,
    )
    check(
        "README 标注最高精度街道/社区级（虚构示例）",
        "最高精度：街道 / 社区级" in README
        and "演示用虚构写法" in README
        and "不是「输路名就精准定位」" in README,
    )
    check(
        "README 不残留真实地址示例",
        all(
            s not in README
            for s in (
                "沙河街道",
                "福中社区",
                "上海市黄浦区南京东路",
                "深圳市福田区深南大道",
                "山东菏泽",
                "22.5442673",
                "Avenue Anatole France",
            )
        ),
    )
    check(
        "README 含「只写城市+路名会偏」的示意反例",
        "仍可能偏" in README and "外省同名路" in README,
    )
    check(
        "README 坐标/邮编为示意占位",
        "示意）" in README and "31.23,121.47" not in README and "518000" not in README,
    )
    check(
        "更新日志 v1.2.2 措辞",
        "### v1.2.2" in README and "添加天气图审阅工具并修复已知bug" in README,
    )
    check(
        "保留 v1.2.1 历史日志", "### v1.2.1" in README and "修复部分已知bug" in README
    )
    check(
        "description 突出免费",
        "description: 免费天气查询" in meta and "无需 API Key" in meta,
    )
    check(
        "short_desc 突出免费+免API Key+免注册",
        "short_desc: 用 wttr.in 免费查天气" in meta and "免 API Key、免注册" in meta,
    )
    check(
        "短长简介不含 Markdown 星号",
        "short_desc: *" not in meta and "description: *" not in meta,
    )
    check(
        "schema 结构有效（顶层为对象且每项含合法 type）",
        isinstance(schema, dict)
        and len(schema) > 0
        and all(
            isinstance(v, dict)
            and v.get("type")
            in (
                "string",
                "text",
                "int",
                "float",
                "bool",
                "object",
                "list",
                "dict",
                "template_list",
                "file",
            )
            for v in schema.values()
        ),
    )
    check(
        "schema has all cfg keys",
        all(
            k in schema
            for k in (
                "default_location",
                "units",
                "language",
                "forecast_days",
                "enable_llm_tools",
                "timeout",
            )
        ),
    )
    check(
        "schema options contain defaults",
        all(
            schema[k].get("default")
            in schema[k].get("options", [schema[k].get("default")])
            for k in ("units", "language")
        ),
    )
    # register / decorators
    check(
        "register args",
        main.WeatherPlugin._register_args[0] == "astrbot_plugin_weather",
    )
    check("register version", main.WeatherPlugin._register_args[3] == "1.2.2")
    handlers = [
        "cmd_weather",
        "cmd_forecast",
        "tool_get_weather",
        "tool_oneline",
        "tool_image",
    ]
    for name in handlers:
        fn = getattr(main.WeatherPlugin, name)
        check(f"handler exists: {name}", callable(fn))
        check(f"handler decorated: {name}", hasattr(fn, "_filter"))
    check(
        "commands have aliases",
        all(
            getattr(main.WeatherPlugin, n)._filter[1].get("alias")
            for n in ("cmd_weather", "cmd_forecast")
        ),
    )
    check(
        "only two command handlers",
        len(
            [
                n
                for n in dir(main.WeatherPlugin)
                if hasattr(getattr(main.WeatherPlugin, n), "_filter")
                and getattr(main.WeatherPlugin, n)._filter[0]
            ]
        )
        == 2,
    )
    # 子命令解析：(模式, 地点, 天数)
    P = main.WeatherPlugin
    check("parse empty", P._parse_args(AstrMessageEvent("/weather")) == ("", "", 0))
    check(
        "parse city only",
        P._parse_args(AstrMessageEvent("/weather 上海")) == ("", "上海", 0),
    )
    check(
        "parse now + city",
        P._parse_args(AstrMessageEvent("/weather now 上海")) == ("now", "上海", 0),
    )
    check(
        "parse now + spaced city",
        P._parse_args(AstrMessageEvent("/weather now Salt Lake City"))
        == ("now", "Salt Lake City", 0),
    )
    check(
        "parse forecast + city",
        P._parse_args(AstrMessageEvent("/weather forecast 北京"))
        == ("forecast", "北京", 0),
    )
    # Q3：多写模式词时，后续模式词从地点里剔除，不再当成地点的一部分
    check(
        "Q3 now img 上海 -> 地点只剩上海",
        P._parse_args(AstrMessageEvent("/weather now img 上海")) == ("now", "上海", 0),
    )
    check(
        "Q3 上海 2 now -> 模式now 天数2 地点上海",
        P._parse_args(AstrMessageEvent("/weather 上海 2 now")) == ("now", "上海", 2),
    )
    check(
        "Q3 天数在中间 2 上海 -> 天数2 地点上海",
        P._parse_args(AstrMessageEvent("/weather 2 上海")) == ("", "上海", 2),
    )
    check(
        "Q3 forecast 北京 img -> 地点北京 模式forecast",
        P._parse_args(AstrMessageEvent("/weather forecast 北京 img"))
        == ("forecast", "北京", 0),
    )
    check(
        "天数任意位置不误判邮编",
        P._parse_args(AstrMessageEvent("/weather 94107 2")) == ("", "94107", 2),
    )
    check(
        "parse pic + city",
        P._parse_args(AstrMessageEvent("/weather pic muc")) == ("pic", "muc", 0),
    )
    check(
        "parse help",
        P._parse_args(AstrMessageEvent("/weather help")) == ("help", "", 0),
    )
    check(
        "parse 帮助",
        P._parse_args(AstrMessageEvent("/weather 帮助")) == ("help", "", 0),
    )
    check(
        "parse alias 天气",
        P._parse_args(AstrMessageEvent("/天气 now 上海")) == ("now", "上海", 0),
    )
    check(
        "parse /forecast",
        P._parse_args(AstrMessageEvent("/forecast 北京")) == ("", "北京", 0),
    )
    # 地点在前、参数在后（用户要求的语法）
    check(
        "parse city + img",
        P._parse_args(AstrMessageEvent("/weather 上海 img")) == ("pic", "上海", 0),
    )
    check(
        "parse city + 图片",
        P._parse_args(AstrMessageEvent("/weather 上海 图片")) == ("pic", "上海", 0),
    )
    check(
        "parse city + now",
        P._parse_args(AstrMessageEvent("/weather 上海 now")) == ("now", "上海", 0),
    )
    check(
        "parse city + forecast",
        P._parse_args(AstrMessageEvent("/weather 上海 forecast"))
        == ("forecast", "上海", 0),
    )
    check(
        "parse spaced city + 图片",
        P._parse_args(AstrMessageEvent("/weather Salt Lake City 图片"))
        == ("pic", "Salt Lake City", 0),
    )
    check(
        "parse param only (default city)",
        P._parse_args(AstrMessageEvent("/weather img")) == ("pic", "", 0),
    )
    check(
        "parse mode alias 速览",
        P._parse_args(AstrMessageEvent("/weather 上海 速览")) == ("now", "上海", 0),
    )
    check(
        "parse mode alias 预报",
        P._parse_args(AstrMessageEvent("/weather 上海 预报"))
        == ("forecast", "上海", 0),
    )
    check(
        "parse mode alias png",
        P._parse_args(AstrMessageEvent("/weather 上海 png")) == ("pic", "上海", 0),
    )
    # 天数：末尾纯数字 1~3
    check(
        "parse 上海 3",
        P._parse_args(AstrMessageEvent("/weather 上海 3")) == ("", "上海", 3),
    )
    check(
        "parse 上海 2",
        P._parse_args(AstrMessageEvent("/weather 上海 2")) == ("", "上海", 2),
    )
    check(
        "parse forecast 北京 3",
        P._parse_args(AstrMessageEvent("/weather forecast 北京 3"))
        == ("forecast", "北京", 3),
    )
    check(
        "parse 3 (default city)",
        P._parse_args(AstrMessageEvent("/weather 3")) == ("", "", 3),
    )
    check(
        "parse 94107 邮编不当天数",
        P._parse_args(AstrMessageEvent("/weather 94107")) == ("", "94107", 0),
    )
    check(
        "parse 5 不当天数",
        P._parse_args(AstrMessageEvent("/weather 上海 5")) == ("", "上海 5", 0),
    )
    # ---- 报告 B3~B8 修复验证 ----
    check(
        "B5 language=en 已映射",
        "lang=en" in main._build_urls("London", "j2", "metric", "en")[0],
    )
    check("B5 en 请求头非中文", main._headers("en")["Accept-Language"].startswith("en"))
    check("B5 zh 请求头仍中文", main._headers("zh")["Accept-Language"].startswith("zh"))
    check("B7 非字符串 location 不崩", main._safe_str(518000) == "518000")
    check(
        "B7 _build_urls 接受数字",
        "/518000?" in main._build_urls(518000, "j2", "metric", "zh")[0],
        main._build_urls(518000, "j2", "metric", "zh")[0],
    )
    check(
        "B7 _png_urls 接受数字", "/518000_m.png" in main._png_urls(518000, "m", "zh")[0]
    )
    # ---- 复查轮 R1/R2/R3 ----
    check(
        "R1 合法 forecast_days 正常",
        main.WeatherPlugin(Context(), {"forecast_days": 2})._forecast_days() == 2,
    )
    check(
        "R1 forecast_days>3 夹到 3",
        main.WeatherPlugin(Context(), {"forecast_days": 10})._forecast_days() == 3,
    )
    check(
        "R1 forecast_days=0 夹到 1",
        main.WeatherPlugin(Context(), {"forecast_days": 0})._forecast_days() == 1,
    )
    check(
        "R1 forecast_days 非法字符串回退 3",
        main.WeatherPlugin(Context(), {"forecast_days": "abc"})._forecast_days() == 3,
    )
    check(
        "R1 forecast_days=None 回退 3",
        main.WeatherPlugin(Context(), {"forecast_days": None})._forecast_days() == 3,
    )
    check(
        "R3 @register repo 指向插件仓库",
        main.WeatherPlugin._register_args[4]
        == "https://github.com/linker9527/astrbot_plugin_weather",
        str(main.WeatherPlugin._register_args[4]),
    )
    p8 = main.WeatherPlugin(Context(), {"timeout": 0})
    check("B8 timeout=0 被夹到 1 秒", p8._timeout(12) == 1.0, f"={p8._timeout(12)}")
    check(
        "B8 非法 timeout 回退默认",
        p8.__class__(Context(), {"timeout": "abc"})._timeout(12) == 12.0,
    )
    fake_imp = {
        "current_condition": [
            {
                "weatherCode": "113",
                "temp_F": "68",
                "FeelsLikeF": "66",
                "humidity": "50",
                "pressureInches": "30",
                "visibilityMiles": "6",
                "precipInches": "0.2",
                "windspeedMiles": "5",
                "uvIndex": "2",
                "winddir16Point": "N",
                "observation_time": "01:00 PM",
            }
        ],
        "weather": [{"mintempF": "50", "maxtempF": "70", "astronomy": [{}]}],
        "nearest_area": [
            {
                "areaName": [{"value": "X"}],
                "region": [{"value": "Y"}],
                "country": [{"value": "Z"}],
            }
        ],
    }
    imp = main._fmt_current(fake_imp, "X", "imperial")
    check(
        "B3 imperial 用英制字段",
        "30 inHg" in imp and "6 mi" in imp and "0.2 in" in imp,
        imp,
    )
    # 修复后格式是「风 {中文方位} {风速}」，不再出现「风 风」或把方向写成「N风」
    check(
        "B3 风向缺失不输出双风",
        "风  5 mph" not in imp and "N风" not in imp and "风  9" not in imp,
        imp.splitlines()[3],
    )
    no_dir = dict(fake_imp["current_condition"][0])
    no_dir.pop("winddir16Point", None)
    imp2 = main._fmt_current(
        {
            "current_condition": [no_dir],
            "weather": fake_imp["weather"],
            "nearest_area": fake_imp["nearest_area"],
        },
        "X",
        "imperial",
    )
    check("B3 无风向字段也不双风", "风  5 mph" not in imp2, imp2.splitlines()[3])
    bad = {
        "weather": [
            {
                "date": "2026-11-07",
                "maxtempC": "9",
                "mintempC": "2",
                "hourly": [
                    {"weatherCode": "113", "chanceofrain": "N/A"},
                    {"weatherCode": "113", "chanceofrain": "50"},
                ],
            }
        ]
    }
    fbt = main._fmt_forecast(bad, "X", "metric", 1)
    check("B4 chanceofrain=N/A 不抛异常", "平均降雨概率 50%" in fbt, fbt)
    # B6：直接调用插件的 _forecast_days() 验证 clamp，不在测试里重写表达式
    p6 = main.WeatherPlugin(Context(), {"forecast_days": 10, "timeout": 12})
    check("B6 _forecast_days 把 10 夹到 3", p6._forecast_days() == 3)
    check(
        "B6 _forecast_days 覆盖 0 / 非法值 / 空值",
        main.WeatherPlugin(Context(), {"forecast_days": 0})._forecast_days() == 1
        and main.WeatherPlugin(Context(), {"forecast_days": "abc"})._forecast_days()
        == 3
        and main.WeatherPlugin(Context(), {"forecast_days": None})._forecast_days()
        == 3,
    )
    # pure helpers
    u1, u2 = main._build_urls("北京", "j2", "metric", "zh")
    check(
        "URL chinese encoded",
        "%E5%8C%97%E4%BA%AC" in u1 and "format=j2" in u1 and "lang=zh" in u1,
    )
    check("URL fallback domain", u2.startswith("https://wttr.is/"))
    check(
        "URL imperial flag",
        "&u" in main._build_urls("London", "j1", "imperial", "en")[0],
    )
    check(
        "URL metric_ms flag",
        "&M" in main._build_urls("London", "j2", "metric_ms", "zh")[0],
    )
    check(
        "B5 URL en 带 lang=en（修复后生效）",
        "lang=en" in main._build_urls("London", "j2", "metric", "en")[0],
    )
    check(
        "URL zh 带 lang=zh",
        "lang=zh" in main._build_urls("London", "j2", "metric", "zh")[0],
    )
    check(
        "PNG option in path",
        main._png_urls("London", "metric", "zh")[0].endswith("/London_m.png"),
    )
    check("PNG lang in path", "_lang=fr" in main._png_urls("London", "metric", "fr")[0])
    # FullAddress（?T1 纯文本地址行）
    t1, t2 = main._build_text_urls("深圳", "metric", "zh")
    check("text URL has T1 + unit + lang", "?T1&m&lang=zh" in t1)
    check("text URL fallback domain", t2.startswith("https://wttr.is/"))
    addr = main._parse_full_address(
        "Weather report: 深圳\n\n"
        "  Clear  +26\n\n"
        "地点: 深圳市, 福田区 (Futian), 深圳市 / Shenzhen, 广东省, 518000, 中国 "
        "[22.5442673,114.0545327]\n"
    )
    check("parse FullAddress zh", "深圳市, 福田区" in addr and "22.5442673" in addr)
    check(
        "parse FullAddress en/fr/ja/ru",
        all(
            "22.5442673"
            in main._parse_full_address(f"{tag}: 深圳市, 中国 [22.5442673,114.0545327]")
            for tag in ("Location", "Emplacement", "Ort", "位置情報", "Местоположение")
        ),
    )
    check(
        "parse FullAddress no coords -> empty",
        main._parse_full_address("Location: no coords here") == "",
    )
    check("parse FullAddress empty -> empty", main._parse_full_address("") == "")
    name, emoji = main._describe("122", "Overcast")
    check("code 122 mapping", name == "阴" and emoji == "☁️")
    check("unknown code falls back", main._describe("999", "Mystery")[0] == "Mystery")
    fake = {
        "current_condition": [
            {
                "weatherCode": "113",
                "temp_C": "20",
                "FeelsLikeC": "19",
                "humidity": "50",
                "pressure": "1010",
                "visibility": "10",
                "winddir16Point": "NNE",
                "windspeedKmph": "9",
                "precipMM": "0.0",
                "uvIndex": "3",
                "observation_time": "01:00 PM",
            }
        ],
        "weather": [
            {
                "mintempC": "12",
                "maxtempC": "22",
                "astronomy": [
                    {
                        "sunrise": "06:00 AM",
                        "sunset": "06:00 PM",
                        "moon_phase": "Waxing Crescent",
                    }
                ],
            }
        ],
        "nearest_area": [
            {
                "areaName": [{"value": "Beijing"}],
                "region": [{"value": "Beijing"}],
                "country": [{"value": "China"}],
            }
        ],
    }
    fmt = main._fmt_current(fake, "Beijing", "metric")
    check(
        "format current has emoji+temp+wind",
        "☀️" in fmt and "20°C" in fmt and "东北偏北 9 km/h" in fmt,
        fmt,
    )
    check("format current has area name", "Beijing, Beijing, China" in fmt)
    check("format current has astronomy", "日出" in fmt and "月相" in fmt)
    custom = "深圳市, 福田区, 广东省, 中国 [22.5442673,114.0545327]"
    check(
        "format current prefers full address",
        custom in main._fmt_current(fake, "Beijing", "metric", custom),
    )
    check(
        "format forecast prefers full address",
        custom in main._fmt_forecast(fake, "Beijing", "metric", 1, custom),
    )
    fc = main._fmt_forecast(
        fake
        | {
            "weather": [
                dict(
                    fake["weather"][0],
                    date="2026-11-07",
                    hourly=[{"weatherCode": "296", "chanceofrain": "50"}],
                )
            ]
        },
        "Beijing",
        "metric",
        1,
    )
    check("format forecast", "未来 1 天" in fc and "小雨" in fc and "50%" in fc)

    print("== live API ==")
    plugin = main.WeatherPlugin(
        Context(),
        {
            "default_location": "Beijing",
            "units": "metric",
            "language": "zh",
            "forecast_days": 3,
            "enable_llm_tools": True,
            "timeout": 15,
        },
    )
    ev = AstrMessageEvent()

    def cmd_weather(text):
        """按真实 AstrBot 调用：location 只收到剥掉命令名后的第一个 token。"""
        e = AstrMessageEvent(text)
        return plugin.cmd_weather(e, e.first_token)

    def cmd_forecast(text):
        e = AstrMessageEvent(text)
        return plugin.cmd_forecast(e, e.first_token)

    out = await collect(cmd_weather("/weather 深圳"))
    t = text_of(out)
    check(
        "/weather 深圳 用完整地址（不再是香港村名）",
        "深圳市" in t and "福田区" in t and "Hong Kong" not in t,
        t[:90].replace("\n", " | "),
    )

    out = await collect(cmd_weather("/weather 北京"))
    t = text_of(out)
    check(
        "/weather 北京 返回实况",
        len(t) > 40 and "数据来源 wttr.in" in t,
        t[:70].replace("\n", " | "),
    )

    out = await collect(cmd_weather("/weather"))
    check(
        "/weather 空参数查默认城市（不是帮助）",
        "数据来源 wttr.in" in text_of(out),
        text_of(out)[:60].replace("\n", " | "),
    )

    out = await collect(cmd_weather("/weather help"))
    check("/weather help 显示帮助", "地点支持" in text_of(out))
    out = await collect(cmd_weather("/weather 帮助"))
    check("/weather 帮助 显示帮助", "地点支持" in text_of(out))

    out = await collect(cmd_weather("/weather 上海 img"))
    chain = [r[1] for r in out if r[0] == "chain"]
    ok = bool(chain) and any(
        getattr(c, "file", "").startswith("base64://") for c in chain[0]
    )
    check("地点在前 + img 发 PNG", ok)

    out = await collect(cmd_weather("/weather 上海 图片"))
    check(
        "地点在前 + 图片 发 PNG",
        any(r[0] == "chain" for r in out),
    )

    out = await collect(cmd_weather("/weather 上海 2"))
    t = text_of(out)
    check(
        "/weather 上海 2 只返回 2 天预报",
        "未来 2 天预报" in t and t.count("平均降雨概率") == 2,
        t[:70].replace("\n", " | "),
    )

    out = await collect(cmd_weather("/weather 上海 3"))
    t = text_of(out)
    check(
        "/weather 上海 3 返回 3 天预报",
        "未来 3 天预报" in t and t.count("平均降雨概率") == 3,
        t[:70].replace("\n", " | "),
    )

    out = await collect(cmd_weather("/weather forecast London"))
    t = text_of(out)
    check(
        "/weather forecast 返回 3 天",
        t.count("2026-") >= 3 or t.count("平均降雨概率") >= 3,
        t[:70].replace("\n", " | "),
    )

    out = await collect(cmd_weather("/weather now Shanghai"))
    t = text_of(out)
    check("/weather now 一行", len(t) < 80 and "°C" in t, t.strip())

    out = await collect(cmd_weather("/weather pic London"))
    chain = [r[1] for r in out if r[0] == "chain"]
    ok = bool(chain) and any(
        getattr(c, "file", "").startswith("base64://") and len(c.file) > 5000
        for c in chain[0]
    )
    check(
        "/weather pic 返回 base64 PNG",
        ok,
        f"components={len(chain[0]) if chain else 0}",
    )

    out = await collect(cmd_forecast("/forecast London"))
    check("/forecast 快捷命令仍可用", "未来 3 天预报" in text_of(out))

    out = await collect(plugin.tool_get_weather(ev, "Beijing", "current"))
    check("llm_tool current", "数据来源 wttr.in" in text_of(out))
    out = await collect(plugin.tool_get_weather(ev, "", "forecast"))
    check("llm_tool forecast uses default city", "未来 3 天预报" in text_of(out))
    out = await collect(plugin.tool_oneline(ev, "muc"))
    check("llm_tool oneline airport code", len(text_of(out)) < 80)

    # 图片工具：返回 CallToolResult 交给 LLM，不直接 yield 到对话
    img_ret = await plugin.tool_image(ev, "London")
    check(
        "getweatherimage 返回 CallToolResult",
        isinstance(img_ret, _CallToolResult),
        type(img_ret).__name__,
    )
    images = (
        [c for c in img_ret.content if c.type == "image"]
        if hasattr(img_ret, "content")
        else []
    )
    texts = (
        [c for c in img_ret.content if c.type == "text"]
        if hasattr(img_ret, "content")
        else []
    )
    check("结果含 1 张 ImageContent", len(images) == 1, f"images={len(images)}")
    check("结果含文本说明", len(texts) == 1 and "London" in texts[0].text)
    if images:
        import base64 as _b64

        raw = _b64.b64decode(images[0].data)
        check(
            "图片是有效 PNG 且体积合理",
            raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) > 5000,
            f"bytes={len(raw)} mime={images[0].mimeType}",
        )
    # 图片工具是协程（return CallToolResult），不是 async generator（不会直接 yield 到对话）
    import inspect

    check(
        "工具为协程函数而非异步生成器",
        inspect.iscoroutinefunction(main.WeatherPlugin.tool_image)
        and not inspect.isasyncgenfunction(main.WeatherPlugin.tool_image),
    )
    check(
        "返回结果含 content 且元素为 Text/Image 内容块",
        hasattr(img_ret, "content")
        and {getattr(c, "type", None) for c in img_ret.content} == {"text", "image"},
    )

    plugin_off = main.WeatherPlugin(
        Context(), {"enable_llm_tools": False, "default_location": "Beijing"}
    )
    out = await collect(plugin_off.tool_get_weather(ev, "Beijing"))
    check("llm_tool disabled gate", "关闭" in text_of(out))
    off_ret = await plugin_off.tool_image(ev, "Beijing")
    check(
        "图片工具关闭开关返回文本",
        isinstance(off_ret, str) and "关闭" in off_ret,
        repr(off_ret),
    )
    bad_ret = await plugin.tool_image(ev, "zzzznotaplace99999")
    check(
        "图片工具失败返回文本而非崩溃",
        isinstance(bad_ret, str) and "失败" in bad_ret,
        repr(bad_ret)[:80],
    )

    out = await collect(cmd_weather("/weather zzzznotaplace99999"))
    check(
        "invalid location handled gracefully", "失败" in text_of(out), text_of(out)[:90]
    )

    # ---- B1/B2 回归：纯模式词 / 多词地点，绝不能静默查到错误城市 ----
    # B1 根因：AstrBot 只给首 token，旧代码 rest or location 会回退成模式词。
    # 直接验证解析结果：纯模式词时 rest 必须为空（于是走 default_location）。
    for text in (
        "/weather img",
        "/weather now",
        "/weather 3",
        "/weather forecast",
        "/weather 图片",
        "/weather 速览",
        "/weather help",
        "/weather 帮助",
    ):
        e = AstrMessageEvent(text)
        mode, rest, days = main.WeatherPlugin._parse_args(e)
        check(
            f"B1 纯模式词 {text} 地点为空（不回退首 token）",
            rest == "",
            f"first_token={e.first_token!r} mode={mode} rest={rest!r} days={days}",
        )
    # B2 根因：cmd_forecast 旧代码直接用首 token。验证多词地点能完整解析。
    _, rest, _ = main.WeatherPlugin._parse_args(
        AstrMessageEvent("/forecast Salt Lake City")
    )
    check("B2 /forecast 多词地点完整保留", rest == "Salt Lake City", f"rest={rest!r}")
    _, rest, _ = main.WeatherPlugin._parse_args(AstrMessageEvent("/天气预报 New York"))
    check("B2 中文别名多词地点完整保留", rest == "New York", f"rest={rest!r}")

    print(f"\n== result: {len(PASS)} passed, {len(FAIL)} failed ==")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run())
