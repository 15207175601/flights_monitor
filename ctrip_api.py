"""
携程特价机票监测工具 - 携程航班搜索客户端
使用 Selenium 驱动 Chrome，通过拦截 XHR 响应获取真实航班数据
"""
import json
import time
import random
import logging
import shutil
import tempfile
import os
from typing import List, Dict
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException

from config import REQUEST_DELAY

logger = logging.getLogger(__name__)

# 注入到页面的 JS 拦截脚本 - 捕获 batchSearch 和 fuzzySearch 响应
_INTERCEPT_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
(function() {
    window.__flightResponses = [];
    window.__fuzzyResponses = [];
    const origFetch = window.fetch;
    window.fetch = function() {
        return origFetch.apply(this, arguments).then(function(response) {
            var url = typeof arguments[0] === 'string' ? arguments[0] : (arguments[0] && arguments[0].url) || '';
            if (url.indexOf('batchSearch') !== -1) {
                response.clone().text().then(function(body) {
                    window.__flightResponses.push(body);
                });
            }
            if (url.indexOf('fuzzySearch') !== -1) {
                response.clone().text().then(function(body) {
                    window.__fuzzyResponses.push(body);
                });
            }
            return response;
        });
    };
    var origOpen = XMLHttpRequest.prototype.open;
    var origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url) {
        this._url = url;
        return origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function() {
        var xhr = this;
        if (this._url && (this._url.indexOf('batchSearch') !== -1)) {
            xhr.addEventListener('load', function() {
                try { window.__flightResponses.push(xhr.responseText); } catch(e) {}
            });
        }
        if (this._url && (this._url.indexOf('fuzzySearch') !== -1)) {
            xhr.addEventListener('load', function() {
                try { window.__fuzzyResponses.push(xhr.responseText); } catch(e) {}
            });
        }
        return origSend.apply(this, arguments);
    };
})();
"""


class CtripFlightClient:
    """携程航班搜索客户端"""

    LIST_URL_TPL = "https://flights.ctrip.com/online/list/oneway-{dcity}-{acity}?depdate={date}"
    PAGE_LOAD_WAIT = 12  # 等待页面加载和 API 响应的秒数

    # macOS 下 Chrome 默认用户数据目录
    _CHROME_USER_DATA = str(Path.home() / "Library/Application Support/Google/Chrome")

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.driver = None
        self._tmp_profile_dir = None

    def _prepare_profile(self):
        """将 Chrome 默认 profile 的 cookie 数据拷贝到临时目录，避免锁冲突"""
        src = os.path.join(self._CHROME_USER_DATA, "Default")
        if not os.path.isdir(src):
            logger.warning("未找到 Chrome 默认 profile: %s，将使用空 profile", src)
            return None

        tmp_dir = tempfile.mkdtemp(prefix="flight_chrome_")
        dst = os.path.join(tmp_dir, "Default")
        os.makedirs(dst, exist_ok=True)

        # 只拷贝 cookie 相关文件，不拷贝整个 profile（太大）
        for name in ("Cookies", "Cookies-journal", "Login Data", "Login Data-journal",
                      "Preferences", "Secure Preferences", "Local State"):
            src_file = os.path.join(src, name)
            if not os.path.exists(src_file):
                # Local State 在上层目录
                src_file = os.path.join(self._CHROME_USER_DATA, name)
            if os.path.exists(src_file):
                dst_file = os.path.join(dst, name) if name != "Local State" else os.path.join(tmp_dir, name)
                shutil.copy2(src_file, dst_file)

        logger.info("已加载 Chrome 默认 cookie 数据")
        return tmp_dir

    def init_session(self):
        """启动 Chrome 浏览器（默认有头模式 + 用户 cookie）"""
        logger.info("启动 Chrome 浏览器 (headless=%s)...", self.headless)
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")

        # 有头模式下不复制 profile（Chrome 会检测篡改并重置，导致登录失效）
        # 用户将在浏览器中手动登录
        if self.headless:
            self._tmp_profile_dir = self._prepare_profile()
        if self._tmp_profile_dir:
            options.add_argument(f"--user-data-dir={self._tmp_profile_dir}")
            options.add_argument("--profile-directory=Default")

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        try:
            self.driver = webdriver.Chrome(options=options)
            # 注入拦截脚本（在每个页面加载前执行）
            self.driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": _INTERCEPT_JS},
            )
            logger.info("浏览器启动成功")
        except WebDriverException as e:
            logger.error("浏览器启动失败: %s", e)
            raise

    def close(self):
        """程序退出时断开 driver 连接，但不关闭浏览器（由用户手动关闭）"""
        if self.driver:
            try:
                self.driver.service.stop()
            except Exception:
                pass
            self.driver = None
        if self._tmp_profile_dir and os.path.isdir(self._tmp_profile_dir):
            try:
                shutil.rmtree(self._tmp_profile_dir, ignore_errors=True)
            except Exception:
                pass
            self._tmp_profile_dir = None

    def discover_destinations(self, dep_city_code: str = "BJS") -> Dict[str, str]:
        """
        从携程自动发现出发城市的所有国内航线目的地
        通过访问携程国内频道页，拦截 fuzzySearch API 获取航线列表
        非北京出发时，先获取北京航线再排除自身作为候选
        Returns:
            {城市代码: 城市名} 的字典，如 {"SHA": "上海", "CAN": "广州"}
        """
        if not self.driver:
            self.init_session()

        logger.info("正在从携程自动发现 %s 出发的所有国内航线...", dep_city_code)
        destinations = {}

        try:
            self.driver.get("https://flights.ctrip.com/online/channel/domestic")
            time.sleep(10)

            # 提取 fuzzySearch 响应（该页面返回北京出发的所有国内航线）
            raw = self.driver.execute_script(
                "var r = window.__fuzzyResponses || []; window.__fuzzyResponses = []; return JSON.stringify(r);"
            )
            responses = json.loads(raw)
            logger.debug("拦截到 %d 个 fuzzySearch 响应", len(responses))

            # 收集所有国内航线城市
            all_cities = {}  # code -> name
            for body_str in responses:
                try:
                    data = json.loads(body_str)
                    routes = data.get("routes", [])
                    for route in routes:
                        arr = route.get("arriveCity", {})
                        if arr.get("isIntl", False):
                            continue
                        code = arr.get("code", "")
                        name = arr.get("name", "")
                        if code and name:
                            all_cities[code] = name
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue

            # 排除出发城市自身
            destinations = {c: n for c, n in all_cities.items() if c != dep_city_code}
            # 非北京出发时，把北京加入候选
            if dep_city_code != "BJS" and "BJS" not in destinations:
                destinations["BJS"] = "北京"

            logger.info("发现 %d 个目的地城市", len(destinations))
            sorted_names = sorted(destinations.values())
            logger.info("目的地: %s", "、".join(sorted_names))

        except Exception as e:
            logger.warning("目的地发现失败: %s", e)

        return destinations

    def search_oneway(
        self, dcity: str, acity: str, dcity_name: str, acity_name: str, date_str: str
    ) -> tuple:
        """搜索单程航班，返回 (航班列表, 是否收到有效API响应)"""
        if not self.driver:
            self.init_session()

        url = self.LIST_URL_TPL.format(
            dcity=dcity.lower(), acity=acity.lower(), date=date_str
        )

        flights = []
        got_response = False
        try:
            logger.debug("访问: %s", url)
            self.driver.get(url)

            # 等待 batchSearch API 响应
            intercepted = False
            try:
                WebDriverWait(self.driver, self.PAGE_LOAD_WAIT).until(
                    lambda d: d.execute_script(
                        "return (window.__flightResponses && window.__flightResponses.length > 0)"
                    )
                )
                intercepted = True
            except TimeoutException:
                logger.warning("等待航班数据超时: %s->%s %s", dcity_name, acity_name, date_str)

            # 额外等待确保数据完整
            time.sleep(2)

            # 提取拦截到的响应数据
            raw = self.driver.execute_script(
                "var r = window.__flightResponses || []; window.__flightResponses = []; return JSON.stringify(r);"
            )
            responses = json.loads(raw)

            # 诊断：检查页面是否有验证码或异常
            page_url = self.driver.current_url
            page_title = self.driver.title

            if not responses:
                logger.warning(
                    "  [诊断] %s->%s %s: 未拦截到API响应 | 拦截器触发=%s | 页面标题='%s' | URL=%s",
                    dcity_name, acity_name, date_str, intercepted, page_title, page_url,
                )
            else:
                got_response = True
                logger.debug("拦截到 %d 个 batchSearch 响应", len(responses))

            for body_str in responses:
                try:
                    data = json.loads(body_str)
                    # 诊断：检查响应结构
                    resp_msg = data.get("msg", "")
                    resp_code = data.get("code", "")
                    fl_list = data.get("data", {}).get("flightItineraryList", [])

                    if not fl_list:
                        logger.warning(
                            "  [诊断] %s->%s %s: API响应无航班列表 | code=%s msg='%s' | data keys=%s",
                            dcity_name, acity_name, date_str, resp_code, resp_msg,
                            list(data.get("data", {}).keys()) if data.get("data") else "无data字段",
                        )

                    parsed = self._parse_response(data, dcity_name, acity_name, date_str)
                    flights.extend(parsed)
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.warning("  [诊断] %s->%s %s: 响应解析异常: %s | 响应前200字符: %s",
                                   dcity_name, acity_name, date_str, e, body_str[:200])

            if not flights and responses:
                logger.warning(
                    "  [诊断] %s->%s %s: 拦截到 %d 个响应但解析出 0 个航班",
                    dcity_name, acity_name, date_str, len(responses),
                )

        except Exception as e:
            logger.warning("搜索失败 %s->%s %s: %s", dcity_name, acity_name, date_str, e)

        # 请求延迟
        delay = REQUEST_DELAY + random.uniform(0, 1)
        time.sleep(delay)

        return flights, got_response

    def _parse_response(
        self, data: dict, dcity_name: str, acity_name: str, date_str: str
    ) -> List[Dict]:
        """解析 batchSearch API 响应"""
        flights = []

        fl_list = data.get("data", {}).get("flightItineraryList", [])
        if not fl_list:
            logger.debug("无航班数据: %s->%s %s", dcity_name, acity_name, date_str)
            return flights

        no_price_list = 0
        no_cabin_y = 0
        no_valid_price = 0
        parse_error = 0

        for item in fl_list:
            try:
                # 航班基本信息
                seg = item.get("flightSegments", [{}])[0]
                fl = seg.get("flightList", [{}])[0]

                flight_no = fl.get("flightNo", "")
                airline = fl.get("marketAirlineName", "")
                dep_time = fl.get("departureDateTime", "")
                arr_time = fl.get("arrivalDateTime", "")
                dep_airport = fl.get("departureAirportShortName", "")
                arr_airport = fl.get("arrivalAirportShortName", "")
                duration = fl.get("duration", 0)

                # 找最低经济舱价格
                best_price = None
                price_list = item.get("priceList", [])
                if not price_list:
                    no_price_list += 1
                    continue

                has_cabin_y = False
                for p in price_list:
                    if p.get("cabin") != "Y":
                        continue
                    has_cabin_y = True

                    price = p.get("adultPrice", 0)
                    if price <= 0:
                        continue

                    # 从 priceUnitList 中获取折扣率
                    discount_rate = self._get_discount_rate(p)

                    if best_price is None or price < best_price["price"]:
                        best_price = {
                            "price": int(price),
                            "discount_rate": discount_rate,
                        }

                if not has_cabin_y:
                    no_cabin_y += 1
                    continue

                if not best_price:
                    no_valid_price += 1
                    continue

                rate = best_price["discount_rate"]
                if rate > 0:
                    disc_display = f"{rate * 10:.1f}折"
                else:
                    disc_display = "未知"

                flights.append({
                    "flight_number": flight_no,
                    "airline": airline,
                    "dep_city": dcity_name,
                    "arr_city": acity_name,
                    "dep_airport": dep_airport,
                    "arr_airport": arr_airport,
                    "dep_time": dep_time,
                    "arr_time": arr_time,
                    "duration": duration,
                    "price": best_price["price"],
                    "discount_rate": round(rate, 2),
                    "discount_display": disc_display,
                    "date": date_str,
                })

            except (KeyError, TypeError, IndexError) as e:
                parse_error += 1
                logger.debug("解析单条航班失败: %s", e)
                continue

        # 解析结果为空时输出诊断统计
        if not flights:
            logger.warning(
                "  [诊断] %s->%s %s: 航班列表 %d 条全部被过滤 | 无priceList=%d 无经济舱=%d 无有效价格=%d 解析异常=%d",
                dcity_name, acity_name, date_str, len(fl_list),
                no_price_list, no_cabin_y, no_valid_price, parse_error,
            )
            # 首次失败时保存原始响应供调试
            debug_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".debug_response.json")
            if not os.path.exists(debug_file):
                try:
                    with open(debug_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    logger.info("  [诊断] 已保存原始响应到 %s", debug_file)
                except Exception:
                    pass

        return flights

    @staticmethod
    def _get_discount_rate(price_item: dict) -> float:
        """从价格项中提取折扣率"""
        try:
            units = price_item.get("priceUnitList", [])
            for u in units:
                seats = u.get("flightSeatList", [])
                for s in seats:
                    rate = s.get("discountRate", 0)
                    if rate > 0:
                        return float(rate)
        except (KeyError, TypeError, ValueError):
            pass
        return 0.0
