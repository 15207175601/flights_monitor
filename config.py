"""
携程特价机票监测工具 - 配置文件
"""
from datetime import date

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

# === 游玩天数过滤 ===
MIN_STAY_DAYS = 0   # 最少游玩天数, 0=不过滤
MAX_STAY_DAYS = 0   # 最多游玩天数, 0=不过滤

# === 2026年法定节假日 (可根据国务院公告调整) ===
# type: "holiday" 表示法定节假日，出发提前2天/返程延后2天
# type: "weekend" 由程序自动生成，出发提前1天/返程延后1天
HOLIDAYS = [
    {
        "name": "清明节",
        "start": date(2026, 4, 4),
        "end": date(2026, 4, 6),
        "type": "holiday",
    },
    {
        "name": "劳动节",
        "start": date(2026, 5, 1),
        "end": date(2026, 5, 5),
        "type": "holiday",
    },
    {
        "name": "端午节",
        "start": date(2026, 6, 19),
        "end": date(2026, 6, 21),
        "type": "holiday",
    },
    {
        "name": "中秋节",
        "start": date(2026, 9, 25),
        "end": date(2026, 9, 27),
        "type": "holiday",
    },
    {
        "name": "国庆节",
        "start": date(2026, 10, 1),
        "end": date(2026, 10, 7),
        "type": "holiday",
    },
]
