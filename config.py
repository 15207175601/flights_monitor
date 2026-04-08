"""
携程特价机票监测工具 - 配置文件
"""
import logging
from datetime import date

from models import PeriodType

# === 出发城市 ===
DEPARTURE_CITY_CODE = "BJS"
DEPARTURE_CITY_NAME = "北京"

# === 最大折扣率 (4折 = 0.4) ===
MAX_DISCOUNT_RATE = 0.4

# === 目的地最小距离（公里），过滤太近的城市 ===
MIN_DISTANCE_KM = 400

# === 搜索时间范围（从今天起多少天内） ===
SEARCH_DAYS_AHEAD = 180

# === 请求延迟（秒），避免被反爬 ===
REQUEST_DELAY = 4.0

# === 城市间休息间隔（秒），降低反爬风险 ===
CITY_SLEEP_MIN = 30
CITY_SLEEP_MAX = 60

# === 连续空响应阈值：超过此数判定为被反爬封禁 ===
MAX_CONSECUTIVE_EMPTY = 5

# === API 重放与页面等待 ===
PAGE_LOAD_WAIT = 15  # 等待页面 API 响应的最大秒数
MAX_RETRY = 2        # API 重放最大重试次数

# === 高铁替代阈值 ===
RAIL_THRESHOLD_KM = 600   # 距离 < 此值用高铁替代
RAIL_PRICE_PER_KM = 0.5   # 高铁估价: 元/km

# === 国际航班批次大小 (API 限制每次 acs 最多 3 个国家) ===
INTL_BATCH_SIZE = 3

# === 游玩天数过滤 ===
MIN_STAY_DAYS = 0   # 最少游玩天数, 0=不过滤
MAX_STAY_DAYS = 0   # 最多游玩天数, 0=不过滤

# === 2026年法定节假日 (可根据国务院公告调整) ===
# type: PeriodType.HOLIDAY 表示法定节假日，出发提前2天/返程延后2天
# type: PeriodType.WEEKEND 由程序自动生成，出发提前1天/返程延后1天
HOLIDAYS = [
    {
        "name": "清明节",
        "start": date(2026, 4, 4),
        "end": date(2026, 4, 6),
        "type": PeriodType.HOLIDAY,
    },
    {
        "name": "劳动节",
        "start": date(2026, 5, 1),
        "end": date(2026, 5, 5),
        "type": PeriodType.HOLIDAY,
    },
    {
        "name": "端午节",
        "start": date(2026, 6, 19),
        "end": date(2026, 6, 21),
        "type": PeriodType.HOLIDAY,
    },
    {
        "name": "中秋节",
        "start": date(2026, 9, 25),
        "end": date(2026, 9, 27),
        "type": PeriodType.HOLIDAY,
    },
    {
        "name": "国庆节",
        "start": date(2026, 10, 1),
        "end": date(2026, 10, 7),
        "type": PeriodType.HOLIDAY,
    },
]

# 假期数据过期提醒
if HOLIDAYS and all(h["end"] < date.today() for h in HOLIDAYS):
    logging.getLogger(__name__).warning(
        "HOLIDAYS 中所有假期均已过期（最晚: %s），请更新 config.py 中的假期数据",
        max(h["end"] for h in HOLIDAYS),
    )
