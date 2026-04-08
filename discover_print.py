"""
携程 FuzzySearch 结果格式化输出

负责: 单人结果表格、多人同行表格、详细航班信息、国际航班表格、搜索计划。
"""
import logging
from datetime import date

from config import PAGE_LOAD_WAIT, REQUEST_DELAY
from date_utils import calculate_trip_days
from shared import fmt_duration, fmt_time
from discover_parse import deduplicate_results

logger = logging.getLogger(__name__)

__all__ = [
    "print_results",
    "print_group_results",
    "print_group_detail",
    "print_abroad_results",
    "print_search_plan",
]


def _format_flight_cell(flight_no, airline):
    """格式化航班号+航司单元格"""
    if flight_no and airline:
        return f"{flight_no}({airline})"
    return flight_no or "-"


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
        print("| # | 目的地 | 最低价 | 游玩天数 | 休假天数 | 去程日期 | 起飞 | 返程日期 | 起飞 | 去程航班 | 时长 | 返程航班 | 时长 | 省份 | 景点推荐 |")
        print("|---|--------|-------|---------|---------|----------|------|----------|------|---------|------|---------|------|------|---------|")

        for rank, r in enumerate(results, 1):
            city = r["city_name"]
            province = r["province"] or "-"
            price_str = f"¥{r['price']}" if r["price"] > 0 else "-"
            # 去程
            go_d = r["go_date"] or "-"
            go_flt = _format_flight_cell(r["flight_no"], r["airline"])
            go_t = fmt_time(r["dep_time"]) or "-"
            go_dur = fmt_duration(r["duration"])
            # 返程
            back_d = r.get("back_date", "") or "-"
            ret_flt = _format_flight_cell(r.get("ret_flight_no", ""), r.get("ret_airline", ""))
            ret_t = fmt_time(r.get("ret_dep_time", "")) or "-"
            ret_dur = fmt_duration(r.get("ret_duration", 0))
            # 游玩天数
            stay = r.get("stay_days", 0)
            stay_str = f"{stay}天" if stay > 0 else "-"
            leave = r.get("leave_days", 0)
            leave_str = f"{leave}天" if leave > 0 else "0"
            tags = ", ".join(r["tags"][:2]) if r["tags"] else "-"

            print(f"| {rank} | {city} | **{price_str}** | {stay_str} | {leave_str} | {go_d} | {go_t} | {back_d} | {ret_t} | {go_flt} | {go_dur} | {ret_flt} | {ret_dur} | {province} | {tags} |")

    print(f"\n> 共找到 **{grand_total}** 条航线\n")


def print_group_results(all_period_results, traveler_names):
    """多人同行 — 简要表格"""
    total_count = sum(len(v) for v in all_period_results.values())
    if total_count == 0:
        print("\n" + "=" * 60)
        print("未找到多人同行的共同目的地特价机票")
        print("=" * 60)
        return

    group_label = "+".join(traveler_names)
    print(f"\n# 多人同行特价机票 ({group_label})")
    print(f"\n> 查询时间: {date.today()}")

    grand_total = 0
    for period_name, combined in all_period_results.items():
        if not combined:
            continue
        grand_total += len(combined)

        # 动态表头：每个出发城市一列
        price_cols = " | ".join(f"{n}→" for n in traveler_names)
        header = f"| # | 目的地 | {price_cols} | 合计 | 同游天数 | 同游时段 | 省份 |"
        sep_cols = " | ".join("------" for _ in traveler_names)
        separator = f"|---|--------|{sep_cols}|------|---------|----------|------|"

        print(f"\n## {period_name}\n")
        print(header)
        print(separator)

        for rank, c in enumerate(combined, 1):
            price_parts = []
            for n in traveler_names:
                r = c["travelers"][n]
                if r.get("is_local"):
                    price_parts.append("¥0(本地)")
                elif r.get("is_rail"):
                    price_parts.append(f"¥{r['price']}(高铁)")
                else:
                    price_parts.append(f"¥{r['price']}")
            prices = " | ".join(price_parts)
            stay = f"{c['stay_days']}天" if c["stay_days"] > 0 else "-"
            together = c.get("together_range", "-")
            province = c["province"] or "-"

            print(f"| {rank} | {c['city_name']} | {prices} | **¥{c['total_price']}** | {stay} | {together} | {province} |")

    print(f"\n> 共找到 **{grand_total}** 个共同目的地\n")


