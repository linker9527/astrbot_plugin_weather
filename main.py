"""基于 wttr.in 的 AstrBot 天气查询插件。

命令和 LLM 工具共用同一套查询/格式化逻辑；网络请求只走 aiohttp。
"""

import asyncio
import base64
import re
import urllib.parse

import aiohttp
from astrbot.api import logger
from astrbot.api.all import llm_tool
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, register

# 一次天气查询可能抛出的全部异常，供各处统一兜底；不含 CancelledError。
_QUERY_ERRORS = (
    aiohttp.ClientError,
    asyncio.TimeoutError,
    OSError,
    RuntimeError,
    ValueError,
    KeyError,
    TypeError,
)

# wttr.in 的 WWO 天气代码 → (中文描述, emoji)，来自仓库
# internal/renderer/oneline/constants.go 的 WWOCodeToName / WeatherSymbol
_CODE_INFO = {
    "113": ("晴", "☀️"),
    "116": ("局部多云", "⛅"),
    "119": ("多云", "☁️"),
    "122": ("阴", "☁️"),
    "143": ("雾", "🌫️"),
    "176": ("小阵雨", "🌦️"),
    "179": ("雨夹雪阵雨", "🌧️"),
    "182": ("小雪或雨夹雪", "🌧️"),
    "185": ("小雪或雨夹雪", "🌧️"),
    "200": ("雷阵雨", "⛈️"),
    "227": ("小雪", "🌨️"),
    "230": ("大雪", "❄️"),
    "248": ("雾", "🌫️"),
    "260": ("冻雾", "🌫️"),
    "263": ("小阵雨", "🌦️"),
    "266": ("小雨", "🌦️"),
    "281": ("雨夹雪", "🌧️"),
    "284": ("雨夹雪", "🌧️"),
    "293": ("小雨", "🌦️"),
    "296": ("小雨", "🌦️"),
    "299": ("大阵雨", "🌧️"),
    "302": ("大雨", "🌧️"),
    "305": ("大阵雨", "🌧️"),
    "308": ("大雨", "🌧️"),
    "311": ("小雪或雨夹雪", "🌧️"),
    "314": ("小雪或雨夹雪", "🌧️"),
    "317": ("小雪或雨夹雪", "🌧️"),
    "320": ("小雪", "🌨️"),
    "323": ("小阵雪", "🌨️"),
    "326": ("小阵雪", "🌨️"),
    "329": ("大雪", "❄️"),
    "332": ("大雪", "❄️"),
    "335": ("大阵雪", "❄️"),
    "338": ("大雪", "❄️"),
    "350": ("雨夹雪", "🌧️"),
    "353": ("小阵雨", "🌦️"),
    "356": ("大阵雨", "🌧️"),
    "359": ("大雨", "🌧️"),
    "362": ("雨夹雪阵雨", "🌧️"),
    "365": ("雨夹雪阵雨", "🌧️"),
    "368": ("小阵雪", "🌨️"),
    "371": ("大阵雪", "❄️"),
    "374": ("雨夹雪阵雨", "🌧️"),
    "377": ("雨夹雪", "🌧️"),
    "386": ("雷阵雨", "⛈️"),
    "389": ("雷暴大雨", "🌩️"),
    "392": ("雷雪", "⛈️"),
    "395": ("大阵雪", "❄️"),
}

# 16 方位风向 → 中文，键来自 JSON 的 winddir16Point
_WIND_DIR = {
    "N": "北",
    "NNE": "东北偏北",
    "NE": "东北",
    "ENE": "东北偏东",
    "E": "东",
    "ESE": "东南偏东",
    "SE": "东南",
    "SSE": "东南偏南",
    "S": "南",
    "SSW": "西南偏南",
    "SW": "西南",
    "WSW": "西南偏西",
    "W": "西",
    "WNW": "西北偏西",
    "NW": "西北",
    "NNW": "西北偏北",
}

_UNIT_FLAG = {"metric": "m", "imperial": "u", "metric_ms": "M"}
_LANG = {
    "zh": "zh",
    "zh-cn": "zh",
    "zh-tw": "zh",
    "en": "en",
    "ja": "ja",
    "ko": "ko",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "ru": "ru",
}
# 传给 wttr.in 的 Accept-Language；配置 language 决定它，不再硬编码中文。
_ACCEPT_LANG = {
    "zh": "zh-CN,zh;q=0.9",
    "en": "en-US,en;q=0.9",
    "ja": "ja-JP,ja;q=0.9",
    "ko": "ko-KR,ko;q=0.9",
    "fr": "fr-FR,fr;q=0.9",
    "de": "de-DE,de;q=0.9",
    "es": "es-ES,es;q=0.9",
    "ru": "ru-RU,ru;q=0.9",
}


