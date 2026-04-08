"""
携程 FuzzySearch 响应解析、过滤、去重

负责: 解析 API 响应 JSON、提取航班/路线信息、结果过滤、距离过滤、去重。
"""
import logging
from datetime import date

from shared import CITY_COORDS, haversine_km, count_leave_days, fmt_duration, fmt_time

logger = logging.getLogger(__name__)

__all__ = [
    "parse_fuzzy_response",
    "filter_results",
    "deduplicate_results",
]


def _extract_flight(fl):
    """从携程航班 dict 中提取标准化航班信息"""
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


def _parse_single_route(route, sdate, allow_intl=False):
    """解析单条路线数据 - 基于携程 fuzzysearch 真实 API 响应格式
    allow_intl: False=仅国内, True=国内+国际, "only"=仅国际
    """
    if not isinstance(route, dict):
        return None

    is_intl = route.get("isIntl", False)
    if allow_intl == "only" and not is_intl:
        return None  # 国际专属模式：跳过国内航线
    if not allow_intl and is_intl:
        return None  # 国内模式：跳过国际航线

    # 目的地信息
    arr_city = route.get("arriveCity", {})
    city_name = arr_city.get("name", "")
    city_code = arr_city.get("code", "")
    province = arr_city.get("provinceName", "") or arr_city.get("countryName", "")
    arr_intl = arr_city.get("isIntl", False)
    if allow_intl == "only" and not arr_intl:
        return None
    if not allow_intl and arr_intl:
        return None
    if not city_name:
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

            # 计算休假天数（使用缓存的假期日期集合）
            leave_days = count_leave_days(d1, d2)
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


def parse_fuzzy_response(data, sdate, allow_intl=False):
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
        parsed = _parse_single_route(route, sdate, allow_intl=allow_intl)
        if parsed:
            results.append(parsed)

    if routes and not results:
        logger.warning("  [诊断] 有 %d 条路线但全部解析失败", len(routes))

    return results


def filter_results(results, max_price=0, min_price=0, min_stay=0, max_stay=0,
                    dep_city_name="", min_dist=0, max_dist=0,
                    min_flight_time=0, max_flight_time=0):
    """
    统一过滤搜索结果（单次遍历 predicate 管线）
    所有阈值为 0 表示不过滤。距离过滤因需要 logging 排除信息，保持为后置步骤。
    """
    # 构建 predicate 列表 — 只添加实际需要的条件
    predicates = []
    if min_price > 0:
        predicates.append(lambda r: r["price"] >= min_price)
    if max_price > 0:
        predicates.append(lambda r: 0 < r["price"] <= max_price)
    if min_stay > 0:
        predicates.append(lambda r: r["stay_days"] >= min_stay)
    if max_stay > 0:
        predicates.append(lambda r: 0 < r["stay_days"] <= max_stay)
    if min_flight_time > 0:
        predicates.append(lambda r: r.get("duration", 0) >= min_flight_time)
    if max_flight_time > 0:
        predicates.append(lambda r: 0 < r.get("duration", 0) <= max_flight_time)

    # 单次遍历应用所有 predicate
    if predicates:
        results = [r for r in results if all(p(r) for p in predicates)]

    # 距离过滤因需要 logging 排除信息，保持为单独的后置步骤
    if (min_dist > 0 or max_dist > 0) and dep_city_name:
        results = _filter_by_distance(results, dep_city_name, min_dist, max_dist)

    return results


def _filter_by_distance(results, dep_city_name, min_dist, max_dist):
    """按城市距离过滤结果"""
    dep_coord = CITY_COORDS.get(dep_city_name)
    if not dep_coord:
        return results
    filtered = []
    for r in results:
        coord = CITY_COORDS.get(r["city_name"])
        if not coord:
            filtered.append(r)  # 未知坐标的城市保留
            continue
        dist = haversine_km(dep_coord[0], dep_coord[1], coord[0], coord[1])
        if min_dist > 0 and dist < min_dist:
            logger.info("  排除 %s (距%s %.0f km < %d km)", r["city_name"], dep_city_name, dist, min_dist)
            continue
        if max_dist > 0 and dist > max_dist:
            logger.info("  排除 %s (距%s %.0f km > %d km)", r["city_name"], dep_city_name, dist, max_dist)
            continue
        filtered.append(r)
    return filtered


def deduplicate_results(results):
    """去重: 同一目的地保留最低价"""
    best = {}
    for r in results:
        key = r["city_code"] or r["city_name"]
        if key not in best or (r["price"] > 0 and r["price"] < best[key]["price"]):
            best[key] = r
    return sorted(best.values(), key=lambda x: x["price"])