def print_group_detail(all_period_results, traveler_names):
    """多人同行 — 详细航班信息"""
    total_count = sum(len(v) for v in all_period_results.values())
    if total_count == 0:
        return

    print("---")
    print("\n# 详细航班信息\n")

    for period_name, combined in all_period_results.items():
        if not combined:
            continue

        print(f"\n## {period_name}\n")

        for rank, c in enumerate(combined, 1):
            print(f"### {rank}. {c['city_name']} — 合计 ¥{c['total_price']}\n")

            for name in traveler_names:
                r = c["travelers"][name]
                price = r["price"]

                personal_leave = r.get("personal_leave", 0)
                leave_str = f"，需请假 {personal_leave} 天" if personal_leave > 0 else "，无需请假"

                if r.get("is_local"):
                    # 本地人员：出发城市=目的地
                    print(f"**{name} [本地, 无需出行]{leave_str}**")
                    print(f"- 已在目的地, 费用 ¥0")
                    print()
                    continue

                if r.get("is_rail"):
                    # 高铁人员
                    dist = r.get("rail_dist", 0)
                    print(f"**{name}出发 ¥{price} [高铁估价, 距离{dist}km]{leave_str}**")
                    print(f"- 高铁往返, 时间灵活")
                    print()
                    continue

                # 去程
                go_flt = _format_flight_cell(r.get("flight_no", ""), r.get("airline", ""))
                go_t = fmt_time(r.get("dep_time", "")) or "-"
                go_dur = fmt_duration(r.get("duration", 0))
                go_d = r.get("go_date", "-")

                # 返程
                ret_flt = _format_flight_cell(r.get("ret_flight_no", ""), r.get("ret_airline", ""))
                ret_t = fmt_time(r.get("ret_dep_time", "")) or "-"
                ret_dur = fmt_duration(r.get("ret_duration", 0))
                back_d = r.get("back_date", "-")

                print(f"**{name}出发 ¥{price}{leave_str}**")
                print(f"- 去程: {go_d} {go_flt} {go_t} ({go_dur})")
                print(f"- 返程: {back_d} {ret_flt} {ret_t} ({ret_dur})")
                print()


def print_abroad_results(all_period_results, dep_city_name, country_names):
    """国际航班 — 结果表格"""
    total_count = sum(len(v) for v in all_period_results.values())
    if total_count == 0:
        print("\n" + "=" * 60)
        print("未找到国际特价机票")
        print("=" * 60)
        return

    countries_str = ", ".join(country_names)
    print(f"\n# 国际特价机票")
    print(f"\n> 出发城市: {dep_city_name} | 目的地: {countries_str} | 查询时间: {date.today()}")

    grand_total = 0
    for period_name, results in all_period_results.items():
        if not results:
            continue
        grand_total += len(results)

        print(f"\n## {period_name}\n")
        print("| # | 国家/地区 | 目的地 | 最低价 | 游玩天数 | 去程日期 | 起飞 | 返程日期 | 起飞 | 去程航班 | 时长 | 返程航班 | 时长 |")
        print("|---|----------|--------|-------|---------|---------|------|---------|------|---------|------|---------|------|")

        for rank, r in enumerate(results, 1):
            city = r["city_name"]
            country = r.get("province") or "-"
            price = f"¥{r['price']}"
            stay = f"{r['stay_days']}天" if r.get("stay_days") else "-"
            go_d = r.get("go_date", "-")
            go_t = fmt_time(r.get("dep_time", "")) or "-"
            back_d = r.get("back_date", "-")
            ret_t = fmt_time(r.get("ret_dep_time", "")) or "-"
            go_flt = _format_flight_cell(r.get("flight_no", ""), r.get("airline", ""))
            go_dur = fmt_duration(r.get("duration", 0))
            ret_flt = _format_flight_cell(r.get("ret_flight_no", ""), r.get("ret_airline", ""))
            ret_dur = fmt_duration(r.get("ret_duration", 0))

            print(f"| {rank} | {country} | {city} | {price} | {stay} | {go_d} | {go_t} | {back_d} | {ret_t} | {go_flt} | {go_dur} | {ret_flt} | {ret_dur} |")

    print(f"\n> 共找到 **{grand_total}** 条国际特价航线\n")


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