def _headers(lang):
    lc = (lang or "").strip().lower()
    accept = _ACCEPT_LANG.get(_LANG.get(lc, "zh"), _ACCEPT_LANG["zh"])
    return {"User-Agent": "curl/8.0", "Accept-Language": accept}


def _safe_str(raw):
    """LLM 工具可能传非字符串，统一转成字符串，避免 .strip() 抛 AttributeError。"""
    return str(raw or "").strip()


DEFAULT_LOCATION = "Beijing"

# 命令别名（含 / 前缀由 AstrBot 处理，这里只比对词本身）
_COMMAND_WORDS = {
    "weather",
    "天气",
    "tianqi",
    "wttr",
    "forecast",
    "天气预报",
    "预报",
}
# 模式词：可放在地点前，也可放在地点后
_MODE_WORDS = {
    "now": "now",
    "速览": "now",
    "一行": "now",
    "oneline": "now",
    "forecast": "forecast",
    "预报": "forecast",
    "多日": "forecast",
    "pic": "pic",
    "img": "pic",
    "png": "pic",
    "图片": "pic",
    "天气图": "pic",
    "help": "help",
    "帮助": "help",
}


def _first_value(obj, key, default=""):
    """wttr.in 把很多字段包成 [{"value": "..."}]，取第一个值。"""
    try:
        return obj[key][0]["value"]
    except (KeyError, IndexError, TypeError):
        return default


def _describe(code, upstream_desc):
    name, emoji = _CODE_INFO.get(str(code), (None, "✨"))
    if name is None:
        name = (upstream_desc or "未知天气").strip() or "未知天气"
    return name, emoji


def _loc_name(data, fallback):
    area = (data.get("nearest_area") or [{}])[0]
    parts = [
        _first_value(area, "areaName"),
        _first_value(area, "region"),
        _first_value(area, "country"),
    ]
    name = ", ".join(p for p in parts if p)
    return name or fallback


def _build_text_urls(location, unit, lang):
    """构造用于取 FullAddress 的 ?T1 纯文本 URL（主/备域名各一个）。"""
    loc = urllib.parse.quote(_safe_str(location), safe="+~@")
    query = ["T1"]
    flag = _UNIT_FLAG.get(unit)
    if flag:
        query.append(flag)
    lc = (lang or "").strip().lower()
    if lc in _LANG:
        query.append(f"lang={_LANG[lc]}")
    path = f"/{loc}" if loc else "/"
    suffix = "?" + "&".join(query)
    return (
        f"https://wttr.in{path}{suffix}",
        f"https://wttr.is{path}{suffix}",
    )


# 匹配 ?T 输出里的地址行：标签随 lang 变化，用含坐标的方括号定位更稳。
_FULL_ADDRESS_RE = re.compile(
    r"^\s*\S*:\s*(.+?\[\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*\])\s*$"
)


def _parse_full_address(text):
    for line in (text or "").splitlines():
        m = _FULL_ADDRESS_RE.match(line)
        if m:
            return m.group(1).strip()
    return ""


async def _fetch_full_address(session, location, unit, lang, timeout):
    """从 ?T1 纯文本输出里取 FullAddress；取不到返回空串，由调用方回退。"""
    for url in _build_text_urls(location, unit, lang):
        try:
            async with session.get(
                url,
                headers=_headers(lang),
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    continue
                addr = _parse_full_address(await resp.text())
                if addr:
                    return addr
        except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError) as e:
            logger.warning(f"[astrbot_plugin_weather] 地址解析失败 {url}: {e}")
    return ""


def _build_urls(location, fmt, unit, lang):
    """构造主/备两个 wttr.in 请求 URL。"""
    loc = urllib.parse.quote(_safe_str(location), safe="+~@")
    query = [f"format={fmt}"]
    flag = _UNIT_FLAG.get(unit)
    if flag:
        query.append(flag)
    lc = (lang or "").strip().lower()
    if lc in _LANG:
        query.append(f"lang={_LANG[lc]}")
    path = f"/{loc}" if loc else "/"
    suffix = "?" + "&".join(query) if query else ""
    return (
        f"https://wttr.in{path}{suffix}",
        f"https://wttr.is{path}{suffix}",
    )


