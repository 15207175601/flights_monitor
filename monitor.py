#!/usr/bin/env python3
"""
携程特价机票逐城精确监控模块
自动从携程发现指定城市出发的全国航线，监测节假日特价机票（经济舱 ≤ 4折）
搜索每个假期的完整日期范围（最早出发日~假期首日, 假期末日~最晚返程日）

由 main.py monitor 子命令调用
"""
import sys
import os
import logging
import math
import json
import random
import time
from datetime import date, datetime, timedelta

# 确保能导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    DEPARTURE_CITY_CODE,
    DEPARTURE_CITY_NAME,
    MAX_DISCOUNT_RATE,
    MIN_DISTANCE_KM,
)
from date_utils import get_all_travel_periods, get_periods_for_dates
from ctrip_api import CtripFlightClient
from discover import resolve_city

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 主要城市坐标 (纬度, 经度)
_CITY_COORDS = {
    "北京": (39.90, 116.41), "上海": (31.23, 121.47), "广州": (23.13, 113.26),
    "深圳": (22.54, 114.06), "成都": (30.57, 104.07), "杭州": (30.27, 120.15),
    "武汉": (30.59, 114.31), "西安": (34.26, 108.94), "重庆": (29.56, 106.55),
    "南京": (32.06, 118.80), "天津": (39.13, 117.20), "长沙": (28.23, 112.94),
    "沈阳": (41.80, 123.43), "哈尔滨": (45.75, 126.65), "大连": (38.91, 121.60),
    "济南": (36.65, 116.99), "青岛": (36.07, 120.38), "郑州": (34.75, 113.65),
    "昆明": (25.04, 102.71), "厦门": (24.48, 118.09), "合肥": (31.82, 117.23),
    "南昌": (28.68, 115.86), "福州": (26.07, 119.31), "太原": (37.87, 112.55),
    "南宁": (22.82, 108.32), "贵阳": (26.65, 106.63), "海口": (20.04, 110.35),
    "三亚": (18.25, 109.50), "兰州": (36.06, 103.83), "乌鲁木齐": (43.83, 87.62),
    "呼和浩特": (40.84, 111.75), "石家庄": (38.04, 114.51), "长春": (43.88, 125.32),
    "拉萨": (29.65, 91.13), "银川": (38.49, 106.23), "西宁": (36.62, 101.78),
    "宁波": (29.87, 121.55), "温州": (28.00, 120.67), "烟台": (37.46, 121.45),
    "威海": (37.51, 122.12), "泉州": (24.87, 118.68), "珠海": (22.27, 113.58),
    "北海": (21.47, 109.12), "桂林": (25.27, 110.29), "丽江": (26.87, 100.23),
    "洛阳": (34.62, 112.45), "宜昌": (30.69, 111.29), "岳阳": (29.36, 113.09),
    "揭阳": (23.55, 116.37), "绵阳": (31.47, 104.74), "赤峰": (42.26, 118.96),
    "连云港": (34.60, 119.22), "通辽": (43.65, 122.26), "满洲里": (49.60, 117.38),
    "包头": (40.66, 109.84), "鄂尔多斯": (39.61, 109.78), "锡林浩特": (43.97, 116.09),
    "嘉峪关": (39.77, 98.29), "临沂": (35.10, 118.36), "柳州": (24.33, 109.41),
    "武夷山": (27.76, 118.04), "湛江": (21.27, 110.36),
}

