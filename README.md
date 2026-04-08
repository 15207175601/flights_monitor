# 携程特价机票工具

自动从携程发现全国航线的节假日/周末特价往返机票，按价格排序输出。

提供两个子命令:

| 子命令 | 入口 | 特点 |
|--------|------|------|
| **discover** | `python main.py discover` | 一次请求获取全国所有目的地，速度快，适合全局概览 |
| **monitor** | `python main.py monitor` | 逐城市搜索具体航班+折扣，结果更详细，支持断点续搜 |

## 环境准备

```bash
pip install -r requirements.txt
# 需要本地安装 Chrome 浏览器（Selenium 会自动管理 ChromeDriver）
```

## 快速开始

### discover — 全国特价概览（推荐）

```bash
# 搜索所有假期+周末（北京出发，默认无头模式）
python main.py discover

# 从上海出发
python main.py discover --from 上海

# 只搜法定节假日
python main.py discover --holidays-only

# 只搜最近一个假期
python main.py discover --next

# 只搜指定日期
python main.py discover --dates 2026-04-04,2026-05-01

# 价格过滤: 只看 500 元以下
python main.py discover --max-price 500

# 游玩天数过滤: 2~4 天
python main.py discover --min-stay 2 --max-stay 4

# 距离过滤: 400~2000km
python main.py discover --min-dist 400 --max-dist 2000

# 飞行时长过滤: 1~3 小时
python main.py discover --min-flight-time 60 --max-flight-time 180

# 组合使用
python main.py discover --from 上海 --holidays-only --max-price 800 --min-stay 3 --min-dist 500

# 测试模式（只搜1个时段，验证环境可用）
python main.py discover --test

# 显示浏览器窗口（默认无头）
python main.py discover --no-headless

# 多人同行: 搜索共同目的地，按合计价排序
python main.py discover --group 北京,武汉

# 三人同行 + 价格过滤（合计价不超过 3000）
python main.py discover --group 北京,武汉,上海 --holidays-only --max-price 3000

# 多人同行 + 最小同游天数（默认2天）
python main.py discover --group 北京,武汉 --min-together 3
```

### 多人同行智能优化

多人同行模式（`--group`）包含以下智能处理：

- **高铁替代**: 出发城市距目的地 < 600km 时，自动用高铁估价（0.5元/km）替代机票，标注"高铁"
- **本地识别**: 出发城市 = 目的地时，该人票价为 ¥0，标注"本地"
- **同游时段**: 精确计算所有飞行人员的到达时间~返程起飞时间交集
- **统一请假**: 所有人的请假天数以飞机人员中最少的为准，保持一致
- **查询间隔**: 每次切换出发城市搜索前随机等待 30~60 秒，防反爬
- **输出格式**: 同时输出简要表格（按合计价排序）和详细航班文档（含每人请假天数）

### discover — 国际航班搜索

```bash
# 随机搜索 3 个国家的特价机票
python main.py discover --abroad

# 指定国家
python main.py discover --abroad 日本,泰国,韩国

# 中国地区
python main.py discover --abroad 中国香港,中国台北,中国澳门

# 组合参数
python main.py discover --abroad 日本,法国 --from 上海 --max-price 3000 --holidays-only

# 包含无效输入（会提示哪些无效并跳过）
python main.py discover --abroad 日本,火星,泰国

# 测试模式
python main.py discover --abroad 日本,泰国,韩国 --test
```

**支持的国家/地区（60个）：**

| 区域 | 国家/地区 |
|------|----------|
| 亚洲(21) | 缅甸、菲律宾、马来西亚、老挝、印度尼西亚、印度、日本、韩国、泰国、马尔代夫、越南、阿联酋、柬埔寨、斯里兰卡、格鲁吉亚、哈萨克斯坦、蒙古、乌兹别克斯坦、尼泊尔、沙特阿拉伯、朝鲜 |
| 欧洲(25) | 俄罗斯、波兰、英国、法国、意大利、土耳其、西班牙、德国、荷兰、瑞士、匈牙利、希腊、冰岛、塞尔维亚、比利时、奥地利、芬兰、丹麦、挪威、葡萄牙、瑞典、捷克、卢森堡、斯洛伐克、斯洛文尼亚 |
| 美洲(4) | 美国、加拿大、墨西哥、巴西 |
| 大洋洲(3) | 澳大利亚、新西兰、斐济 |
| 非洲(7) | 埃塞俄比亚、南非、坦桑尼亚、埃及、摩洛哥、肯尼亚、毛里求斯 |
| 中国地区(4) | 中国香港、中国台北、高雄、中国澳门 |

