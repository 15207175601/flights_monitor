"""
携程特价机票工具 - 统一浏览器管理

提供 Chrome 浏览器的启动、JS 拦截脚本注入、cookie 复用、安全退出。
修复问题:
- Chrome 进程泄漏: 使用 driver.quit() 替代 driver.service.stop()
- UA 过时: 更新到 Chrome/131
- 固定 sleep: 提供 wait_for_api_response() 基于 WebDriverWait 的等待
"""
import os
import sys
import shutil
import tempfile
import logging
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException

logger = logging.getLogger(__name__)


def _get_chrome_user_data_dir():
    """获取当前平台的 Chrome 用户数据目录"""
    if sys.platform == "darwin":
        return str(Path.home() / "Library/Application Support/Google/Chrome")
    elif sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        return os.path.join(local_app, "Google", "Chrome", "User Data") if local_app else ""
    else:
        # Linux
        return str(Path.home() / ".config/google-chrome")


_CHROME_USER_DATA = _get_chrome_user_data_dir()

# 当前版本 Chrome UA
CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 注入到页面的 JS 拦截脚本（discover 模式）
# 同时捕获 API 的 请求(URL+method+headers+body) 和 响应(body)
FUZZYSEARCH_INTERCEPT_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
(function() {
    window.__fuzzyResponses = [];
    window.__fuzzyRequests = [];

    const origFetch = window.fetch;
    window.fetch = function(input, init) {
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        var method = (init && init.method) || 'GET';
        var body = (init && init.body) || null;
        var headers = null;
        if (init && init.headers) {
            if (init.headers instanceof Headers) {
                headers = {};
                init.headers.forEach(function(v, k) { headers[k] = v; });
            } else {
                headers = init.headers;
            }
        }

        if (url.indexOf('uzzy') !== -1 || url.indexOf('lowprice') !== -1) {
            window.__fuzzyRequests.push({
                url: url, method: method, body: body, headers: headers
            });
        }

        return origFetch.apply(this, arguments).then(function(response) {
            if (url.indexOf('uzzy') !== -1 || url.indexOf('lowprice') !== -1) {
                response.clone().text().then(function(respBody) {
                    try {
                        var d = JSON.parse(respBody);
                        if (d && d.routes) {
                            window.__fuzzyResponses.push(respBody);
                        }
                    } catch(e) {}
                });
            }
            return response;
        });
    };

    var origOpen = XMLHttpRequest.prototype.open;
    var origSend = XMLHttpRequest.prototype.send;
    var origSetHeader = XMLHttpRequest.prototype.setRequestHeader;

    XMLHttpRequest.prototype.open = function(method, url) {
        this._url = url;
        this._method = method;
        this._headers = {};
        return origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        if (this._headers) this._headers[name] = value;
        return origSetHeader.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function(body) {
        var xhr = this;
        var url = this._url || '';
        if (url.indexOf('uzzy') !== -1 || url.indexOf('lowprice') !== -1) {
            window.__fuzzyRequests.push({
                url: url, method: this._method || 'GET',
                body: body || null, headers: this._headers || null
            });
            xhr.addEventListener('load', function() {
                try {
                    var d = JSON.parse(xhr.responseText);
                    if (d && d.routes) {
                        window.__fuzzyResponses.push(xhr.responseText);
                    }
                } catch(e) {}
            });
        }
        return origSend.apply(this, arguments);
    };
})();
"""

# 注入到页面的 JS 拦截脚本（monitor 模式 / batchSearch + fuzzySearch）
BATCH_INTERCEPT_JS = """
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


def prepare_chrome_profile():
    """将 Chrome 默认 profile 的 cookie 数据拷贝到临时目录"""
    src = os.path.join(_CHROME_USER_DATA, "Default")
    if not os.path.isdir(src):
        logger.warning("未找到 Chrome 默认 profile: %s", src)
        return None

    tmp_dir = tempfile.mkdtemp(prefix="flight_chrome_")
    dst = os.path.join(tmp_dir, "Default")
    os.makedirs(dst, exist_ok=True)

    for name in ("Cookies", "Cookies-journal", "Login Data", "Login Data-journal",
                  "Preferences", "Secure Preferences", "Local State"):
        src_file = os.path.join(src, name)
        if not os.path.exists(src_file):
            src_file = os.path.join(_CHROME_USER_DATA, name)
        if os.path.exists(src_file):
            dst_file = os.path.join(dst, name) if name != "Local State" else os.path.join(tmp_dir, name)
            shutil.copy2(src_file, dst_file)

    logger.info("已加载 Chrome cookie 数据")
    return tmp_dir


def init_browser(headless=False, intercept_js=FUZZYSEARCH_INTERCEPT_JS):
    """
    启动 Chrome 浏览器并注入拦截脚本。
    返回 (driver, tmp_profile_dir)。
    """
    logger.info("启动 Chrome 浏览器 (headless=%s)...", headless)
    options = Options()

    tmp_profile = None
    if headless:
        options.add_argument("--headless=new")
        tmp_profile = prepare_chrome_profile()
    if tmp_profile:
        options.add_argument(f"--user-data-dir={tmp_profile}")
        options.add_argument("--profile-directory=Default")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-agent={CHROME_UA}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": intercept_js},
    )
    logger.info("浏览器启动成功")
    return driver, tmp_profile


def close_browser(driver, tmp_profile=None):
    """
    安全关闭浏览器（修复 Chrome 进程泄漏）。
    使用 driver.quit() 而非 driver.service.stop()。
    """
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    if tmp_profile and os.path.isdir(tmp_profile):
        shutil.rmtree(tmp_profile, ignore_errors=True)


def wait_for_api_response(driver, js_check, timeout=15, poll_frequency=0.5):
    """
    基于 WebDriverWait 等待 API 响应（替代固定 sleep）。

    Args:
        driver: WebDriver 实例
        js_check: JS 表达式，返回 true 表示响应已到达
            例如: "return (window.__fuzzyResponses && window.__fuzzyResponses.length > 0)"
        timeout: 最大等待秒数
        poll_frequency: 轮询间隔

    Returns:
        True 如果在超时前收到响应，False 如果超时
    """
    try:
        WebDriverWait(driver, timeout, poll_frequency=poll_frequency).until(
            lambda d: d.execute_script(js_check)
        )
        return True
    except TimeoutException:
        return False


class BrowserSession:
    """浏览器 Context Manager — 保证退出时清理 Chrome 进程和临时目录"""

    def __init__(self, headless=False, intercept_js=FUZZYSEARCH_INTERCEPT_JS):
        self.headless = headless
        self.intercept_js = intercept_js
        self.driver = None
        self._tmp_profile = None

    def __enter__(self):
        self.driver, self._tmp_profile = init_browser(
            headless=self.headless, intercept_js=self.intercept_js,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        close_browser(self.driver, self._tmp_profile)
        self.driver = None
        self._tmp_profile = None
        return False