# 主要城市携程城市代码（用于 --from 参数指定出发城市）
_CITY_CODES = {
    "北京": "BJS", "上海": "SHA", "广州": "CAN", "深圳": "SZX", "成都": "CTU",
    "杭州": "HGH", "武汉": "WUH", "西安": "SIA", "重庆": "CKG", "南京": "NKG",
    "天津": "TSN", "长沙": "CSX", "沈阳": "SHE", "哈尔滨": "HRB", "大连": "DLC",
    "济南": "TNA", "青岛": "TAO", "郑州": "CGO", "昆明": "KMG", "厦门": "XMN",
    "合肥": "HFE", "南昌": "KHN", "福州": "FOC", "太原": "TYN", "南宁": "NNG",
    "贵阳": "KWE", "海口": "HAK", "三亚": "SYX", "兰州": "LHW", "乌鲁木齐": "URC",
    "呼和浩特": "HET", "石家庄": "SJW", "长春": "CGQ", "拉萨": "LXA", "银川": "INC",
    "西宁": "XNN", "宁波": "NGB", "温州": "WNZ", "烟台": "YNT", "威海": "WEH",
    "泉州": "JJN", "珠海": "ZUH", "北海": "BHY", "桂林": "KWL", "丽江": "LJG",
    "洛阳": "LYA", "宜昌": "YIH", "揭阳": "SWA", "绵阳": "MIG", "赤峰": "CIF",
    "连云港": "LYG", "通辽": "TGO", "满洲里": "NZH", "包头": "BAV", "鄂尔多斯": "DSN",
    "锡林浩特": "XIL", "嘉峪关": "JGN", "临沂": "LYI", "柳州": "LZH",
    "武夷山": "WUS", "湛江": "ZHA", "岳阳": "YYA",
}


def _haversine_km(lat1, lon1, lat2, lon2):
    """计算两个坐标之间的大圆距离（公里）"""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def filter_by_distance(destinations, dep_city_name, min_km):
    """过滤掉距离出发城市太近的目的地"""
    dep_coord = _CITY_COORDS.get(dep_city_name)
    if not dep_coord:
        return destinations

    filtered = {}
    for code, name in destinations.items():
        coord = _CITY_COORDS.get(name)
        if not coord:
            filtered[code] = name  # 未知坐标的城市保留
            continue
        dist = _haversine_km(dep_coord[0], dep_coord[1], coord[0], coord[1])
        if dist >= min_km:
            filtered[code] = name
        else:
            logger.info("  排除 %s (距%s %.0f km < %d km)", name, dep_city_name, dist, min_km)
    return filtered


# === 断点续搜 ===
_CHECKPOINT_DIR = os.path.dirname(os.path.abspath(__file__))
_CHECKPOINT_FILE = os.path.join(_CHECKPOINT_DIR, ".search_checkpoint.json")

# 连续空结果阈值：超过此数判定为被反爬封禁
MAX_CONSECUTIVE_EMPTY = 5


