"""
携程 FuzzySearch 多人同行搜索

负责: 搜索多个出发城市、找共同目的地、构建旅客记录、计算同游时间、核心编排。
"""
import logging
import random
import time
from datetime import datetime

from config import CITY_SLEEP_MIN, CITY_SLEEP_MAX, RAIL_THRESHOLD_KM, RAIL_PRICE_PER_KM
from date_utils import calculate_trip_days
from shared import CITY_COORDS, haversine_km, count_leave_days, parse_date
from discover_api import search_fuzzysearch
from discover_parse import filter_results
from discover_print import print_group_results, print_group_detail

logger = logging.getLogger(__name__)

__all__ = ["run_group_search"]


def _search_all_travelers(driver, api_template, travelers, period):
    """搜索每个出发城市的航班，返回 {traveler_name: {dest_key: result}}"""
    city_results = {}
    for idx, (code, name) in enumerate(travelers):
        if idx > 0:
            delay = random.uniform(CITY_SLEEP_MIN, CITY_SLEEP_MAX)
            logger.info("  等待 %.0f 秒后搜索 %s 出发...", delay, name)
            time.sleep(delay)

        logger.info("  搜索 %s 出发的航班...", name)
        results = search_fuzzysearch(driver, api_template, code, name, period)

        dest_map = {}
        for r in (results or []):
            key = r["city_code"] or r["city_name"]
            if key not in dest_map or r["price"] < dest_map[key]["price"]:
                dest_map[key] = r
        city_results[name] = dest_map
        logger.info("    → %s: %d 个目的地", name, len(dest_map))

    return city_results


def _find_common_destinations(travelers, city_results):
    """找到所有人都有航班/本地的共同目的地 key 集合"""
    traveler_home_keys = {}
    for code, name in travelers:
        traveler_home_keys[name] = {code, name}

    all_dest_keys = set()
    for dest_map in city_results.values():
        all_dest_keys.update(dest_map.keys())

    common_keys = set()
    for key in all_dest_keys:
        is_common = True
        for code, name in travelers:
            has_result = key in city_results.get(name, {})
            is_home = key in traveler_home_keys[name]
            if not has_result and not is_home:
                is_common = False
                break
        if is_common:
            common_keys.add(key)

    return common_keys, traveler_home_keys


def _build_traveler_record(name, key, city_results, traveler_home_keys):
    """
    为某个旅客构建某目的地的记录。
    处理本地（出发地=目的地）和高铁替代逻辑。
    返回 (record, ok)，ok=False 表示该目的地对该旅客无效。
    """
    r = city_results.get(name, {}).get(key)

    if not r:
        is_home = key in traveler_home_keys[name]
        if is_home:
            ref = None
            for other_name, dest_map in city_results.items():
                if key in dest_map:
                    ref = dest_map[key]
                    break
            if not ref:
                return None, False
            r = dict(ref)
            r["price"] = 0
            r["is_local"] = True
            r["is_rail"] = False
            r["flight_no"] = ""
            r["airline"] = ""
            r["ret_flight_no"] = ""
            r["ret_airline"] = ""
            return r, True
        return None, False

    r = dict(r)  # 浅拷贝避免污染原始数据
    if not r.get("is_local"):
        dep_coord = CITY_COORDS.get(name)
        dest_coord = CITY_COORDS.get(r["city_name"])
        dist = 0
        if dep_coord and dest_coord:
            dist = haversine_km(dep_coord[0], dep_coord[1], dest_coord[0], dest_coord[1])

        if dist > 0 and dist < RAIL_THRESHOLD_KM:
            rail_price = int(RAIL_PRICE_PER_KM * dist)
            r["price"] = rail_price
            r["is_rail"] = True
            r["rail_dist"] = int(dist)
            r["flight_no"] = ""
            r["airline"] = ""
            r["ret_flight_no"] = ""
            r["ret_airline"] = ""
        else:
            r["is_rail"] = False

    return r, True


