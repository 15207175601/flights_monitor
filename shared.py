"""
携程特价机票工具 - 共享数据与工具函数

提供跨模块共享的城市数据、坐标、距离计算、假期缓存、格式化工具。
"""
import math
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Optional

from config import HOLIDAYS

# === 城市名 → (code, name) 映射表 ===
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

# === 国际航班: 国家/地区名 → ISO 代码映射 ===
INTL_COUNTRY_MAP = {
    # 亚洲
    "缅甸": "MM", "菲律宾": "PH", "马来西亚": "MY", "老挝": "LA",
    "印度尼西亚": "ID", "印度": "IN", "日本": "JP", "韩国": "KR",
    "泰国": "TH", "马尔代夫": "MV", "越南": "VN", "阿联酋": "AE",
    "柬埔寨": "KH", "斯里兰卡": "LK", "格鲁吉亚": "GE",
    "哈萨克斯坦": "KZ", "蒙古": "MN", "乌兹别克斯坦": "UZ",
    "尼泊尔": "NP", "沙特阿拉伯": "SA", "朝鲜": "KP",
    # 欧洲
    "俄罗斯": "RU", "波兰": "PL", "英国": "GB", "法国": "FR",
    "意大利": "IT", "土耳其": "TR", "西班牙": "ES", "德国": "DE",
    "荷兰": "NL", "瑞士": "CH", "匈牙利": "HU", "希腊": "GR",
    "冰岛": "IS", "塞尔维亚": "RS", "比利时": "BE", "奥地利": "AT",
    "芬兰": "FI", "丹麦": "DK", "挪威": "NO", "葡萄牙": "PT",
    "瑞典": "SE", "捷克": "CZ", "卢森堡": "LU", "斯洛伐克": "SK",
    "斯洛文尼亚": "SI",
    # 美洲
    "美国": "US", "加拿大": "CA", "墨西哥": "MX", "巴西": "BR",
    # 大洋洲
    "澳大利亚": "AU", "新西兰": "NZ", "斐济": "FJ",
    # 非洲
    "埃塞俄比亚": "ET", "南非": "ZA", "坦桑尼亚": "TZ",
    "埃及": "EG", "摩洛哥": "MA", "肯尼亚": "KE", "毛里求斯": "MU",
    # 中国地区
    "中国香港": "HK", "中国台北": "TW", "高雄": "TW", "中国澳门": "MO",
}

# === 城市坐标 (纬度, 经度) ===
CITY_COORDS = {
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


def haversine_km(lat1, lon1, lat2, lon2):
    """计算两个坐标之间的大圆距离（公里）"""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def resolve_city(city_name_or_code):
    """
    根据城市名或代码解析出 (code, name)
    支持中文名（如"上海"）或三字码（如"SHA"）
    """
    if city_name_or_code in CITY_MAP:
        return CITY_MAP[city_name_or_code]
    upper = city_name_or_code.upper()
    for name, (code, cname) in CITY_MAP.items():
        if code == upper:
            return (code, name)
    if len(city_name_or_code) == 3 and city_name_or_code.isalpha():
        return (upper, city_name_or_code)
    return (city_name_or_code, city_name_or_code)


@lru_cache(maxsize=1)
def build_holiday_dates():
    """构建节假日日期集合（缓存，整个进程生命周期只计算一次）"""
    holiday_dates = set()
    for h in HOLIDAYS:
        d = h["start"]
        while d <= h["end"]:
            holiday_dates.add(d)
            d += timedelta(days=1)
    return frozenset(holiday_dates)


def count_leave_days(go_date, back_date):
    """计算出发日~返程日之间需要请假的工作日数"""
    holiday_dates = build_holiday_dates()
    leave = 0
    d = go_date
    while d <= back_date:
        if d.weekday() < 5 and d not in holiday_dates:
            leave += 1
        d += timedelta(days=1)
    return leave


def fmt_duration(minutes):
    """格式化飞行时长"""
    if not minutes:
        return "-"
    h, m = divmod(int(minutes), 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def fmt_duration_detail(fly_min, transfer_min=0):
    """格式化飞行时长，含中转耗时

    直达: "2h30m"
    中转: "飞2h30m+转1h20m"
    """
    if not fly_min and not transfer_min:
        return "-"
    fly_str = fmt_duration(fly_min)
    if not transfer_min:
        return fly_str
    trans_str = fmt_duration(transfer_min)
    return f"飞{fly_str}+转{trans_str}"


def fmt_datetime_short(date_str, time_str=""):
    """合并日期+时间为 'MM/DD HH:MM' 格式，如 '04/11 09:55'
    date_str: '2026-04-11' 或含日期的字符串
    time_str: '2026-04-16 08:25:00' 或 HH:MM，若为空则从 date_str 不提取时间
    """
    if not date_str:
        return "-"
    try:
        # 解析日期部分 (取 date_str 的前 10 字符 YYYY-MM-DD)
        d = date_str[:10]
        month = d[5:7].lstrip("0") or "0"
        day = d[8:10].lstrip("0") or "0"
        md = f"{month.zfill(2)}/{day.zfill(2)}"
    except (IndexError, ValueError):
        return "-"
    # 解析时间部分
    t = fmt_time(time_str) if time_str else ""
    if t:
        return f"{md} {t}"
    return md


def fmt_time(dt_str):
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


def parse_datetime(dt_str: str) -> Optional[datetime]:
    """安全解析 ISO 日期时间字符串 (如 '2026-04-16T08:25:00')"""
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None


def parse_date(date_str: str) -> Optional[date]:
    """安全解析 ISO 日期字符串 (如 '2026-04-16')"""
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def is_within_distance(city_name: str, dep_city_name: str,
                       min_km: float = 0, max_km: float = 0) -> bool:
    """判断目的地是否在指定距离范围内 (未知坐标的城市返回 True 保留)"""
    dep_coord = CITY_COORDS.get(dep_city_name)
    dest_coord = CITY_COORDS.get(city_name)
    if not dep_coord or not dest_coord:
        return True
    dist = haversine_km(dep_coord[0], dep_coord[1], dest_coord[0], dest_coord[1])
    if min_km > 0 and dist < min_km:
        return False
    if max_km > 0 and dist > max_km:
        return False
    return True
