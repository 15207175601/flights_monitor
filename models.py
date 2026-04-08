"""
携程特价机票工具 - 数据模型

dataclass 与 enum 定义，供全项目使用。
本模块仅依赖标准库，位于依赖图的叶子层。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ── 枚举 ──────────────────────────────────────────────

class PeriodType(str, Enum):
    """假期类型：法定节假日 / 周末"""
    HOLIDAY = "holiday"
    WEEKEND = "weekend"


class IntlMode(str, Enum):
    """国际航班搜索模式"""
    DOMESTIC = "domestic"      # 仅国内
    ALL = "all"                # 国内 + 国际
    INTL_ONLY = "intl_only"   # 仅国际


# ── 航班信息 ──────────────────────────────────────────

@dataclass
class FlightInfo:
    """单段航班信息（去程或返程）"""
    flight_no: str = ""
    airline: str = ""
    dep_airport: str = ""
    arr_airport: str = ""
    dep_time: str = ""
    arr_time: str = ""
    duration: int = 0


# ── 单人路线结果 (discover) ───────────────────────────

@dataclass
class RouteResult:
    """FuzzySearch 返回的单条往返路线"""
    city_name: str
    city_code: str
    province: str
    dep_city_name: str
    price: int
    go_date: str
    back_date: str
    stay_days: int = 0
    leave_days: int = 0
    jump_url: str = ""
    outbound: FlightInfo = field(default_factory=FlightInfo)
    inbound: FlightInfo = field(default_factory=FlightInfo)
    tags: List[str] = field(default_factory=list)
    # 多人同行附加字段
    is_local: bool = False
    is_rail: bool = False
    rail_dist: int = 0


# ── 多人同行结果 ──────────────────────────────────────

@dataclass
class GroupResult:
    """多人同行的共同目的地结果"""
    dest_key: str
    city_name: str
    city_code: str
    province: str
    total_price: int
    avg_price: int
    go_date: str
    back_date: str
    stay_days: int
    together_range: str = ""
    tags: List[str] = field(default_factory=list)
    travelers: Dict[str, RouteResult] = field(default_factory=dict)


# ── API 模板 ──────────────────────────────────────────

@dataclass
class ApiTemplate:
    """捕获的携程 API 请求模板，用于重放"""
    url: str
    method: str = "POST"
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[dict] = None
