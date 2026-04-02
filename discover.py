#!/usr/bin/env python3
"""
携程特价机票 FuzzySearch 全国特价概览模块
通过携程模糊搜索页面(fuzzysearch)，直接获取指定城市出发到全国的特价往返机票
无需逐个城市搜索，一次请求即可获取所有目的地的最低价

由 main.py discover 子命令调用
"""
import sys
import os
import json
import time
import random
import logging
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path

# 确保能导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import HOLIDAYS, SEARCH_DAYS_AHEAD, REQUEST_DELAY, MIN_STAY_DAYS, MAX_STAY_DAYS
from date_utils import get_all_travel_periods, get_periods_for_dates

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# === 常量 ===
PAGE_LOAD_WAIT = 15  # 等待页面 API 响应的最大秒数

FUZZYSEARCH_PAGE = "https://flights.ctrip.com/fuzzysearch/search"

# macOS Chrome 用户数据目录
_CHROME_USER_DATA = str(Path.home() / "Library/Application Support/Google/Chrome")

# 城市名 → (code, name) 映射表
CITY_MAP = {
    "北京": ("BJS", "北京"),
    "上海": ("SHA", "上海"),
    "广州": ("CAN", "广州"),
    "深圳": ("SZX", "深圳"),
    "成都": ("CTU", "成都"),
    "杭州": ("HGH", "杭州"),
    "武汉": ("WUH", "武汉"),
    "西安": ("SIA", "西安"),
    "重庆": ("CKG", "重庆"),
    "南京": ("NKG", "南京"),
    "长沙": ("CSX", "长沙"),
    "昆明": ("KMG", "昆明"),
    "天津": ("TSN", "天津"),
    "青岛": ("TAO", "青岛"),
    "大连": ("DLC", "大连"),
    "厦门": ("XMN", "厦门"),
    "沈阳": ("SHE", "沈阳"),
    "哈尔滨": ("HRB", "哈尔滨"),
    "郑州": ("CGO", "郑州"),
    "福州": ("FOC", "福州"),
    "济南": ("TNA", "济南"),
    "合肥": ("HFE", "合肥"),
    "贵阳": ("KWE", "贵阳"),
    "南宁": ("NNG", "南宁"),
    "海口": ("HAK", "海口"),
    "三亚": ("SYX", "三亚"),
    "拉萨": ("LXA", "拉萨"),
    "乌鲁木齐": ("URC", "乌鲁木齐"),
    "兰州": ("LHW", "兰州"),
    "银川": ("INC", "银川"),
    "西宁": ("XNN", "西宁"),
    "呼和浩特": ("HET", "呼和浩特"),
    "太原": ("TYN", "太原"),
    "石家庄": ("SJW", "石家庄"),
    "长春": ("CGQ", "长春"),
    "南昌": ("KHN", "南昌"),
    "珠海": ("ZUH", "珠海"),
    "无锡": ("WUX", "无锡"),
    "宁波": ("NGB", "宁波"),
    "温州": ("WNZ", "温州"),
}

# 默认出发城市（从 config 读取）
from config import DEPARTURE_CITY_CODE, DEPARTURE_CITY_NAME

