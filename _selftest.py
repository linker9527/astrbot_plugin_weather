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
    def __init__(self, text=""):
        self.text = text
        self.message_str = text

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


async def run():
    print("== static ==")
    # metadata / schema consistency
    meta, schema = META, SCHEMA
    check("metadata name", "name: astrbot_plugin_weather" in meta)
    check("display_name", "display_name: 天气查询" in meta)
    check("metadata version", "version: 1.2.0" in meta)
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
    check("schema json valid", isinstance(schema, dict))
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
    check("register version", main.WeatherPlugin._register_args[3] == "1.2.0")
    handlers = ["cmd_weather", "cmd_forecast", "tool_get_weather", "tool_oneline"]
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
        "URL en has no lang",
        "lang=" not in main._build_urls("London", "j2", "metric", "en")[0],
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
        "☀️" in fmt and "20°C" in fmt and "东北偏北风" in fmt,
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

    out = await collect(plugin.cmd_weather(AstrMessageEvent("/weather 深圳"), "深圳"))
    t = text_of(out)
    check(
        "/weather 深圳 用完整地址（不再是香港村名）",
        "深圳市" in t and "福田区" in t and "Hong Kong" not in t,
        t[:90].replace("\n", " | "),
    )

    out = await collect(plugin.cmd_weather(AstrMessageEvent("/weather 北京"), "北京"))
    t = text_of(out)
    check(
        "/weather 北京 返回实况",
        len(t) > 40 and "数据来源 wttr.in" in t,
        t[:70].replace("\n", " | "),
    )

    out = await collect(plugin.cmd_weather(AstrMessageEvent("/weather"), ""))
    check(
        "/weather 空参数查默认城市（不是帮助）",
        "数据来源 wttr.in" in text_of(out),
        text_of(out)[:60].replace("\n", " | "),
    )

    out = await collect(plugin.cmd_weather(AstrMessageEvent("/weather help"), ""))
    check("/weather help 显示帮助", "地点支持" in text_of(out))
    out = await collect(plugin.cmd_weather(AstrMessageEvent("/weather 帮助"), ""))
    check("/weather 帮助 显示帮助", "地点支持" in text_of(out))

    out = await collect(
        plugin.cmd_weather(AstrMessageEvent("/weather 上海 img"), "上海 img")
    )
    chain = [r[1] for r in out if r[0] == "chain"]
    ok = bool(chain) and any(
        getattr(c, "file", "").startswith("base64://") for c in chain[0]
    )
    check("地点在前 + img 发 PNG", ok)

    out = await collect(
        plugin.cmd_weather(AstrMessageEvent("/weather 上海 图片"), "上海 图片")
    )
    check(
        "地点在前 + 图片 发 PNG",
        any(r[0] == "chain" for r in out),
    )

    out = await collect(
        plugin.cmd_weather(AstrMessageEvent("/weather 上海 2"), "上海 2")
    )
    t = text_of(out)
    check(
        "/weather 上海 2 只返回 2 天预报",
        "未来 2 天预报" in t and t.count("平均降雨概率") == 2,
        t[:70].replace("\n", " | "),
    )

    out = await collect(
        plugin.cmd_weather(AstrMessageEvent("/weather 上海 3"), "上海 3")
    )
    t = text_of(out)
    check(
        "/weather 上海 3 返回 3 天预报",
        "未来 3 天预报" in t and t.count("平均降雨概率") == 3,
        t[:70].replace("\n", " | "),
    )

    out = await collect(
        plugin.cmd_weather(AstrMessageEvent("/weather forecast London"), "London")
    )
    t = text_of(out)
    check(
        "/weather forecast 返回 3 天",
        t.count("2026-") >= 3 or t.count("平均降雨概率") >= 3,
        t[:70].replace("\n", " | "),
    )

    out = await collect(
        plugin.cmd_weather(AstrMessageEvent("/weather now Shanghai"), "Shanghai")
    )
    t = text_of(out)
    check("/weather now 一行", len(t) < 80 and "°C" in t, t.strip())

    out = await collect(
        plugin.cmd_weather(AstrMessageEvent("/weather pic London"), "London")
    )
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

    out = await collect(
        plugin.cmd_forecast(AstrMessageEvent("/forecast London"), "London")
    )
    check("/forecast 快捷命令仍可用", "未来 3 天预报" in text_of(out))

    out = await collect(plugin.tool_get_weather(ev, "Beijing", "current"))
    check("llm_tool current", "数据来源 wttr.in" in text_of(out))
    out = await collect(plugin.tool_get_weather(ev, "", "forecast"))
    check("llm_tool forecast uses default city", "未来 3 天预报" in text_of(out))
    out = await collect(plugin.tool_oneline(ev, "muc"))
    check("llm_tool oneline airport code", len(text_of(out)) < 80)

    plugin_off = main.WeatherPlugin(
        Context(), {"enable_llm_tools": False, "default_location": "Beijing"}
    )
    out = await collect(plugin_off.tool_get_weather(ev, "Beijing"))
    check("llm_tool disabled gate", "关闭" in text_of(out))

    out = await collect(
        plugin.cmd_weather(
            AstrMessageEvent("/weather zzzznotaplace99999"), "zzzznotaplace99999"
        )
    )
    check(
        "invalid location handled gracefully", "失败" in text_of(out), text_of(out)[:90]
    )

    print(f"\n== result: {len(PASS)} passed, {len(FAIL)} failed ==")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run())
