"""
携程 FuzzySearch API 捕获与重放

负责: 打开 fuzzysearch 页面拦截 API、修改请求体、反爬检测、API 重放、搜索入口。
"""
import copy
import json
import logging
import os
import random
import time

from config import PAGE_LOAD_WAIT, MAX_RETRY, REQUEST_DELAY
from browser import wait_for_api_response
from date_utils import calculate_trip_days

logger = logging.getLogger(__name__)

__all__ = [
    "FUZZYSEARCH_PAGE",
    "discover_api",
    "replay_api",
    "search_fuzzysearch",
]

# === 常量 ===
FUZZYSEARCH_PAGE = "https://flights.ctrip.com/fuzzysearch/search"


def discover_api(driver):
    """
    打开 fuzzysearch 页面，拦截页面自身发出的 API 请求，
    返回 API 模板 (url, method, headers, body_dict) 供后续重放
    """
    logger.info("打开 fuzzysearch 页面，捕获 API 请求模板...")
    driver.get(FUZZYSEARCH_PAGE)

    # 等待页面加载并发出 API 请求（替代固定 sleep(8)）
    if not wait_for_api_response(
        driver,
        "return (window.__fuzzyRequests && window.__fuzzyRequests.length > 0)",
        timeout=PAGE_LOAD_WAIT,
    ):
        logger.warning("等待 API 请求模板超时，尝试继续...")
    time.sleep(1)  # 额外短暂等待确保请求完整

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


def _modify_request_body(body, dep_city_code, dep_city_name, date_begin, date_end, trip_days, acs_list=None):
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

    modified = copy.deepcopy(body)

    # 1. 设置往返: tt=2
    modified["tt"] = 2

    # 2. 修改 segments
    segments = modified.get("segments", [])
    if segments and isinstance(segments[0], dict):
        seg = segments[0]

        # 修改出发城市 dcs
        seg["dcs"] = [{"ct": 1, "code": dep_city_code, "name": dep_city_name}]

        # 修改目的地 acs（国际模式）
        if acs_list:
            seg["acs"] = acs_list

        # 修改日期范围 drl — 窄范围，仅覆盖假期出发日期
        seg["drl"] = [{"begin": f"{date_begin.year}-{date_begin.month}-{date_begin.day}",
                        "end": f"{date_end.year}-{date_end.month}-{date_end.day}"}]

        # 设置出行天数 sr (stayRange)
        if trip_days:
            seg["sr"] = {"min": min(trip_days), "max": max(trip_days)}

    return modified


def _detect_anti_crawl(data, raw_text=""):
    """
    检测反爬响应，返回描述字符串（被拦截时）或 None（正常）。
    检查项：HTTP 错误码、验证码关键词、加密 data 字段、空路由 + 错误状态。
    """
    if not isinstance(data, dict):
        return None

    # 1. 响应中的 HTTP 状态码检测
    code = data.get("code") or data.get("statusCode") or data.get("status")
    if code in (403, 429, "403", "429"):
        return f"HTTP {code} 被限流/封禁"

    # 2. 响应消息中的反爬关键词
    msg = str(data.get("msg", "") or data.get("message", "") or "")
    anti_keywords = ["验证", "频繁", "限制", "forbidden", "rate limit", "blocked", "captcha"]
    for kw in anti_keywords:
        if kw.lower() in msg.lower():
            return f"响应消息含反爬关键词: {msg[:100]}"

    # 3. data 字段为加密字符串（非正常 JSON 结构）
    d = data.get("data")
    if isinstance(d, str) and len(d) > 50 and not d.startswith("{"):
        return "data 字段为加密内容，疑似被风控拦截"

    # 4. ResponseStatus 中的错误
    rs = data.get("ResponseStatus", {})
    if isinstance(rs, dict):
        ack = rs.get("Ack", "")
        if ack and str(ack).lower() in ("failure", "error"):
            rs_msg = rs.get("Message", "")
            return f"ResponseStatus.Ack={ack}: {rs_msg[:100]}"

    return None


def replay_api(driver, api_template, dep_city_code, dep_city_name, date_begin, date_end, trip_days, acs_list=None):
    """
    用修改后的参数重放 API 请求（带重试）
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
        modified_body = _modify_request_body(body, dep_city_code, dep_city_name, date_begin, date_end, trip_days, acs_list=acs_list)
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

    for attempt in range(1, MAX_RETRY + 2):
        try:
            driver.set_script_timeout(20)
            result = driver.execute_async_script(
                js_code, url, method, headers_json, body_json
            )
            if result:
                return result
        except Exception as e:
            logger.warning("  API 重放失败 (尝试 %d/%d): %s", attempt, MAX_RETRY + 1, e)

        if attempt <= MAX_RETRY:
            delay = 2 ** attempt + random.uniform(0, 1)
            logger.info("  等待 %.1f 秒后重试...", delay)
            time.sleep(delay)

    return None


def search_fuzzysearch(driver, api_template, dep_city_code, dep_city_name, period, acs_list=None):
    """
    执行一次 fuzzysearch 搜索（通过 API 重放）
    每个假期/周末只请求一次，日期范围覆盖该时段所有出发日
    """
    from discover_parse import parse_fuzzy_response

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
                         date_begin, date_end, trip_days, acs_list=acs_list)
        if raw:
            try:
                data = json.loads(raw)

                # 反爬检测
                blocked = _detect_anti_crawl(data, raw)
                if blocked:
                    logger.warning("  [反爬] %s，跳过本次请求", blocked)
                    return results

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
                    allow_intl = "only" if acs_list else False
                    results = parse_fuzzy_response(data, sdate, allow_intl=allow_intl)
                    if results:
                        logger.info("    → API 重放获取到 %d 条航线", len(results))
                        return results
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("  API 响应解析失败: %s | 前200字符: %s", e, str(raw)[:200])

    # 方式 2: API 重放失败时回退到页面导航 + 拦截
    logger.info("  回退到页面导航模式...")
    try:
        driver.get(FUZZYSEARCH_PAGE)
        wait_for_api_response(
            driver,
            "return (window.__fuzzyResponses && window.__fuzzyResponses.length > 0)",
            timeout=PAGE_LOAD_WAIT,
        )
        time.sleep(1)

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
