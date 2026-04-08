"""
携程 FuzzySearch 国际航班搜索

负责: 国际航班批量搜索（按国家分批请求）。
"""
import logging
import random
import time

from config import INTL_BATCH_SIZE, CITY_SLEEP_MIN, CITY_SLEEP_MAX
from date_utils import calculate_trip_days
from discover_api import search_fuzzysearch
from discover_parse import filter_results
from discover_print import print_abroad_results

logger = logging.getLogger(__name__)

__all__ = ["run_abroad_search"]


def run_abroad_search(driver, api_template, dep_city_code, dep_city_name, countries, periods, args):
    """
    国际航班搜索
    countries: [{"name": "日本", "code": "JP", "ct": 2}, ...]
    每次 acs 最多 3 个国家，多批次间随机等待 30-60s
    """
    batches = [countries[i:i + INTL_BATCH_SIZE] for i in range(0, len(countries), INTL_BATCH_SIZE)]
    country_names = [c["name"] for c in countries]
    all_period_results = {}

    for i, period in enumerate(periods, 1):
        period_name = period["name"]
        depart_dates = period["depart_dates"]
        trip_days_list = calculate_trip_days(period)

        logger.info(
            "=== [%d/%d] %s (出发: %s~%s, 出行: %s~%s天) — 国际航班 ===",
            i, len(periods), period_name,
            depart_dates[0], depart_dates[-1],
            trip_days_list[0], trip_days_list[-1],
        )

        period_results = []
        for batch_idx, batch in enumerate(batches):
            if batch_idx > 0:
                delay = random.uniform(CITY_SLEEP_MIN, CITY_SLEEP_MAX)
                logger.info("  等待 %.0f 秒后查询下一批国家...", delay)
                time.sleep(delay)

            batch_names = "+".join(c["name"] for c in batch)
            logger.info("  查询批次 %d/%d: %s", batch_idx + 1, len(batches), batch_names)

            results = search_fuzzysearch(
                driver, api_template, dep_city_code, dep_city_name,
                period, acs_list=batch,
            )
            if results:
                results = filter_results(
                    results,
                    max_price=args.max_price,
                    min_price=args.min_price,
                    dep_city_name=dep_city_name,
                    min_stay=args.min_stay,
                    max_stay=args.max_stay,
                )
                logger.info("    → 获取到 %d 条航线", len(results))
                period_results.extend(results)

        period_results.sort(key=lambda x: x["price"])
        all_period_results[period_name] = period_results
        logger.info("  %s 共 %d 条结果", period_name, len(period_results))

    print_abroad_results(all_period_results, dep_city_name, country_names)
