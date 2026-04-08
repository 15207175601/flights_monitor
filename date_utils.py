"""
携程特价机票监测工具 - 日期计算工具
根据假期类型计算出发和返程的搜索日期范围
"""
from datetime import date, timedelta
from typing import List, Dict

from config import HOLIDAYS, SEARCH_DAYS_AHEAD


def get_weekends(start_date: date, days_ahead: int) -> List[Dict]:
    """
    获取从 start_date 起 days_ahead 天内的所有周末
    返回格式与 HOLIDAYS 一致
    """
    weekends = []
    current = start_date
    end_limit = start_date + timedelta(days=days_ahead)

    # 找到第一个周六
    while current.weekday() != 5 and current < end_limit:
        current += timedelta(days=1)

    while current < end_limit:
        saturday = current
        sunday = current + timedelta(days=1)
        if sunday < end_limit:
            weekends.append({
                "name": f"周末({saturday.month}/{saturday.day}-{sunday.month}/{sunday.day})",
                "start": saturday,
                "end": sunday,
                "type": "weekend",
            })
        current += timedelta(days=7)

    return weekends


def get_holidays_in_range(start_date: date, days_ahead: int) -> List[Dict]:
    """获取在搜索范围内的法定节假日"""
    end_limit = start_date + timedelta(days=days_ahead)
    return [h for h in HOLIDAYS if h["start"] >= start_date and h["start"] < end_limit]


def _date_range(start: date, end: date) -> List[date]:
    """生成从 start 到 end（含）的日期列表"""
    days = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days


def calculate_travel_dates(holiday: Dict) -> Dict:
    """
    根据假期类型计算出发和返程的日期搜索范围
    - 周末: 最早出发=假期前1天, 最晚出发=假期首日; 最早返程=假期末日, 最晚返程=假期后1天
    - 法定节假日: 最早出发=假期前2天, 最晚出发=假期首日; 最早返程=假期末日, 最晚返程=假期后2天
    """
    if holiday["type"] == "weekend":
        advance_days = 1
        delay_days = 1
    else:
        advance_days = 2
        delay_days = 2

    earliest_depart = holiday["start"] - timedelta(days=advance_days)
    latest_depart = holiday["start"]
    earliest_return = holiday["end"]
    latest_return = holiday["end"] + timedelta(days=delay_days)

    return {
        "name": holiday["name"],
        "type": holiday["type"],
        "holiday_start": holiday["start"],
        "holiday_end": holiday["end"],
        "depart_dates": _date_range(earliest_depart, latest_depart),
        "return_dates": _date_range(earliest_return, latest_return),
    }


def get_all_travel_periods(only_holidays: bool = False) -> List[Dict]:
    """
    获取所有需要搜索的出行时段
    Args:
        only_holidays: 是否只返回法定节假日(不含普通周末)
    """
    today = date.today()
    periods = []

    # 法定节假日
    holidays = get_holidays_in_range(today, SEARCH_DAYS_AHEAD)
    for h in holidays:
        periods.append(calculate_travel_dates(h))

    # 普通周末
    if not only_holidays:
        weekends = get_weekends(today, SEARCH_DAYS_AHEAD)

        # 排除与法定节假日重叠的周末
        holiday_dates = set()
        for h in holidays:
            d = h["start"]
            while d <= h["end"]:
                holiday_dates.add(d)
                d += timedelta(days=1)

        for w in weekends:
            if w["start"] not in holiday_dates and w["end"] not in holiday_dates:
                periods.append(calculate_travel_dates(w))

    # 按最早出发日期排序
    periods.sort(key=lambda x: x["depart_dates"][0])
    return periods


def calculate_trip_days(period) -> list:
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


def get_periods_for_dates(dates_str: str) -> List[Dict]:
    """
    根据用户指定的日期列表生成出行时段
    自动判断每个日期是节假日还是周末：
    - 落在 HOLIDAYS 范围内 → 按该节假日处理
    - 否则 → 找到该日期所在周的周六-周日，按周末处理
    Args:
        dates_str: 逗号分隔的日期字符串，如 "2026-04-11,2026-05-01"
    """
    from datetime import datetime

    date_list = []
    for s in dates_str.split(","):
        s = s.strip()
        if not s:
            continue
        try:
            date_list.append(datetime.strptime(s, "%Y-%m-%d").date())
        except ValueError:
            raise ValueError(f"日期格式错误: {s}，请使用 YYYY-MM-DD 格式")

    seen = set()  # 用于去重（同一个节假日/周末只保留一个）
    periods = []

    for d in date_list:
        # 检查是否落在某个节假日范围内
        matched_holiday = None
        for h in HOLIDAYS:
            if h["start"] <= d <= h["end"]:
                matched_holiday = h
                break

        if matched_holiday:
            key = ("holiday", matched_holiday["name"])
            if key not in seen:
                seen.add(key)
                periods.append(calculate_travel_dates(matched_holiday))
        else:
            # 找到该日期所在周的周六-周日
            # weekday: Mon=0 ... Sat=5, Sun=6
            # Sunday 特殊处理：回退 1 天到当周的 Saturday
            if d.weekday() == 6:
                saturday = d - timedelta(days=1)
            else:
                days_until_sat = (5 - d.weekday()) % 7
                saturday = d + timedelta(days=days_until_sat)
            sunday = saturday + timedelta(days=1)
            key = ("weekend", saturday)
            if key not in seen:
                seen.add(key)
                weekend = {
                    "name": f"周末({saturday.month}/{saturday.day}-{sunday.month}/{sunday.day})",
                    "start": saturday,
                    "end": sunday,
                    "type": "weekend",
                }
                periods.append(calculate_travel_dates(weekend))

    periods.sort(key=lambda x: x["depart_dates"][0])
    return periods