# 注入到页面的 JS 拦截脚本
# 同时捕获 API 的 请求(URL+method+headers+body) 和 响应(body)
_INTERCEPT_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
(function() {
    window.__fuzzyResponses = [];
    window.__fuzzyRequests = [];

    const origFetch = window.fetch;
    window.fetch = function(input, init) {
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        var method = (init && init.method) || 'GET';
        var body = (init && init.body) || null;
        var headers = null;
        if (init && init.headers) {
            if (init.headers instanceof Headers) {
                headers = {};
                init.headers.forEach(function(v, k) { headers[k] = v; });
            } else {
                headers = init.headers;
            }
        }

        // 捕获 fuzzysearch 相关的 API 请求
        if (url.indexOf('uzzy') !== -1 || url.indexOf('lowprice') !== -1) {
            window.__fuzzyRequests.push({
                url: url,
                method: method,
                body: body,
                headers: headers
            });
        }

        return origFetch.apply(this, arguments).then(function(response) {
            if (url.indexOf('uzzy') !== -1 || url.indexOf('lowprice') !== -1) {
                response.clone().text().then(function(respBody) {
                    try {
                        var d = JSON.parse(respBody);
                        if (d && d.routes) {
                            window.__fuzzyResponses.push(respBody);
                        }
                    } catch(e) {}
                });
            }
            return response;
        });
    };

    // XHR 拦截
    var origOpen = XMLHttpRequest.prototype.open;
    var origSend = XMLHttpRequest.prototype.send;
    var origSetHeader = XMLHttpRequest.prototype.setRequestHeader;

    XMLHttpRequest.prototype.open = function(method, url) {
        this._url = url;
        this._method = method;
        this._headers = {};
        return origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        if (this._headers) this._headers[name] = value;
        return origSetHeader.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function(body) {
        var xhr = this;
        var url = this._url || '';
        if (url.indexOf('uzzy') !== -1 || url.indexOf('lowprice') !== -1) {
            window.__fuzzyRequests.push({
                url: url,
                method: this._method || 'GET',
                body: body || null,
                headers: this._headers || null
            });
            xhr.addEventListener('load', function() {
                try {
                    var d = JSON.parse(xhr.responseText);
                    if (d && d.routes) {
                        window.__fuzzyResponses.push(xhr.responseText);
                    }
                } catch(e) {}
            });
        }
        return origSend.apply(this, arguments);
    };
})();
"""


def calculate_trip_days(period):
    """
    根据假期类型计算出行天数范围
    周末: n ~ n+2 天 (n = 假期天数)
    节假日: n ~ n+4 天 (n = 假期天数)
    """
    n = (period["holiday_end"] - period["holiday_start"]).days + 1
    if period["type"] == "weekend":
        return list(range(n, n + 3))
    else:
        return list(range(n, n + 5))


def resolve_city(city_name_or_code):
    """
    根据城市名或代码解析出 (code, name)
    支持中文名（如"上海"）或三字码（如"SHA"）
    """
    # 先按名称查找
    if city_name_or_code in CITY_MAP:
        return CITY_MAP[city_name_or_code]
    # 按代码查找
    upper = city_name_or_code.upper()
    for name, (code, cname) in CITY_MAP.items():
        if code == upper:
            return (code, name)
    # 如果是3字母代码，直接使用
    if len(city_name_or_code) == 3 and city_name_or_code.isalpha():
        return (upper, city_name_or_code)
    # 默认返回原始输入
    return (city_name_or_code, city_name_or_code)


def prepare_chrome_profile():
    """将 Chrome 默认 profile 的 cookie 数据拷贝到临时目录"""
    src = os.path.join(_CHROME_USER_DATA, "Default")
    if not os.path.isdir(src):
        logger.warning("未找到 Chrome 默认 profile: %s", src)
        return None

    tmp_dir = tempfile.mkdtemp(prefix="fuzzy_chrome_")
    dst = os.path.join(tmp_dir, "Default")
    os.makedirs(dst, exist_ok=True)

    for name in ("Cookies", "Cookies-journal", "Login Data", "Login Data-journal",
                  "Preferences", "Secure Preferences", "Local State"):
        src_file = os.path.join(src, name)
        if not os.path.exists(src_file):
            src_file = os.path.join(_CHROME_USER_DATA, name)
        if os.path.exists(src_file):
            dst_file = os.path.join(dst, name) if name != "Local State" else os.path.join(tmp_dir, name)
            shutil.copy2(src_file, dst_file)

    logger.info("已加载 Chrome cookie 数据")
    return tmp_dir


def init_browser(headless=False):
    """启动 Chrome 浏览器并注入拦截脚本"""
    logger.info("启动 Chrome 浏览器 (headless=%s)...", headless)
    options = Options()

    tmp_profile = None
    if headless:
        options.add_argument("--headless=new")
        tmp_profile = prepare_chrome_profile()
    if tmp_profile:
        options.add_argument(f"--user-data-dir={tmp_profile}")
        options.add_argument("--profile-directory=Default")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": _INTERCEPT_JS},
    )
    logger.info("浏览器启动成功")
    return driver, tmp_profile


def discover_api(driver):
    """
    打开 fuzzysearch 页面，拦截页面自身发出的 API 请求，
    返回 API 模板 (url, method, headers, body_dict) 供后续重放
    """
    logger.info("打开 fuzzysearch 页面，捕获 API 请求模板...")
    driver.get(FUZZYSEARCH_PAGE)

    # 等待页面加载并发出 API 请求
    time.sleep(8)

    # 提取捕获到的请求
    raw = driver.execute_script(
        "return JSON.stringify(window.__fuzzyRequests || []);"
    )
    requests = json.loads(raw)
    logger.info("捕获到 %d 个 API 请求", len(requests))

    # 同时提取响应（页面默认搜索的结果，可以用来验证）
    resp_raw = driver.execute_script(
        "var r = window.__fuzzyResponses || []; window.__fuzzyResponses = []; return JSON.stringify(r);"
    )
    responses = json.loads(resp_raw)
    logger.info("捕获到 %d 个 API 响应", len(responses))

    # 找到包含 body 的 POST 请求（真正的搜索 API）
    api_template = None
    for req in requests:
        if req.get("body"):
            try:
                body = json.loads(req["body"]) if isinstance(req["body"], str) else req["body"]
                api_template = {
                    "url": req["url"],
                    "method": req.get("method", "POST"),
                    "headers": req.get("headers", {}),
                    "body": body,
                }
                logger.info("发现 API 模板: %s (method=%s)", req["url"][:100], req.get("method"))
                logger.debug("请求体 keys: %s", list(body.keys()) if isinstance(body, dict) else type(body))
                break
            except (json.JSONDecodeError, TypeError):
                continue

    if not api_template:
        # 没有 POST 请求，尝试用 GET 请求（可能参数在 URL 中）
        for req in requests:
            if req.get("url"):
                api_template = {
                    "url": req["url"],
                    "method": req.get("method", "GET"),
                    "headers": req.get("headers", {}),
                    "body": None,
                }
                logger.info("发现 GET API: %s", req["url"][:100])
                break

    if not api_template:
        logger.warning("未能捕获到 API 请求模板")
        for i, req in enumerate(requests):
            logger.warning("  请求 %d: %s %s body=%s",
                           i, req.get("method", "?"), req.get("url", "?")[:80],
                           "有" if req.get("body") else "无")

    # 保存调试信息
    debug_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".fuzzysearch_debug.json")
    try:
        debug_data = {
            "requests": requests,
            "response_count": len(responses),
            "api_template": api_template,
            "first_response_sample": json.loads(responses[0])["routes"][0] if responses else None,
        }
        with open(debug_file, "w", encoding="utf-8") as f:
            json.dump(debug_data, f, ensure_ascii=False, indent=2)
        logger.info("已保存调试信息到 %s", debug_file)
    except Exception:
        pass

    return api_template


def _modify_request_body(body, dep_city_code, dep_city_name, date_begin, date_end, trip_days):
    """
    修改 API 请求体中的参数
    真实请求体结构:
    {
      "tt": 2,  // 1=单程, 2=往返
      "segments": [{
        "dcs": [{"name": "北京", "code": "BJS", "ct": 1}],
        "acs": [{"ct": 3, "code": "DOMESTIC_ALL", "name": "全中国"}],
        "drl": [{"begin": "2026-4-2", "end": "2026-4-4"}],
        "sr": {"min": 2, "max": 6},
        "dow": []
      }]
    }
    """
    if not isinstance(body, dict):
        return body

    modified = json.loads(json.dumps(body))  # deep copy

    # 1. 设置往返: tt=2
    modified["tt"] = 2

    # 2. 修改 segments
    segments = modified.get("segments", [])
    if segments and isinstance(segments[0], dict):
        seg = segments[0]

        # 修改出发城市 dcs
        seg["dcs"] = [{"ct": 1, "code": dep_city_code, "name": dep_city_name}]

        # 修改日期范围 drl — 窄范围，仅覆盖假期出发日期
        seg["drl"] = [{"begin": date_begin.strftime("%Y-%-m-%-d"), "end": date_end.strftime("%Y-%-m-%-d")}]

        # 设置出行天数 sr (stayRange)
        if trip_days:
            seg["sr"] = {"min": min(trip_days), "max": max(trip_days)}

    return modified


def replay_api(driver, api_template, dep_city_code, dep_city_name, date_begin, date_end, trip_days):
    """
    用修改后的参数重放 API 请求
    在页面上下文中使用 fetch()，天然携带 cookie 和 session
    """
    if not api_template:
        return None

    url = api_template["url"]
    method = api_template["method"]
    headers = api_template.get("headers") or {}
    body = api_template.get("body")

    # 修改请求体参数
    if body:
        modified_body = _modify_request_body(body, dep_city_code, dep_city_name, date_begin, date_end, trip_days)
        body_json = json.dumps(modified_body, ensure_ascii=False)
        logger.debug("  重放请求体: %s", body_json[:300])
    else:
        body_json = None

    # 确保 headers 有 Content-Type
    if body_json and "content-type" not in {k.lower() for k in headers}:
        headers["Content-Type"] = "application/json"

    headers_json = json.dumps(headers, ensure_ascii=False)

    # 在页面上下文中执行 fetch
    js_code = """
    var callback = arguments[arguments.length - 1];
    var url = arguments[0];
    var method = arguments[1];
    var headers = JSON.parse(arguments[2]);
    var body = arguments[3];

    var opts = {method: method, headers: headers};
    if (body) opts.body = body;

    fetch(url, opts)
        .then(function(r) { return r.text(); })
        .then(function(t) { callback(t); })
        .catch(function(e) { callback(JSON.stringify({error: e.toString()})); });
    """

    try:
        driver.set_script_timeout(20)
        result = driver.execute_async_script(
            js_code, url, method, headers_json, body_json
        )
        return result
    except Exception as e:
        logger.warning("  API 重放失败: %s", e)
        return None


def search_fuzzysearch(driver, api_template, dep_city_code, dep_city_name, period):
    """
    执行一次 fuzzysearch 搜索（通过 API 重放）
    每个假期/周末只请求一次，日期范围覆盖该时段所有出发日
    """
    depart_dates = period["depart_dates"]
    date_begin = depart_dates[0]
    date_end = depart_dates[-1]
    trip_days = calculate_trip_days(period)
    tripday_str = f"{trip_days[0]}~{trip_days[-1]}"

    logger.info("  搜索: %s出发 %s~%s, 出行 %s 天",
                dep_city_name, date_begin, date_end, tripday_str)

    results = []

    # 方式 1: 通过 API 重放
    if api_template:
        raw = replay_api(driver, api_template, dep_city_code, dep_city_name,
                         date_begin, date_end, trip_days)
        if raw:
            try:
                data = json.loads(raw)
                if data.get("error"):
                    logger.warning("  API 返回错误: %s", data["error"])
                else:
                    # 保存第一次重放响应供调试
                    debug_replay = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), ".fuzzysearch_replay.json"
                    )
                    if not os.path.exists(debug_replay):
                        try:
                            sample = dict(data)
                            if sample.get("routes") and len(sample["routes"]) > 2:
                                sample["routes"] = sample["routes"][:2]
                            with open(debug_replay, "w", encoding="utf-8") as f:
                                json.dump(sample, f, ensure_ascii=False, indent=2)
                            logger.info("  [诊断] 已保存重放响应样本到 %s", debug_replay)
                        except Exception:
                            pass

                    sdate = date_begin.strftime("%Y-%m-%d")
                    results = parse_fuzzy_response(data, sdate)
                    if results:
                        logger.info("    → API 重放获取到 %d 条航线", len(results))
                        return results
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("  API 响应解析失败: %s | 前200字符: %s", e, str(raw)[:200])

    # 方式 2: API 重放失败时回退到页面导航 + 拦截
    logger.info("  回退到页面导航模式...")
    try:
        driver.get(FUZZYSEARCH_PAGE)
        time.sleep(8)

        resp_raw = driver.execute_script(
            "var r = window.__fuzzyResponses || []; window.__fuzzyResponses = []; return JSON.stringify(r);"
        )
        responses = json.loads(resp_raw)

        sdate = date_begin.strftime("%Y-%m-%d")
        for body_str in responses:
            try:
                data = json.loads(body_str)
                parsed = parse_fuzzy_response(data, sdate)
                results.extend(parsed)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

    except Exception as e:
        logger.warning("  页面导航搜索失败: %s", e)

    # 请求延迟
    delay = REQUEST_DELAY + random.uniform(0, 2)
    time.sleep(delay)

    return results


def parse_fuzzy_response(data, sdate):
    """
    解析 fuzzysearch API 响应
    真实格式: { "routes": [ { "arriveCity": {...}, "flights": [...], "pl": [...], "tags": [...] } ] }
    """
    results = []

    routes = data.get("routes", [])
    if not routes:
        if data.get("data") and isinstance(data["data"], str):
            logger.debug("  [诊断] 响应为加密数据，跳过")
        elif data.get("ResponseStatus"):
            logger.debug("  [诊断] 响应为状态信息，无 routes")
        else:
            logger.debug("  [诊断] 响应无 routes，keys: %s", list(data.keys()))
        return results

    for route in routes:
        parsed = _parse_single_route(route, sdate)
        if parsed:
            results.append(parsed)

    if routes and not results:
        logger.warning("  [诊断] 有 %d 条路线但全部解析失败", len(routes))

    return results


def _parse_single_route(route, sdate):
    """解析单条路线数据 - 基于携程 fuzzysearch 真实 API 响应格式"""
    if not isinstance(route, dict):
        return None

    if route.get("isIntl", False):
        return None

    # 目的地信息
    arr_city = route.get("arriveCity", {})
    city_name = arr_city.get("name", "")
    city_code = arr_city.get("code", "")
    province = arr_city.get("provinceName", "")
    if arr_city.get("isIntl", False) or not city_name:
        return None

    # 出发城市
    dep_city_info = route.get("departCity", {})
    dep_city_name = dep_city_info.get("name", "")

    # 价格列表 pl[]
    pl = route.get("pl", [])
    if not pl:
        return None

    valid_pl = [p for p in pl if isinstance(p, dict) and p.get("price", 0) > 0]
    if not valid_pl:
        return None

    best = min(valid_pl, key=lambda x: x["price"])
    price = int(best["price"])
    go_date = best.get("departDate", sdate)
    back_date = best.get("returnDate", "")
    jump_url = best.get("jumpUrl", "")

    all_prices = sorted(
        [{"price": int(p["price"]), "date": p.get("departDate", "")} for p in valid_pl],
        key=lambda x: x["price"],
    )

    # 航班信息 flights[] — segment=1 去程, segment=2 返程
    flights = route.get("flights", [])
    go_flight = {}
    ret_flight = {}
    for fl in flights:
        seg = fl.get("segment", 0)
        if seg == 1 and not go_flight:
            go_flight = fl
        elif seg == 2 and not ret_flight:
            ret_flight = fl

    # 如果没有 segment 标记，按顺序取
    if not go_flight and flights:
        go_flight = flights[0]
    if not ret_flight and len(flights) > 1:
        ret_flight = flights[1]

    def _extract_flight(fl):
        if not fl:
            return {"flight_no": "", "airline": "", "dep_airport": "", "arr_airport": "",
                    "dep_time": "", "arr_time": "", "duration": 0}
        airline_info = fl.get("airline", {})
        dport = fl.get("dport", {})
        aport = fl.get("aport", {})
        return {
            "flight_no": fl.get("flightNo", ""),
            "airline": airline_info.get("name", "") if isinstance(airline_info, dict) else "",
            "dep_airport": dport.get("fullName", dport.get("name", "")),
            "arr_airport": aport.get("fullName", aport.get("name", "")),
            "dep_time": fl.get("dtime", ""),
            "arr_time": fl.get("atime", ""),
            "duration": fl.get("duration", 0),
        }

    go_info = _extract_flight(go_flight)
    ret_info = _extract_flight(ret_flight)

    # 计算游玩天数
    stay_days = 0
    leave_days = 0
    if go_date and back_date:
        try:
            d1 = date.fromisoformat(go_date)
            d2 = date.fromisoformat(back_date)
            stay_days = (d2 - d1).days

            # 计算休假天数：出发日~返程日中，需要请假的工作日数
            # 工作日 = 周一~周五 且 不在法定节假日范围内
            holiday_dates = set()
            for h in HOLIDAYS:
                d = h["start"]
                while d <= h["end"]:
                    holiday_dates.add(d)
                    d += timedelta(days=1)
            d = d1
            while d <= d2:
                if d.weekday() < 5 and d not in holiday_dates:
                    leave_days += 1
                d += timedelta(days=1)
        except (ValueError, TypeError):
            pass

    # 标签 tags[]
    tags = [t.get("name", "") for t in route.get("tags", [])
            if isinstance(t, dict) and t.get("name")]

    return {
        "city_name": city_name,
        "city_code": city_code,
        "province": province,
        "dep_city_name": dep_city_name,
        "price": price,
        "go_date": go_date,
        "back_date": back_date,
        "stay_days": stay_days,
        "leave_days": leave_days,
        "jump_url": jump_url,
        "all_prices": all_prices,
        # 去程
        "flight_no": go_info["flight_no"],
        "airline": go_info["airline"],
        "dep_airport": go_info["dep_airport"],
        "arr_airport": go_info["arr_airport"],
        "dep_time": go_info["dep_time"],
        "arr_time": go_info["arr_time"],
        "duration": go_info["duration"],
        # 返程
        "ret_flight_no": ret_info["flight_no"],
        "ret_airline": ret_info["airline"],
        "ret_dep_airport": ret_info["dep_airport"],
        "ret_arr_airport": ret_info["arr_airport"],
        "ret_dep_time": ret_info["dep_time"],
        "ret_arr_time": ret_info["arr_time"],
        "ret_duration": ret_info["duration"],
        "tags": tags,
    }


def filter_results(results, max_price=0, min_price=0, min_stay=0, max_stay=0):
    """
    统一过滤搜索结果
    - max_price: 最高价格（0=不过滤）
    - min_price: 最低价格（0=不过滤）
    - min_stay: 最少游玩天数（0=不过滤）
    - max_stay: 最多游玩天数（0=不过滤）
    """
    filtered = results

    if min_price > 0:
        filtered = [r for r in filtered if r["price"] >= min_price]

    if max_price > 0:
        filtered = [r for r in filtered if 0 < r["price"] <= max_price]

    if min_stay > 0:
        filtered = [r for r in filtered if r["stay_days"] >= min_stay]

    if max_stay > 0:
        filtered = [r for r in filtered if 0 < r["stay_days"] <= max_stay]

    return filtered


def deduplicate_results(results):
    """去重: 同一目的地保留最低价"""
    best = {}
    for r in results:
        key = r["city_code"] or r["city_name"]
        if key not in best or (r["price"] > 0 and r["price"] < best[key]["price"]):
            best[key] = r
    return sorted(best.values(), key=lambda x: x["price"])


def _fmt_duration(minutes):
    """格式化飞行时长"""
    if not minutes:
        return "-"
    h, m = divmod(int(minutes), 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _fmt_time(dt_str):
    """从 '2026-04-16 08:25:00' 提取 '08:25'"""
    if not dt_str:
        return ""
    try:
        parts = dt_str.split(" ")
        if len(parts) >= 2:
            return parts[1][:5]
        return dt_str[:5]
    except Exception:
        return ""


def print_results(all_period_results, dep_city_name):
    """格式化输出搜索结果"""
    total_count = sum(len(v) for v in all_period_results.values())
    if total_count == 0:
        print("\n" + "=" * 60)
        print("未找到满足条件的特价机票")
        print("=" * 60)
        return

    print(f"\n# 携程 FuzzySearch 特价机票")
    print(f"\n> 出发城市: {dep_city_name} | 目的地: 全中国 | 查询时间: {date.today()}")

    grand_total = 0

    for period_name, results in all_period_results.items():
        if not results:
            continue

        results = deduplicate_results(results)
        grand_total += len(results)

        print(f"\n## {period_name}\n")
        print("| # | 目的地 | 省份 | 最低价 | 去程日期 | 去程航班 | 起飞 | 时长 | 返程日期 | 返程航班 | 起飞 | 时长 | 游玩天数 | 休假天数 | 景点推荐 |")
        print("|---|--------|------|-------|----------|---------|------|------|----------|---------|------|------|---------|---------|---------|")

        for rank, r in enumerate(results, 1):
            city = r["city_name"]
            province = r["province"] or "-"
            price_str = f"¥{r['price']}" if r["price"] > 0 else "-"
            # 去程
            go_d = r["go_date"] or "-"
            go_flt = f"{r['flight_no']}({r['airline']})" if r["flight_no"] and r["airline"] else (r["flight_no"] or "-")
            go_t = _fmt_time(r["dep_time"]) or "-"
            go_dur = _fmt_duration(r["duration"])
            # 返程
            back_d = r.get("back_date", "") or "-"
            ret_flt = ""
            ret_no = r.get("ret_flight_no", "")
            ret_al = r.get("ret_airline", "")
            if ret_no and ret_al:
                ret_flt = f"{ret_no}({ret_al})"
            elif ret_no:
                ret_flt = ret_no
            else:
                ret_flt = "-"
            ret_t = _fmt_time(r.get("ret_dep_time", "")) or "-"
            ret_dur = _fmt_duration(r.get("ret_duration", 0))
            # 游玩天数
            stay = r.get("stay_days", 0)
            stay_str = f"{stay}天" if stay > 0 else "-"
            leave = r.get("leave_days", 0)
            leave_str = f"{leave}天" if leave > 0 else "0"
            tags = ", ".join(r["tags"][:2]) if r["tags"] else "-"

            print(f"| {rank} | {city} | {province} | **{price_str}** | {go_d} | {go_flt} | {go_t} | {go_dur} | {back_d} | {ret_flt} | {ret_t} | {ret_dur} | {stay_str} | {leave_str} | {tags} |")

    print(f"\n> 共找到 **{grand_total}** 条航线\n")


def print_search_plan(periods, dep_city_name):
    """打印搜索计划"""
    print(f"\n{'═' * 80}")
    print(f"  携程 FuzzySearch 特价机票搜索")
    print(f"  出发城市: {dep_city_name} → 目的地: 全中国")
    print(f"{'═' * 80}")
    print(f"\n将搜索以下出行时段 (每个时段 1 次 API 请求):")
    print(f"{'─' * 80}")
    print(f"  {'假期名称':<16} {'出发日期范围':<24} {'出行天数':<16} {'类型':<6}")
    print(f"{'─' * 80}")

    for p in periods:
        ptype = "节假日" if p["type"] == "holiday" else "周末"
        dep_range = f"{p['depart_dates'][0]} ~ {p['depart_dates'][-1]}"
        trip_days = calculate_trip_days(p)
        trip_str = f"{trip_days[0]}~{trip_days[-1]}天"
        print(f"  {p['name']:<14} {dep_range:<22} {trip_str:<14} {ptype:<6}")

    print(f"{'─' * 80}")
    print(f"  总请求次数: {len(periods)} (每次请求覆盖全国所有目的地)")
    est_min = max(1, len(periods) * (PAGE_LOAD_WAIT + REQUEST_DELAY) // 60)
    print(f"  预计耗时: ~{est_min} 分钟")
    print()


def run(args):
    """discover 子命令入口，接收 argparse Namespace"""
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 解析出发城市
    if args.from_city:
        dep_city_code, dep_city_name = resolve_city(args.from_city)
    else:
        dep_city_code, dep_city_name = DEPARTURE_CITY_CODE, DEPARTURE_CITY_NAME

    # 获取出行时段
    if args.dates:
        periods = get_periods_for_dates(args.dates)
    else:
        periods = get_all_travel_periods(only_holidays=args.holidays_only)

    if not periods:
        print("未找到需要搜索的出行时段。")
        return

    if args.next_only or args.test:
        periods = periods[:1]

    print_search_plan(periods, dep_city_name)

    # 启动浏览器
    driver = None
    tmp_profile = None
    try:
        driver, tmp_profile = init_browser(headless=args.headless)

        # 第 1 步: 打开 fuzzysearch 页面，捕获 API 请求模板
        api_template = discover_api(driver)

        if api_template:
            logger.info("API 模板捕获成功，将通过 API 重放搜索（出发城市=%s）", dep_city_name)
            if api_template.get("body"):
                logger.debug("API 请求体: %s", json.dumps(api_template["body"], ensure_ascii=False)[:500])
        else:
            logger.warning("未捕获到 API 模板，将使用页面导航模式（出发城市取决于页面默认值）")

        # 第 2 步: 逐时段搜索（每个时段只请求一次）
        all_period_results = {}

        for i, period in enumerate(periods, 1):
            period_name = period["name"]
            depart_dates = period["depart_dates"]
            trip_days = calculate_trip_days(period)

            logger.info(
                "=== [%d/%d] %s (出发: %s~%s, 出行: %s~%s天) ===",
                i, len(periods), period_name,
                depart_dates[0], depart_dates[-1],
                trip_days[0], trip_days[-1],
            )

            # 每个假期只请求一次
            results = search_fuzzysearch(
                driver, api_template,
                dep_city_code, dep_city_name,
                period,
            )

            if results:
                # 统一过滤
                results = filter_results(
                    results,
                    max_price=args.max_price,
                    min_price=args.min_price,
                    min_stay=args.min_stay,
                    max_stay=args.max_stay,
                )
                logger.info("    → 过滤后 %d 条航线数据", len(results))
            else:
                logger.warning("    → 未获取到数据")

            all_period_results[period_name] = results
            logger.info("=== %s 搜索完成, 共 %d 条数据 ===\n", period_name, len(results))

        # 输出结果
        print_results(all_period_results, dep_city_name)

    except KeyboardInterrupt:
        print("\n\n用户中断搜索 (Ctrl+C)")
    except WebDriverException as e:
        logger.error("浏览器异常: %s", e)
    finally:
        if driver:
            try:
                driver.service.stop()
            except Exception:
                pass
        if tmp_profile and os.path.isdir(tmp_profile):
            shutil.rmtree(tmp_profile, ignore_errors=True)

