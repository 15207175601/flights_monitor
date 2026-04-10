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


_EMPTY_FLIGHT = {
    "flight_no": "", "airline": "", "dep_airport": "", "arr_airport": "",
    "dep_time": "", "arr_time": "", "duration": 0,
    "transfer_time": 0, "transfer_count": 0, "transfer_cities": [],
}


def _extract_flights(flight_list):
    """从同一方向的多段航班列表中提取合并航班信息

    对于直达航班 (1段)：与之前行为一致。
    对于中转航班 (多段)：合并航班号、累加飞行耗时、计算中转等待时间。
    """
    if not flight_list:
        return dict(_EMPTY_FLIGHT)

    # 按 sequence 排序确保正确顺序
    flight_list = sorted(flight_list, key=lambda f: f.get("sequence", 0))

    first = flight_list[0]
    last = flight_list[-1]

    # 航班号：多段用 → 连接
    flight_nos = [f.get("flightNo", "") for f in flight_list if f.get("flightNo")]
    airlines = []
    seen_airlines = set()
    for f in flight_list:
        a = f.get("airline", {})
        name = a.get("name", "") if isinstance(a, dict) else ""
        if name and name not in seen_airlines:
            airlines.append(name)
            seen_airlines.add(name)

    # 出发/到达：取第一段出发、最后一段到达
    first_dport = first.get("dport", {})
    last_aport = last.get("aport", {})

    # 飞行耗时：各段 duration 之和
    fly_duration = sum(f.get("duration", 0) for f in flight_list)

    # 中转耗时：相邻两段之间的等待时间（到达→下一段出发）
    transfer_time = 0
    transfer_cities = []
    for i in range(len(flight_list) - 1):
        cur_atime = flight_list[i].get("atime", "")
        nxt_dtime = flight_list[i + 1].get("dtime", "")
        cur_aport = flight_list[i].get("aport", {})
        city = cur_aport.get("cityName", cur_aport.get("name", ""))
        if city:
            transfer_cities.append(city)
        if cur_atime and nxt_dtime:
            from shared import parse_datetime
            t1 = parse_datetime(cur_atime.replace(" ", "T") if "T" not in cur_atime else cur_atime)
            t2 = parse_datetime(nxt_dtime.replace(" ", "T") if "T" not in nxt_dtime else nxt_dtime)
            if t1 and t2:
                transfer_time += max(0, int((t2 - t1).total_seconds() / 60))

    return {
        "flight_no": "→".join(flight_nos) if flight_nos else "",
        "airline": "/".join(airlines) if airlines else "",
        "dep_airport": first_dport.get("fullName", first_dport.get("name", "")),
        "arr_airport": last_aport.get("fullName", last_aport.get("name", "")),
        "dep_time": first.get("dtime", ""),
        "arr_time": last.get("atime", ""),
        "duration": fly_duration,
        "transfer_time": transfer_time,
        "transfer_count": len(flight_list) - 1,
        "transfer_cities": transfer_cities,
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
    # 同一 segment 可能有多段（中转航班），按 sequence 排序后合并
    flights = route.get("flights", [])
    go_flights = []
    ret_flights = []
    for fl in flights:
        seg = fl.get("segment", 0)
        if seg == 1:
            go_flights.append(fl)
        elif seg == 2:
            ret_flights.append(fl)

    # 如果没有 segment 标记，按顺序取
    if not go_flights and flights:
        go_flights = [flights[0]]
    if not ret_flights and len(flights) > 1:
        ret_flights = [flights[-1]]

    go_info = _extract_flights(go_flights)
    ret_info = _extract_flights(ret_flights)

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
        "transfer_time": go_info["transfer_time"],
        "transfer_count": go_info["transfer_count"],
        "transfer_cities": go_info["transfer_cities"],
        # 返程
        "ret_flight_no": ret_info["flight_no"],
        "ret_airline": ret_info["airline"],
        "ret_dep_airport": ret_info["dep_airport"],
        "ret_arr_airport": ret_info["arr_airport"],
        "ret_dep_time": ret_info["dep_time"],
        "ret_arr_time": ret_info["arr_time"],
        "ret_duration": ret_info["duration"],
        "ret_transfer_time": ret_info["transfer_time"],
        "ret_transfer_count": ret_info["transfer_count"],
        "ret_transfer_cities": ret_info["transfer_cities"],
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
