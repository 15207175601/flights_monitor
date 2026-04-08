#!/usr/bin/env python3
"""
携程特价机票 FuzzySearch 全国特价概览模块
通过携程模糊搜索页面(fuzzysearch)，直接获取指定城市出发到全国的特价往返机票
无需逐个城市搜索，一次请求即可获取所有目的地的最低价

由 main.py discover 子命令调用
"""
import json
import random
import logging

from config import (
    DEPARTURE_CITY_CODE, DEPARTURE_CITY_NAME,
    INTL_BATCH_SIZE,
)
from date_utils import get_all_travel_periods, get_periods_for_dates, calculate_trip_days
from shared import INTL_COUNTRY_MAP, resolve_city
from browser import init_browser, close_browser
from discover_api import discover_api, search_fuzzysearch
from discover_parse import filter_results
from discover_print import print_results, print_search_plan
from discover_group import run_group_search
from discover_abroad import run_abroad_search

from selenium.common.exceptions import WebDriverException

logger = logging.getLogger(__name__)


def run(args):
    """discover 子命令入口，接收 argparse Namespace"""
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 解析出发城市
    if args.from_city:
        dep_city_code, dep_city_name = resolve_city(args.from_city)
    else:
        dep_city_code, dep_city_name = DEPARTURE_CITY_CODE, DEPARTURE_CITY_NAME

    # 多人同行模式: 解析所有出发城市
    travelers = None
    if args.group:
        city_strs = [c.strip() for c in args.group.split(",") if c.strip()]
        if len(city_strs) < 2:
            print("--group 需要至少 2 个出发城市（逗号分隔），如: --group 北京,武汉")
            return
        travelers = [resolve_city(c) for c in city_strs]
        group_label = "+".join(name for _, name in travelers)
        logger.info("多人同行模式: %s", group_label)
        # 多人模式下 dep_city_name 用第一个人的（用于搜索计划显示）
        dep_city_code, dep_city_name = travelers[0]

    # 获取出行时段
    if args.dates:
        try:
            periods = get_periods_for_dates(args.dates)
        except ValueError as e:
            print(f"日期参数错误: {e}")
            return
    else:
        periods = get_all_travel_periods(only_holidays=args.holidays_only)

    if not periods:
        print("未找到需要搜索的出行时段。")
        return

    if args.next_only or args.test:
        periods = periods[:1]

    # 国际航班模式: 解析 --abroad 参数
    abroad_countries = None
    if getattr(args, 'abroad', None) is not None:
        if args.abroad == "":
            # 随机选 3 个国家
            selected = random.sample(list(INTL_COUNTRY_MAP.keys()), INTL_BATCH_SIZE)
            logger.info("随机选择 3 个国家/地区: %s", ", ".join(selected))
        else:
            input_names = [n.strip() for n in args.abroad.split(",") if n.strip()]
            valid, invalid = [], []
            for n in input_names:
                (valid if n in INTL_COUNTRY_MAP else invalid).append(n)
            if invalid:
                print(f"\n以下输入不在支持的国家/地区列表中，已跳过: {', '.join(invalid)}")
                print(f"支持的国家/地区请参考 --help 或 README.md\n")
            selected = valid

        if not selected:
            print("没有有效的国家/地区可查询")
            return

        abroad_countries = [{"name": n, "code": INTL_COUNTRY_MAP[n], "ct": 2} for n in selected]
        country_label = "+".join(selected)
        logger.info("国际航班模式: %s出发 → %s", dep_city_name, country_label)

    if abroad_countries:
        country_label = "+".join(c["name"] for c in abroad_countries)
        print_search_plan(periods, f"{dep_city_name} → {country_label}")
    elif travelers:
        group_label = "+".join(name for _, name in travelers)
        print_search_plan(periods, group_label)
    else:
        print_search_plan(periods, dep_city_name)

    # 启动浏览器
    driver = None
    tmp_profile = None
    try:
        driver, tmp_profile = init_browser(headless=args.headless)

        # 第 1 步: 打开 fuzzysearch 页面，捕获 API 请求模板
        api_template = discover_api(driver)

        if api_template:
            logger.info("API 模板捕获成功")
            if api_template.get("body"):
                logger.debug("API 请求体: %s", json.dumps(api_template["body"], ensure_ascii=False)[:500])
        else:
            logger.warning("未捕获到 API 模板，将使用页面导航模式")

        # 第 2 步: 国际 / 多人 / 单人模式
        if abroad_countries:
            run_abroad_search(driver, api_template, dep_city_code, dep_city_name,
                              abroad_countries, periods, args)
        elif travelers:
            run_group_search(driver, api_template, travelers, periods, args)
        else:
            # 原有单人逻辑
            all_period_results = {}

            for i, period in enumerate(periods, 1):
                period_name = period["name"]
                depart_dates = period["depart_dates"]
                trip_days = calculate_trip_days(period)

                logger.info(
                    "=== [%d/%d] %s (出发: %s~%s, 出行: %s~%s天) ===",
                    i, len(periods), period_name,
                    depart_dates[0], depart_dates[-1],
                    trip_days[0], trip_days[-1],
                )

                results = search_fuzzysearch(
                    driver, api_template,
                    dep_city_code, dep_city_name,
                    period,
                )

                if results:
                    results = filter_results(
                        results,
                        max_price=args.max_price,
                        min_price=args.min_price,
                        min_stay=args.min_stay,
                        max_stay=args.max_stay,
                        dep_city_name=dep_city_name,
                        min_dist=args.min_dist,
                        max_dist=args.max_dist,
                        min_flight_time=args.min_flight_time,
                        max_flight_time=args.max_flight_time,
                    )
                    logger.info("    → 过滤后 %d 条航线数据", len(results))
                else:
                    logger.warning("    → 未获取到数据")

                all_period_results[period_name] = results
                logger.info("=== %s 搜索完成, 共 %d 条数据 ===\n", period_name, len(results))

            print_results(all_period_results, dep_city_name)

    except KeyboardInterrupt:
        print("\n\n用户中断搜索 (Ctrl+C)")
    except WebDriverException as e:
        logger.error("浏览器异常: %s", e)
    finally:
        close_browser(driver, tmp_profile)
