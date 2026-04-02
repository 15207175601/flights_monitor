#!/usr/bin/env python3
"""
携程特价机票工具 - 统一入口

子命令:
    discover  FuzzySearch 全国特价概览（一次请求获取全部目的地）
    monitor   逐城精确特价监控（支持断点续搜、折扣过滤）

用法:
    python main.py discover --from 上海 --max-price 500
    python main.py monitor --from 北京 --holidays-only
    python main.py discover --help
    python main.py monitor --help
"""
import argparse
import sys
import os

# 确保能导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DEPARTURE_CITY_NAME, MIN_STAY_DAYS, MAX_STAY_DAYS


def build_parser():
    parser = argparse.ArgumentParser(
        description="携程特价机票工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python main.py discover --from 上海 --max-price 500\n"
               "  python main.py monitor --from 北京 --holidays-only\n"
               "  python main.py discover --test\n",
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # === discover 子命令 ===
    dp = subparsers.add_parser(
        "discover",
        help="FuzzySearch 全国特价概览（推荐，速度快）",
        description="通过携程 FuzzySearch 一次请求获取全国所有目的地特价往返机票",
    )
    # 搜索范围
    dp.add_argument(
        "--from", dest="from_city", type=str, default=None,
        help=f"出发城市名或三字码 (默认: {DEPARTURE_CITY_NAME})，如: --from 上海",
    )
    dp.add_argument(
        "--holidays-only", action="store_true",
        help="只搜索法定节假日，不搜索普通周末",
    )
    dp.add_argument(
        "--next", dest="next_only", action="store_true",
        help="只搜索最近的一个假期/周末",
    )
    dp.add_argument(
        "--dates", type=str, default=None,
        help="只搜索指定日期(逗号分隔), 如: --dates 2026-04-04,2026-05-01",
    )
    # 过滤
    dp.add_argument(
        "--max-price", type=int, default=0,
        help="最高价格过滤(元), 0=不过滤",
    )
    dp.add_argument(
        "--min-price", type=int, default=0,
        help="最低价格过滤(元), 0=不过滤",
    )
    dp.add_argument(
        "--min-stay", type=int, default=MIN_STAY_DAYS,
        help=f"最少游玩天数过滤, 0=不过滤 (默认: {MIN_STAY_DAYS})",
    )
    dp.add_argument(
        "--max-stay", type=int, default=MAX_STAY_DAYS,
        help=f"最多游玩天数过滤, 0=不过滤 (默认: {MAX_STAY_DAYS})",
    )
    # 运行模式
    dp.add_argument("--test", action="store_true", help="测试模式: 只搜索1个时段")
    dp.add_argument("--debug", action="store_true", help="显示调试日志")
    dp.add_argument(
        "--headless", action="store_true", default=True,
        help="无头模式（默认开启）",
    )
    dp.add_argument(
        "--no-headless", dest="headless", action="store_false",
        help="关闭无头模式，显示浏览器窗口",
    )

    # === monitor 子命令 ===
    mp = subparsers.add_parser(
        "monitor",
        help="逐城精确特价监控（支持断点续搜）",
        description="逐城市搜索具体航班+折扣，结果更详细，支持断点续搜",
    )
    mp.add_argument(
        "--from", dest="from_city", type=str, default=None,
        help=f"出发城市名或三字码 (默认: {DEPARTURE_CITY_NAME})",
    )
    mp.add_argument(
        "--holidays-only", action="store_true",
        help="只搜索法定节假日，不搜索普通周末",
    )
    mp.add_argument(
        "--next", dest="next_only", action="store_true",
        help="只搜索最近的一个假期/周末",
    )
    mp.add_argument(
        "--dates", type=str, default=None,
        help="指定搜索日期（逗号分隔）",
    )
    mp.add_argument(
        "--dest-file", default=None,
        help="目的地白名单文件路径（txt，每行一个城市名）",
    )
    mp.add_argument("--test", action="store_true", help="测试模式：只搜2个目的地+最近1个假期")
    mp.add_argument("--debug", action="store_true", help="显示调试日志")
    mp.add_argument("--headless", action="store_true", help="无头模式运行")
    mp.add_argument("--fresh", action="store_true", help="忽略断点，强制从头开始搜索")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "discover":
        from discover import run
        run(args)
    elif args.command == "monitor":
        from monitor import run
        run(args)


if __name__ == "__main__":
    main()