async def _fetch_json(session, url, timeout, lang=""):
    async with session.get(
        url, headers=_headers(lang), timeout=aiohttp.ClientTimeout(total=timeout)
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        return await resp.json(content_type=None)


async def _fetch_png(session, url, timeout, lang=""):
    async with session.get(
        url, headers=_headers(lang), timeout=aiohttp.ClientTimeout(total=timeout)
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        ctype = resp.headers.get("Content-Type", "")
        if "image/png" not in ctype:
            raise RuntimeError(f"意外的内容类型: {ctype}")
        return await resp.read()


def _png_urls(location, unit, lang):
    """PNG 视图把选项拼进路径而不是查询串，实测 '?'/'&' 选项会 500。"""
    loc = urllib.parse.quote(_safe_str(location), safe="+~@")
    option = _UNIT_FLAG.get(unit, "m")
    lang_path = (lang or "").strip().lower()
    if lang_path in _LANG and _LANG[lang_path] != "zh":
        option += f"_lang={_LANG[lang_path]}"
    path = f"/{loc}_{option}.png" if loc else f"_{option}.png"
    return f"https://wttr.in{path}", f"https://wttr.is{path}"


def _fmt_current(data, fallback_location, unit, display_name=""):
    cur = (data.get("current_condition") or [{}])[0]
    day = (data.get("weather") or [{}])[0]
    code = str(cur.get("weatherCode", ""))
    desc = _first_value(cur, "weatherDesc")
    name, emoji = _describe(code, desc)
    imperial = unit == "imperial"
    temp = cur.get("temp_F" if imperial else "temp_C", "-")
    feels = cur.get("FeelsLikeF" if imperial else "FeelsLikeC", "-")
    unit_sym = "°F" if imperial else "°C"
    wind = cur.get("windspeedMiles" if imperial else "windspeedKmph", "-")
    wind_unit = "mph" if imperial else "km/h"
    if unit == "metric_ms":
        try:
            wind = f"{int(wind) / 3.6:.1f}"
            wind_unit = "m/s"
        except (TypeError, ValueError):
            wind_unit = "km/h"
    wind_dir = _WIND_DIR.get(
        cur.get("winddir16Point", ""), cur.get("winddir16Point", "")
    ).strip()
    # 缺风向时把「风  9 km/h」压成「风 9 km/h」，避免双空格/双「风」
    wind_phrase = (
        f"风 {wind_dir} {wind} {wind_unit}" if wind_dir else f"风 {wind} {wind_unit}"
    )
    low = day.get("mintempF" if imperial else "mintempC", "-")
    high = day.get("maxtempF" if imperial else "maxtempC", "-")
    astro = (day.get("astronomy") or [{}])[0]

    vis = cur.get("visibilityMiles" if imperial else "visibility", "-")
    vis_unit = "mi" if imperial else "km"
    precip = cur.get("precipInches" if imperial else "precipMM", "-")
    precip_unit = "in" if imperial else "mm"
    pressure = cur.get("pressureInches" if imperial else "pressure", "-")
    pressure_unit = "inHg" if imperial else "hPa"

    place = display_name or _loc_name(data, fallback_location)
    lines = [
        f"{emoji} {place} · {name}",
        f"温度 {temp}{unit_sym}（体感 {feels}{unit_sym}）  今日 {low}~{high}{unit_sym}",
        f"湿度 {cur.get('humidity', '-')}%  气压 {pressure} {pressure_unit}  能见度 {vis} {vis_unit}",
        f"{wind_phrase}  降水 {precip} {precip_unit}  UV {cur.get('uvIndex', '-')}",
    ]
    if astro.get("sunrise"):
        lines.append(
            f"日出 {astro.get('sunrise', '-')}  日落 {astro.get('sunset', '-')}  月相 {astro.get('moon_phase', '-')}"
        )
    lines.append(f"观测时间 {cur.get('observation_time', '-')} · 数据来源 wttr.in")
    return "\n".join(lines)


def _fmt_forecast(data, fallback_location, unit, days, display_name=""):
    imperial = unit == "imperial"
    unit_sym = "°F" if imperial else "°C"
    place = display_name or _loc_name(data, fallback_location)
    lines = [f"📅 {place} 未来 {days} 天预报（{unit_sym}）"]
    for day in (data.get("weather") or [])[:days]:
        code = ""
        hourly = day.get("hourly") or []
        if hourly:
            code = str(hourly[len(hourly) // 2].get("weatherCode", ""))
        desc = _first_value(hourly[len(hourly) // 2], "weatherDesc") if hourly else ""
        name, emoji = _describe(code, desc)
        low = day.get("mintempF" if imperial else "mintempC", "-")
        high = day.get("maxtempF" if imperial else "maxtempC", "-")
        rain = "0"
        if hourly:
            vals = []
            for h in hourly:
                try:
                    vals.append(float(h.get("chanceofrain", 0) or 0))
                except (TypeError, ValueError):
                    continue
            if vals:
                rain = str(round(sum(vals) / len(vals)))
        lines.append(
            f"{day.get('date', '?')}  {emoji} {name}  {low}~{high}{unit_sym}  平均降雨概率 {rain}%"
        )
    lines.append("数据来源 wttr.in")
    return "\n".join(lines)


@register(
    "astrbot_plugin_weather",
    "linker9527",
    "基于 wttr.in 的天气查询：当前天气、多日预报、一行速览、PNG 天气图",
    "1.2.2",
    "https://github.com/linker9527/astrbot_plugin_weather",
)
class WeatherPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}

    def _cfg(self, key, default):
        value = self.config.get(key, default)
        return default if value is None or value == "" else value

    def _resolve_location(self, raw):
        raw = _safe_str(raw)
        return raw or self._cfg("default_location", DEFAULT_LOCATION)

    def _timeout(self, default):
        """timeout 配置下限 1 秒；aiohttp 的 total=0 等于永不超时，必须挡住。"""
        try:
            return max(1.0, float(self._cfg("timeout", default)))
        except (TypeError, ValueError):
            return float(default)

    def _forecast_days(self):
        """预报天数统一解析：非法值回退 3，并夹到 1~3（上游最多 3 天）。"""
        try:
            days = int(self._cfg("forecast_days", 3))
        except (TypeError, ValueError):
            days = 3
        return max(1, min(3, days))

    async def _query(self, location, view, days):
        unit = self._cfg("units", "metric")
        lang = self._cfg("language", "zh")
        timeout = self._timeout(12)
        fmt = "j1" if view == "forecast" else "j2"
        urls = _build_urls(location, fmt, unit, lang)
        errors = []
        data = None
        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    data = await _fetch_json(session, url, timeout, lang)
                    break
                except _QUERY_ERRORS as e:  # 主域名失败时换备用域名
                    errors.append(f"{urllib.parse.urlsplit(url).netloc}: {e}")
                    logger.warning(f"[astrbot_plugin_weather] 请求失败 {url}: {e}")
        if data is None:
            raise RuntimeError("天气服务不可用（" + "; ".join(errors) + "）")

        # 格式化在重试循环之外：上游字段异常降级显示，不再伪装成「服务不可用」。
        addr = ""
        if self._cfg("use_full_address", True):
            try:
                async with aiohttp.ClientSession() as session:
                    addr = await _fetch_full_address(
                        session, location, unit, lang, timeout
                    )
            except _QUERY_ERRORS as e:
                logger.warning(f"[astrbot_plugin_weather] FullAddress 获取失败: {e}")
        if view == "forecast":
            return _fmt_forecast(data, location, unit, days, addr)
        return _fmt_current(data, location, unit, addr)

    async def _one_line(self, location):
        unit = self._cfg("units", "metric")
        lang = self._cfg("language", "zh")
        timeout = self._timeout(12)
        urls = _build_urls(location, "3", unit, lang)
        errors = []
        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    async with session.get(
                        url,
                        headers=_headers(lang),
                        timeout=aiohttp.ClientTimeout(total=timeout),
                    ) as resp:
                        if resp.status != 200:
                            raise RuntimeError(f"HTTP {resp.status}")
                        text = (await resp.text()).strip()
                        if text:
                            return text
                        raise RuntimeError("空响应")
                except _QUERY_ERRORS as e:
                    errors.append(f"{urllib.parse.urlsplit(url).netloc}: {e}")
                    logger.warning(f"[astrbot_plugin_weather] 请求失败 {url}: {e}")
        raise RuntimeError("天气服务不可用（" + "; ".join(errors) + "）")

    async def _png_bytes(self, location):
        unit = self._cfg("units", "metric")
        lang = self._cfg("language", "zh")
        timeout = self._timeout(20)
        urls = _png_urls(location, unit, lang)
        errors = []
        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    return await _fetch_png(session, url, timeout, lang)
                except _QUERY_ERRORS as e:
                    errors.append(f"{urllib.parse.urlsplit(url).netloc}: {e}")
                    logger.warning(f"[astrbot_plugin_weather] PNG 请求失败 {url}: {e}")
        raise RuntimeError("天气图片服务不可用（" + "; ".join(errors) + "）")

    @staticmethod
    def _image_chain(png):
        return [Image.fromBytes(png)]

    HELP_TEXT = (
        "天气查询（wttr.in）\n"
        "/weather                    查默认城市当前天气\n"
        "/weather 上海               当前天气\n"
        "/weather 上海 now           一行速览\n"
        "/weather 上海 forecast      多日预报\n"
        "/weather 上海 3             未来 3 天预报（天数 1~3，上游最多 3 天）\n"
        "/weather 上海 img / 图片     PNG 天气图\n"
        "/weather help / 帮助         显示本帮助\n"
        "参数也可写在地点前：/weather now 上海\n"
        "地点支持中文、英文、机场三字码、坐标；留空用配置里的默认城市。"
    )

    @staticmethod
    def _parse_args(event):
        """剥掉命令名，取出 (模式, 地点, 天数)。

        模式词可出现在地点前或后，且全部从地点里剔除（多写不会把词当地点）。
        天数取任意位置出现的纯数字 1~3（最后一个生效）；更长的数字如 94107
        视为邮编/区号保留在地点里，不误判成天数。
        """
        parts = (event.message_str or "").strip().split()
        if parts:
            first = parts[0].lstrip("/").lower()
            if first in _COMMAND_WORDS:
                parts = parts[1:]
        days = 0
        mode = ""
        loc_parts = []
        for token in parts:
            key = token.lower()
            if token in ("1", "2", "3"):
                days = int(token)
            elif key in _MODE_WORDS:
                # 所有模式词都从地点里剔除；mode 只取第一个，后续不覆盖。
                if not mode:
                    mode = _MODE_WORDS[key]
            else:
                loc_parts.append(token)
        return mode, " ".join(loc_parts), days

    @filter.command("weather", alias={"天气", "tianqi", "wttr"})
    async def cmd_weather(self, event: AstrMessageEvent, location: str = ""):
        """天气查询：/weather [地点] [now|forecast|img|help|天数]，不带地点用默认城市

        AstrBot 只把第一个 token 填进 location，多余 token 会丢弃；因此地点一律
        由 _parse_args 从 message_str 二次解析，绝不用 location 兜底（否则纯模式词
        会被当成同名地点）。location 参数仅为满足 handler 签名而保留。
        """
        sub, rest, days = self._parse_args(event)
        loc = self._resolve_location(rest)
        if sub == "help":
            yield event.plain_result(self.HELP_TEXT)
            return
        if days and not sub:
            sub = "forecast"
        if sub == "forecast":
            days = max(1, min(3, days)) if days else self._forecast_days()
            try:
                yield event.plain_result(await self._query(loc, "forecast", days))
            except _QUERY_ERRORS as e:
                logger.error(f"[astrbot_plugin_weather] forecast 失败: {e}")
                yield event.plain_result(f"查询「{loc}」预报失败：{e}")
            return
        if sub == "now":
            try:
                yield event.plain_result(await self._one_line(loc))
            except _QUERY_ERRORS as e:
                logger.error(f"[astrbot_plugin_weather] now 失败: {e}")
                yield event.plain_result(f"查询「{loc}」失败：{e}")
            return
        if sub == "pic":
            try:
                png = await self._png_bytes(loc)
                yield event.chain_result(
                    [Plain(f"{loc} 天气图")] + self._image_chain(png)
                )
            except _QUERY_ERRORS as e:
                logger.error(f"[astrbot_plugin_weather] pic 失败: {e}")
                yield event.plain_result(f"获取「{loc}」天气图失败：{e}")
            return
        try:
            yield event.plain_result(await self._query(loc, "current", 3))
        except _QUERY_ERRORS as e:
            logger.error(f"[astrbot_plugin_weather] current 失败: {e}")
            yield event.plain_result(f"查询「{loc}」失败：{e}")

    @filter.command("forecast", alias={"天气预报", "预报"})
    async def cmd_forecast(self, event: AstrMessageEvent, location: str = ""):
        """多日预报快捷命令：/forecast [地点]（多词地点同样走 message_str 解析）"""
        _, rest, days = self._parse_args(event)
        loc = self._resolve_location(rest)
        days = max(1, min(3, days)) if days else self._forecast_days()
        try:
            yield event.plain_result(await self._query(loc, "forecast", days))
        except _QUERY_ERRORS as e:
            logger.error(f"[astrbot_plugin_weather] /forecast 失败: {e}")
            yield event.plain_result(f"查询「{loc}」预报失败：{e}")

    @llm_tool(name="getweather")
    async def tool_get_weather(
        self, event: AstrMessageEvent, location: str = "", view: str = "current"
    ):
        """查询指定地点的当前天气或未来几天预报。用户问天气、气温、下雨、要不要带伞、穿什么衣服时使用。

        Args:
            location(string): 地点名称，如 北京、London、muc；留空则查询默认城市
            view(string): 查询类型，current 为当前天气，forecast 为多日预报，默认 current
        """
        if not self.config.get("enable_llm_tools", True):
            yield event.plain_result("天气工具已在插件配置中关闭")
            return
        loc = self._resolve_location(location)
        view = "forecast" if str(view).strip().lower() == "forecast" else "current"
        days = self._forecast_days()
        try:
            yield event.plain_result(await self._query(loc, view, days))
        except _QUERY_ERRORS as e:
            logger.error(f"[astrbot_plugin_weather] llm_tool 失败: {e}")
            yield event.plain_result(f"查询「{loc}」失败：{e}")

    @llm_tool(name="getweatheroneline")
    async def tool_oneline(self, event: AstrMessageEvent, location: str = ""):
        """获取指定地点的一行式天气速览，适合状态栏或简短回答。

        Args:
            location(string): 地点名称；留空则查询默认城市
        """
        if not self.config.get("enable_llm_tools", True):
            yield event.plain_result("天气工具已在插件配置中关闭")
            return
        loc = self._resolve_location(location)
        try:
            yield event.plain_result(await self._one_line(loc))
        except _QUERY_ERRORS as e:
            logger.error(f"[astrbot_plugin_weather] llm_tool oneline 失败: {e}")
            yield event.plain_result(f"查询「{loc}」失败：{e}")

    @llm_tool(name="getweatherimage")
    async def tool_image(self, event: AstrMessageEvent, location: str = ""):
        """获取指定地点的 wttr.in PNG 天气图，返回给大模型查看，不直接发给用户。

        用户想看天气图、想把图发给别人、或你需要在回答里配一张天气图时调用。
        图片会作为工具结果返回供你审阅；确认合适后可用 send_message_to_user 发给用户，
        也可以先对用户说几句再发。

        Args:
            location(string): 地点名称，如 北京、London、muc；留空则查询默认城市
        """
        if not self.config.get("enable_llm_tools", True):
            return "天气工具已在插件配置中关闭"
        loc = self._resolve_location(location)
        try:
            png = await self._png_bytes(loc)
        except _QUERY_ERRORS as e:
            logger.error(f"[astrbot_plugin_weather] llm_tool image 失败: {e}")
            return f"获取「{loc}」天气图失败：{e}"

        try:
            from mcp.types import CallToolResult, ImageContent, TextContent
        except ImportError:
            # 旧版 AstrBot 无 mcp 时降级：只给文本，不把图当工具结果返回
            logger.warning(
                "[astrbot_plugin_weather] 缺少 mcp.types，图片工具降级为文本"
            )
            return (
                f"已获取「{loc}」天气图，但当前 AstrBot 版本不支持把图片返回给大模型。"
            )

        b64 = base64.b64encode(png).decode("ascii")
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"已生成「{loc}」的 wttr.in 天气图（PNG，{len(png)} 字节）。请查看下方图片。",
                ),
                ImageContent(type="image", data=b64, mimeType="image/png"),
            ]
        )

    async def terminate(self):
        """插件卸载时无需清理：网络会话随请求结束即关闭。"""