def _compute_together_time(traveler_data, traveler_names, first_result):
    """
    计算飞行人员的日期交集、同游天数、同游时段、统一请假天数。
    返回 (together_days, latest_go, earliest_back, together_range, valid)
    valid=False 表示飞行人员日期无交集，应跳过此目的地。
    """
    arrive_times = []
    depart_times = []
    go_dates = []
    back_dates = []

    for name in traveler_names:
        r = traveler_data[name]
        if r.get("is_rail") or r.get("is_local"):
            continue

        go_d = parse_date(r.get("go_date"))
        back_d = parse_date(r.get("back_date"))

        if go_d:
            go_dates.append(go_d)
        if back_d:
            back_dates.append(back_d)

        arr_str = r.get("arr_time", "")
        if arr_str:
            try:
                arrive_times.append(datetime.fromisoformat(arr_str))
            except (ValueError, TypeError):
                pass
        ret_dep_str = r.get("ret_dep_time", "")
        if ret_dep_str:
            try:
                depart_times.append(datetime.fromisoformat(ret_dep_str))
            except (ValueError, TypeError):
                pass

    # 日期交集
    if go_dates and back_dates:
        latest_go = max(go_dates)
        earliest_back = min(back_dates)
        together_days = (earliest_back - latest_go).days
        if together_days <= 0:
            return 0, None, None, "-", False
    else:
        latest_go = None
        earliest_back = None
        together_days = first_result.get("stay_days", 0) if first_result else 0

    # 统一请假天数
    flyer_leave_list = []
    for name, r in traveler_data.items():
        if r.get("is_rail") or r.get("is_local"):
            continue
        go_d = parse_date(r.get("go_date"))
        back_d = parse_date(r.get("back_date"))
        if go_d and back_d:
            flyer_leave_list.append(count_leave_days(go_d, back_d))
    unified_leave = min(flyer_leave_list) if flyer_leave_list else 0
    for r in traveler_data.values():
        r["personal_leave"] = unified_leave

    # 同游时段字符串
    if arrive_times and depart_times:
        t_start = max(arrive_times)
        t_end = min(depart_times)
        together_range = f"{t_start.strftime('%m/%d %H:%M')}~{t_end.strftime('%m/%d %H:%M')}"
    else:
        together_range = "-"

    return together_days, latest_go, earliest_back, together_range, True


def run_group_search(driver, api_template, travelers, periods, args):
    """多人同行搜索核心逻辑"""
    traveler_names = [name for _, name in travelers]
    group_label = "+".join(traveler_names)
    all_period_results = {}

    for i, period in enumerate(periods, 1):
        period_name = period["name"]
        depart_dates = period["depart_dates"]
        trip_days = calculate_trip_days(period)

        logger.info(
            "=== [%d/%d] %s (出发: %s~%s, 出行: %s~%s天) — 同行: %s ===",
            i, len(periods), period_name,
            depart_dates[0], depart_dates[-1],
            trip_days[0], trip_days[-1], group_label,
        )

        # 搜索所有出发城市
        city_results = _search_all_travelers(driver, api_template, travelers, period)
        if not city_results:
            all_period_results[period_name] = []
            continue

        # 找共同目的地
        common_keys, traveler_home_keys = _find_common_destinations(travelers, city_results)
        if not common_keys:
            logger.warning("  无共同目的地")
            all_period_results[period_name] = []
            continue

        # 组合每个目的地的结果
        combined = []
        for key in common_keys:
            traveler_data = {}
            total_price = 0
            first_result = None
            all_have_data = True

            for code, name in travelers:
                r, ok = _build_traveler_record(name, key, city_results, traveler_home_keys)
                if not ok:
                    all_have_data = False
                    break
                if not first_result:
                    first_result = r
                traveler_data[name] = r
                total_price += r["price"]

            if not all_have_data:
                continue

            together_days, latest_go, earliest_back, together_range, valid = \
                _compute_together_time(traveler_data, traveler_names, first_result)
            if not valid:
                continue

            combined.append({
                "dest_key": key,
                "city_name": first_result["city_name"],
                "city_code": first_result["city_code"],
                "province": first_result.get("province", ""),
                "total_price": total_price,
                "avg_price": total_price // len(travelers),
                "go_date": str(latest_go) if latest_go else first_result.get("go_date", ""),
                "back_date": str(earliest_back) if earliest_back else first_result.get("back_date", ""),
                "stay_days": together_days,
                "together_range": together_range,
                "tags": first_result.get("tags", []),
                "travelers": traveler_data,
            })

        # 排序 + 过滤
        combined.sort(key=lambda x: x["total_price"])
        min_together = getattr(args, "min_together", 2)
        if min_together > 0:
            combined = [c for c in combined if c["stay_days"] >= min_together]
        if args.max_price > 0:
            combined = [c for c in combined if c["total_price"] <= args.max_price]

        logger.info("  共同目的地 %d 个（过滤后 %d 个）", len(common_keys), len(combined))
        all_period_results[period_name] = combined

    # 输出
    print_group_results(all_period_results, traveler_names)
    print_group_detail(all_period_results, traveler_names)