每次 API 查询最多 3 个国家，超过 3 个自动分批，批次间随机等待 30-60 秒。

### monitor — 逐城精确监控

```bash
# 搜索所有假期+周末（北京出发）
python main.py monitor

# 从上海出发
python main.py monitor --from 上海

# 只搜法定节假日
python main.py monitor --holidays-only

# 只搜最近一个假期
python main.py monitor --next

# 测试模式
python main.py monitor --test

# 无头模式
python main.py monitor --headless

# 显示调试日志
python main.py monitor --debug
```

## 参数说明

### discover 子命令

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--from <城市>` | 出发城市（中文名或三字码） | 北京 |
| `--group <城市列表>` | 多人同行模式，逗号分隔出发城市 | - |
| `--min-together <天>` | 多人同行最小同游天数 | 2 |
| `--abroad [国家列表]` | 国际航班搜索，不带值=随机3国，带值=逗号分隔 | - |
| `--holidays-only` | 只搜索法定节假日 | 搜索全部 |
| `--next` | 只搜索最近一个假期/周末 | 搜索全部 |
| `--dates <日期>` | 只搜索指定日期（逗号分隔，YYYY-MM-DD） | 自动计算 |
| `--max-price <元>` | 最高价格过滤 | 0（不过滤） |
| `--min-price <元>` | 最低价格过滤 | 0（不过滤） |
| `--min-stay <天>` | 最少游玩天数 | 0（不过滤） |
| `--max-stay <天>` | 最多游玩天数 | 0（不过滤） |
| `--min-dist <km>` | 目的地最小距离（公里） | 0（不过滤） |
| `--max-dist <km>` | 目的地最大距离（公里） | 0（不过滤） |
| `--min-flight-time <分钟>` | 单程最短飞行时长 | 0（不过滤） |
| `--max-flight-time <分钟>` | 单程最长飞行时长 | 0（不过滤） |
| `--test` | 测试模式：只搜索1个时段 | - |
| `--no-headless` | 显示浏览器窗口（默认无头） | 无头模式 |
| `--debug` | 显示调试日志 | - |

### monitor 子命令

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--from <城市>` | 出发城市（中文名或三字码） | 北京 |
| `--holidays-only` | 只搜索法定节假日 | 搜索全部 |
| `--next` | 只搜索最近一个假期 | 搜索全部 |
| `--dates <日期>` | 只搜索指定日期（逗号分隔） | 自动计算 |
| `--dest-file <文件>` | 目的地白名单文件 | 搜索全部城市 |
| `--test` | 测试模式 | - |
| `--fresh` | 忽略断点，重新搜索 | 自动续搜 |
| `--headless` | 无头模式 | 有头模式 |
| `--debug` | 显示调试日志 | - |

## 配置说明

编辑 `config.py`：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DEPARTURE_CITY_CODE` | `"BJS"` | 默认出发城市代码（`--from` 可覆盖） |
| `DEPARTURE_CITY_NAME` | `"北京"` | 默认出发城市名 |
| `MAX_DISCOUNT_RATE` | `0.4` | 最大折扣率（monitor 使用），4折 = 0.4 |
| `MIN_DISTANCE_KM` | `400` | 目的地最小距离km（monitor 使用） |
| `SEARCH_DAYS_AHEAD` | `180` | 搜索未来多少天内的假期 |
| `REQUEST_DELAY` | `4.0` | 请求间隔（秒），防反爬 |
| `MIN_STAY_DAYS` | `0` | 最少游玩天数过滤默认值（`--min-stay` 可覆盖） |
| `MAX_STAY_DAYS` | `0` | 最多游玩天数过滤默认值（`--max-stay` 可覆盖） |
| `HOLIDAYS` | 2026年假期 | 法定节假日列表，按国务院公告调整 |

### 出行天数计算规则

| 类型 | 假期天数 n | 出行天数范围 |
|------|-----------|-------------|
| 周末 | 2 | n ~ n+2 天（即 2~4 天） |
| 节假日 | 视假期而定 | n ~ n+4 天（如劳动节 5~9 天） |

### 出发日期计算规则

| 类型 | 最早出发 | 最晚出发 |
|------|---------|---------|
| 周末 | 假期前1天 | 假期首日 |
| 节假日 | 假期前2天 | 假期首日 |

## 断点续搜（monitor）

搜索量大时可能因反爬被中止，monitor 支持断点续搜：

```bash
# 中断后再次运行会自动从上次位置继续
python main.py monitor