def _save_checkpoint(data):
    """保存搜索进度到文件"""
    try:
        with open(_CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        logger.debug("进度已保存: %s", _CHECKPOINT_FILE)
    except Exception as e:
        logger.warning("保存进度失败: %s", e)


def _load_checkpoint():
    """加载上次搜索进度"""
    if not os.path.exists(_CHECKPOINT_FILE):
        return None
    try:
        with open(_CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("加载进度失败: %s", e)
        return None


def _clear_checkpoint():
    """搜索完成后清除进度文件"""
    if os.path.exists(_CHECKPOINT_FILE):
        os.remove(_CHECKPOINT_FILE)


def _parse_dt(dt_str):
    """解析携程 API 返回的日期时间字符串"""
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None


def _fmt_time(dt_str):
    """从日期时间字符串中提取 HH:MM"""
    dt = _parse_dt(dt_str)
    return dt.strftime("%H:%M") if dt else "-"


class SearchAborted(Exception):
    """搜索被中止（连续空结果过多，疑似被封禁）"""
    pass


def search_flights_for_period(client, period, destinations, dep_city_code, dep_city_name,
                               consecutive_empty=0, on_city_done=None):
    """搜索某个假期时段内所有目的地的往返航班（遍历所有候选日期）
    Args:
        on_city_done: 回调函数(city_code, results, completed_cities)，每完成一个城市调用一次
    Returns: (results_list, completed_city_codes_set, consecutive_empty_count)
    Raises: SearchAborted if consecutive empty results exceed threshold
    """
    results = []
    completed_cities = set()
    depart_dates = period["depart_dates"]
    return_dates = period["return_dates"]
    dest_total = len(destinations)

    dep_range_str = f"{depart_dates[0]}~{depart_dates[-1]}"
    ret_range_str = f"{return_dates[0]}~{return_dates[-1]}"

    for idx, (city_code, city_name) in enumerate(destinations.items(), 1):
        # 搜索所有候选出发日的去程航班
        all_outbound = []
        for d in depart_dates:
            ds = d.strftime("%Y-%m-%d")
            logger.info(
                "  [%d/%d] %s -> %s  去程 %s",
                idx, dest_total, dep_city_name, city_name, ds,
            )
            flights, got_response = client.search_oneway(
                dep_city_code, city_code,
                dep_city_name, city_name, ds,
            )
            if flights or got_response:
                # 有航班数据，或者API正常响应只是该航线无航班，都重置计数器
                consecutive_empty = 0
            else:
                # 完全没有拦截到API响应，才算疑似被封
                consecutive_empty += 1
                if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                    logger.error(
                        "连续 %d 次完全未收到API响应，疑似被反爬封禁，中止搜索",
                        consecutive_empty,
                    )
                    raise SearchAborted(f"连续 {consecutive_empty} 次无API响应")
            all_outbound.extend(flights)

        # 搜索所有候选返程日的回程航班
        all_inbound = []
        for d in return_dates:
            ds = d.strftime("%Y-%m-%d")
            logger.info(
                "  [%d/%d] %s -> %s  回程 %s",
                idx, dest_total, city_name, dep_city_name, ds,
            )
            flights, got_response = client.search_oneway(
                city_code, dep_city_code,
                city_name, dep_city_name, ds,
            )
            if flights or got_response:
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                    logger.error(
                        "连续 %d 次完全未收到API响应，疑似被反爬封禁，中止搜索",
                        consecutive_empty,
                    )
                    raise SearchAborted(f"连续 {consecutive_empty} 次无API响应")
            all_inbound.extend(flights)

        completed_cities.add(city_code)

        # 过滤：只保留折扣 ≤ 4折 的经济舱
        cheap_out = [f for f in all_outbound if 0 < f["discount_rate"] <= MAX_DISCOUNT_RATE]
        cheap_in = [f for f in all_inbound if 0 < f["discount_rate"] <= MAX_DISCOUNT_RATE]

        # 找最便宜的有效往返组合（返程出发 >= 去程到达 + 24h）
        if cheap_out and cheap_in:
            best_pair = None
            best_total = float("inf")
            for out in cheap_out:
                out_arr = _parse_dt(out["arr_time"])
                if not out_arr:
                    continue
                for inb in cheap_in:
                    inb_dep = _parse_dt(inb["dep_time"])
                    if not inb_dep:
                        continue
                    if inb_dep >= out_arr + timedelta(hours=24):
                        pair_price = out["price"] + inb["price"]
                        if pair_price < best_total:
                            best_total = pair_price
                            best_pair = (out, inb)

            if best_pair:
                results.append({
                    "city": city_name,
                    "period_name": period["name"],
                    "depart_range": dep_range_str,
                    "return_range": ret_range_str,
                    "best_outbound": best_pair[0],
                    "best_inbound": best_pair[1],
                    "total_price": int(best_total),
                    "outbound_count": len(cheap_out),
                    "inbound_count": len(cheap_in),
                })
                logger.info(
                    "    -> 找到特价! %s 去程 %d 个, 回程 %d 个, 最低往返 ¥%d",
                    city_name, len(cheap_out), len(cheap_in), best_total,
                )

        # 每完成一个城市立即回调保存进度
        if on_city_done:
            on_city_done(city_code, results, completed_cities)

        # 每完成一个城市后随机休息 30-60 秒，降低反爬风险（最后一个城市不休息）
        if idx < dest_total:
            sleep_sec = random.randint(30, 60)
            logger.info("  休息 %d 秒后继续...", sleep_sec)
            time.sleep(sleep_sec)

    return results, completed_cities, consecutive_empty


def print_results(all_results, dep_city_name):
    """格式化输出搜索结果"""
    if not all_results:
        print("\n" + "=" * 60)
        print("未找到满足条件的特价机票（经济舱 ≤ 4折）")
        print("=" * 60)
        return

    all_results.sort(key=lambda x: x["best_outbound"]["discount_rate"])

    print(f"\n# 携程特价机票监测结果 - 经济舱 ≤ {MAX_DISCOUNT_RATE * 10:.0f}折")
    print(f"\n> 出发城市: {dep_city_name} | 查询时间: {date.today()}")

    # 按假期分组显示
    periods_seen = {}
    for r in all_results:
        key = r["period_name"]
        if key not in periods_seen:
            periods_seen[key] = []
        periods_seen[key].append(r)

    for period_name, results in periods_seen.items():
        results.sort(key=lambda x: x["best_outbound"]["discount_rate"])
        dep_range = results[0]['depart_range'] if results else ""
        ret_range = results[0]['return_range'] if results else ""
        print(f"\n## {period_name}（出发: {dep_range} | 返程: {ret_range}）\n")
        print("| 排名 | 目的地 | 去程航班 | 去程日期 | 起飞-到达 | 去程价格 | 折扣 | 回程航班 | 回程日期 | 起飞-到达 | 回程价格 | 折扣 | 往返总价 |")
        print("|------|--------|----------|----------|-----------|----------|------|----------|----------|-----------|----------|------|----------|")

        for rank, r in enumerate(results, 1):
            out = r["best_outbound"]
            inb = r["best_inbound"]

            out_flight = out["flight_number"] if out else "-"
            out_date = out["date"] if out else "-"
            out_price = f"¥{out['price']}" if out else "-"
            out_disc = out["discount_display"] if out else "-"
            out_dep_t = _fmt_time(out["dep_time"]) if out else "-"
            out_arr_t = _fmt_time(out["arr_time"]) if out else "-"

            inb_flight = inb["flight_number"] if inb else "-"
            inb_date = inb["date"] if inb else "-"
            inb_price = f"¥{inb['price']}" if inb else "-"
            inb_disc = inb["discount_display"] if inb else "-"
            inb_dep_t = _fmt_time(inb["dep_time"]) if inb else "-"
            inb_arr_t = _fmt_time(inb["arr_time"]) if inb else "-"

            total = f"¥{r['total_price']}"

            print(f"| {rank} | {r['city']} | {out_flight} | {out_date} | {out_dep_t}-{out_arr_t} | {out_price} | {out_disc} | {inb_flight} | {inb_date} | {inb_dep_t}-{inb_arr_t} | {inb_price} | {inb_disc} | **{total}** |")

    print(f"\n> 共找到 **{len(all_results)}** 条特价往返线路\n")


def print_period_summary(periods):
    """打印将要搜索的假期时段"""
    print("\n将搜索以下出行时段:")
    print(f"{'─' * 65}")
    print(f"  {'假期名称':<16} {'出发日期范围':<26} {'返程日期范围':<26} {'类型':<6}")
    print(f"{'─' * 65}")
    for p in periods:
        ptype = "节假日" if p["type"] == "holiday" else "周末"
        dep_range = f"{p['depart_dates'][0]} ~ {p['depart_dates'][-1]}"
        ret_range = f"{p['return_dates'][0]} ~ {p['return_dates'][-1]}"
        print(f"  {p['name']:<14} {dep_range:<24} {ret_range:<24} {ptype:<6}")
    print(f"{'─' * 65}")
    print()


def run(args):
    """monitor 子命令入口，接收 argparse Namespace"""
    # 确定出发城市（使用 discover 模块的 resolve_city）
    if args.from_city:
        dep_city_code, dep_city_name = resolve_city(args.from_city)
    else:
        dep_city_code, dep_city_name = DEPARTURE_CITY_CODE, DEPARTURE_CITY_NAME

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 获取所有需要搜索的出行时段
    if args.dates:
        periods = get_periods_for_dates(args.dates)
    else:
        periods = get_all_travel_periods(only_holidays=args.holidays_only)

    if not periods:
        print("未找到需要搜索的出行时段。")
        return

    if args.next_only or args.test:
        periods = periods[:1]

    print_period_summary(periods)

    # 初始化客户端（默认有头模式，--headless 可切换）
    client = CtripFlightClient(headless=args.headless)
    try:
        client.init_session()

        # 有头模式下先打开携程首页，等待用户完成登录
        if not args.headless:
            client.driver.get("https://www.ctrip.com/")
            wait_sec = 60
            print(f"\n已打开携程首页，请在浏览器中完成登录，{wait_sec} 秒后自动开始搜索...")
            for remaining in range(wait_sec, 0, -1):
                print(f"\r  倒计时 {remaining:>2} 秒... (登录完成可等待倒计时结束)", end="", flush=True)
                time.sleep(1)
            print("\r  登录等待结束，开始搜索。" + " " * 30)

        # 自动从携程发现目的地城市
        destinations = client.discover_destinations(dep_city_code)
        if not destinations:
            print("未能发现目的地城市，请检查网络连接。")
            return

        # 过滤距离太近的城市
        destinations = filter_by_distance(destinations, dep_city_name, MIN_DISTANCE_KM)

        # 目的地偏好过滤
        if args.dest_file:
            try:
                with open(args.dest_file, "r", encoding="utf-8") as f:
                    preferred = {line.strip() for line in f if line.strip()}
                before = len(destinations)
                destinations = {c: n for c, n in destinations.items() if n in preferred}
                ignored = preferred - set(destinations.values())
                if ignored:
                    logger.warning("偏好文件中以下城市未在航线中找到: %s", "、".join(sorted(ignored)))
                logger.info("目的地偏好过滤: %d -> %d 个城市", before, len(destinations))
                if not destinations:
                    print("偏好文件中的城市均未在可用航线中找到，请检查文件内容。")
                    return
            except FileNotFoundError:
                print(f"目的地偏好文件不存在: {args.dest_file}")
                return

        if args.test:
            destinations = dict(list(destinations.items())[:2])

        # 自动检测断点续搜（--fresh 强制从头开始）
        checkpoint = None
        completed_period_cities = {}  # {period_name: set(city_codes)}
        prev_results = []
        if not args.fresh:
            checkpoint = _load_checkpoint()
            if checkpoint and checkpoint.get("dep_city_code") == dep_city_code:
                completed_period_cities = {
                    k: set(v) for k, v in checkpoint.get("completed", {}).items()
                }
                prev_results = checkpoint.get("results", [])
                skipped = sum(len(v) for v in completed_period_cities.values())
                logger.info(
                    "检测到断点，自动恢复: 已完成 %d 个城市搜索, 已有 %d 条结果",
                    skipped, len(prev_results),
                )
            else:
                if checkpoint:
                    logger.info("断点的出发城市不匹配，将重新开始搜索")
                checkpoint = None
        elif os.path.exists(_CHECKPOINT_FILE):
            _clear_checkpoint()
            logger.info("已忽略断点文件，从头开始搜索")

        logger.info("共 %d 个出行时段, %d 个目的地城市", len(periods), len(destinations))
        dep_days = len(periods[0]["depart_dates"]) if periods else 1
        ret_days = len(periods[0]["return_dates"]) if periods else 1
        total_calls = len(periods) * len(destinations) * (dep_days + ret_days)
        est_minutes = total_calls * 5 // 60 + 1
        logger.info(
            "每个城市搜索 %d 个去程日期 + %d 个返程日期, 预计 API 调用: %d, 耗时: ~%d 分钟",
            dep_days, ret_days, total_calls, est_minutes,
        )

        # 搜索每个时段
        all_results = list(prev_results)
        consecutive_empty = 0
        aborted = False

        def _on_city_done(city_code, period_results, period_completed):
            """每完成一个城市，立即保存进度到 checkpoint 文件"""
            # 用最新的 period_results 和 period_completed 更新全局状态
            # （注意：period_results/period_completed 是 search_flights_for_period 内的累积值）
            current_all = list(prev_results) + period_results
            merged = dict(completed_period_cities)
            merged[_current_period_name] = (
                completed_period_cities.get(_current_period_name, set()) | period_completed
            )
            _save_checkpoint({
                "dep_city_code": dep_city_code,
                "dep_city_name": dep_city_name,
                "completed": {k: list(v) for k, v in merged.items()},
                "results": current_all,
                "timestamp": datetime.now().isoformat(),
            })
            logger.debug("进度已保存: %s 完成 (%d 城市, %d 结果)",
                         city_code, sum(len(v) for v in merged.values()), len(current_all))

        for i, period in enumerate(periods, 1):
            # 过滤掉已完成的城市
            done_cities = completed_period_cities.get(period["name"], set())
            remaining = {c: n for c, n in destinations.items() if c not in done_cities}
            if not remaining:
                logger.info("=== [%d/%d] %s 已完成，跳过 ===", i, len(periods), period["name"])
                continue

            if done_cities:
                logger.info(
                    "=== [%d/%d] 搜索 %s (去程: %s~%s, 回程: %s~%s) [续: 跳过已完成的 %d 个城市] ===",
                    i, len(periods), period["name"],
                    period["depart_dates"][0], period["depart_dates"][-1],
                    period["return_dates"][0], period["return_dates"][-1],
                    len(done_cities),
                )
            else:
                logger.info(
                    "=== [%d/%d] 搜索 %s (去程: %s~%s, 回程: %s~%s) ===",
                    i, len(periods), period["name"],
                    period["depart_dates"][0], period["depart_dates"][-1],
                    period["return_dates"][0], period["return_dates"][-1],
                )

            _current_period_name = period["name"]

            try:
                results, completed_cities, consecutive_empty = search_flights_for_period(
                    client, period, remaining, dep_city_code, dep_city_name,
                    consecutive_empty=consecutive_empty,
                    on_city_done=_on_city_done,
                )
                all_results.extend(results)

                # 更新已完成记录
                if period["name"] not in completed_period_cities:
                    completed_period_cities[period["name"]] = set()
                completed_period_cities[period["name"]].update(completed_cities)

            except (SearchAborted, KeyboardInterrupt) as e:
                aborted = True
                if isinstance(e, KeyboardInterrupt):
                    logger.warning("用户中断搜索 (Ctrl+C)")
                # 进度已在 on_city_done 回调中实时保存，这里只需从 checkpoint 恢复最新状态
                saved = _load_checkpoint()
                if saved:
                    all_results = saved.get("results", [])
                    completed_period_cities = {
                        k: set(v) for k, v in saved.get("completed", {}).items()
                    }
                logger.info("进度已保存，下次运行可从中断位置继续（加 --fresh 可强制从头）")
                break

        # 输出已有结果
        print_results(all_results, dep_city_name)

        if aborted:
            print(f"\n搜索未完成，进度已保存到 {_CHECKPOINT_FILE}")
            print("下次运行时会自动从中断位置继续搜索（加 --fresh 可强制从头开始）")
            sys.exit(2)  # 退出码 2 = 被中止，需要重试
        else:
            _clear_checkpoint()
            logger.info("搜索全部完成，已清除进度文件")
    finally:
        client.close()