# 强制从头搜索
python main.py monitor --fresh
```

进度保存在 `.search_checkpoint.json`，搜索完成后自动清除。

## 自动重试（monitor）

```bash
# 全自动搜索，被反爬中止后 10 分钟自动重试
bash auto_retry.sh

# 支持所有 monitor 参数
bash auto_retry.sh --from 上海 --holidays-only
```

## 支持的出发城市

`--from` 支持以下城市（中文名或三字码均可）：

北京(BJS)、上海(SHA)、广州(CAN)、深圳(SZX)、成都(CTU)、杭州(HGH)、武汉(WUH)、西安(SIA)、重庆(CKG)、南京(NKG)、长沙(CSX)、昆明(KMG)、天津(TSN)、青岛(TAO)、大连(DLC)、厦门(XMN)、沈阳(SHE)、哈尔滨(HRB)、郑州(CGO)、福州(FOC)、济南(TNA)、合肥(HFE)、贵阳(KWE)、南宁(NNG)、海口(HAK)、三亚(SYX)、拉萨(LXA)、乌鲁木齐(URC)、兰州(LHW)、银川(INC)、西宁(XNN)、呼和浩特(HET)、太原(TYN)、石家庄(SJW)、长春(CGQ)、南昌(KHN)、珠海(ZUH)、无锡(WUX)、宁波(NGB)、温州(WNZ)

不在列表中的城市可直接使用三字码：`--from HRB`

## 文件结构

```
flight-monitor/
├── main.py              # 统一入口（子命令分发、logging 配置）
├── models.py            # 数据模型（dataclass + enum）
├── config.py            # 配置文件（假期、折扣、过滤等）
├── shared.py            # 共享工具（城市数据、坐标、距离、日期解析）
├── date_utils.py        # 日期计算（假期/周末日期范围、出行天数）
├── browser.py           # 浏览器管理（Chrome 启动/关闭/JS 注入）
├── ctrip_api.py         # 携程 API 客户端（Selenium + JS 拦截）
├── discover.py          # discover 子命令入口（编排搜索流程）
├── discover_api.py      # discover API 捕获/重放/搜索
├── discover_parse.py    # discover 响应解析/过滤/去重
├── discover_print.py    # discover 结果格式化输出
├── discover_group.py    # discover 多人同行搜索
├── discover_abroad.py   # discover 国际航班搜索
├── monitor.py           # monitor 子命令：逐城精确监控
├── auto_retry.sh        # 自动重试脚本（monitor 专用）
├── requirements.txt     # Python 依赖
└── README.md
```

## 输出示例

### discover 单人模式

```
# 携程 FuzzySearch 特价机票

> 出发城市: 北京 | 目的地: 全中国 | 查询时间: 2026-04-01

## 清明节

| # | 目的地 | 最低价 | 游玩天数 | 休假天数 | 去程日期   | 起飞  | 返程日期   | 起飞  | 去程航班          | 时长   | 返程航班          | 时长   | 省份 | 景点推荐               |
|---|--------|-------|---------|---------|-----------|------|-----------|------|------------------|--------|------------------|--------|------|----------------------|
| 1 | 太原   | ¥176  | 2天     | 0       | 2026-04-01 | 06:40 | 2026-04-03 | 09:05 | CA1125(中国国航)  | 1h15m  | CA1146(中国国航)  | 1h15m  | 山西 | 晋祠博物馆, 五台山    |
| 2 | 威海   | ¥195  | 3天     | 0       | 2026-04-01 | 18:00 | 2026-04-04 | 10:00 | 9C8925(春秋航空)  | 1h10m  | CZ5937(南方航空)  | 1h30m  | 山东 | 刘公岛景区, 成山头    |
```

### discover 多人同行模式

```
# 多人同行特价机票 (北京+武汉)

> 查询时间: 2026-04-07

## 周末(4/11-4/12)

| # | 目的地 | 北京→ | 武汉→ | 合计 | 同游天数 | 同游时段 | 省份 |
|---|--------|------|------|------|---------|----------|------|
| 1 | 北京   | ¥0(本地) | ¥819 | **¥819** | 3天 | 04/11 23:15~04/14 21:05 | 北京 |
| 2 | 武汉   | ¥822 | ¥0(本地) | **¥822** | 3天 | 04/12 00:15~04/14 08:40 | 湖北 |
| 3 | 大连   | ¥229(高铁) | ¥599 | **¥828** | 3天 | 04/11 18:40~04/14 18:55 | 辽宁 |
| 4 | 天津   | ¥54(高铁) | ¥800 | **¥854** | 2天 | 04/11 15:55~04/13 15:45 | 天津 |
```
