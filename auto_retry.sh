#!/bin/bash
# 携程特价机票自动重试脚本
# 当搜索被反爬中止(退出码2)时，10分钟后自动注册一次性cron任务断点续爬
# 搜索全部完成(退出码0)则不再重试
#
# 用法:
#   bash auto_retry.sh                   # 默认参数(北京出发，所有假期)
#   bash auto_retry.sh --from 上海        # 自定义参数
#   bash auto_retry.sh --holidays-only   # 只搜法定节假日

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${SCRIPT_DIR}/../myenv/bin/python"
MAIN="${SCRIPT_DIR}/main.py"
LOG="${SCRIPT_DIR}/flight_monitor.log"

# 接收额外参数(如 --from 上海 --holidays-only 等)
EXTRA_ARGS="$@"

echo "$(date '+%Y-%m-%d %H:%M:%S') 开始搜索 (参数: ${EXTRA_ARGS})" >> "$LOG"

# main.py 会自动检测断点文件续搜，无需手动加 --resume
"$PYTHON" "$MAIN" monitor $EXTRA_ARGS 2>&1 | tee -a "$LOG"
EXIT_CODE=${PIPESTATUS[0]}

echo "$(date '+%Y-%m-%d %H:%M:%S') 搜索退出，退出码: $EXIT_CODE" >> "$LOG"

if [ "$EXIT_CODE" -eq 2 ]; then
    # 被反爬中止，10分钟后重试
    RETRY_TIME=$(date -v+10M '+%M %H %d %m *' 2>/dev/null || date -d '+10 minutes' '+%M %H %d %m *' 2>/dev/null)
    if [ -z "$RETRY_TIME" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') 无法计算重试时间，请手动重试" >> "$LOG"
        echo "搜索被中止，请稍后手动运行: bash auto_retry.sh ${EXTRA_ARGS}"
        exit 2
    fi

    # 写入一次性 cron 任务（直接透传用户原始参数，不强制 --headless）
    CLEAN_ARGS=$(echo "$EXTRA_ARGS" | xargs)
    CRON_CMD="$RETRY_TIME cd $SCRIPT_DIR && bash auto_retry.sh ${CLEAN_ARGS} # flight-monitor-retry"
    # 先移除旧的重试任务，再添加新的
    (crontab -l 2>/dev/null | grep -v 'flight-monitor-retry'; echo "$CRON_CMD") | crontab -

    RETRY_DISPLAY=$(date -v+10M '+%H:%M' 2>/dev/null || date -d '+10 minutes' '+%H:%M' 2>/dev/null)
    echo "$(date '+%Y-%m-%d %H:%M:%S') 已注册 cron 重试任务，将在 ${RETRY_DISPLAY} 自动续搜" >> "$LOG"
    echo ""
    echo "搜索被反爬中止，已自动注册 10 分钟后重试 (${RETRY_DISPLAY})"
    echo "查看日志: tail -f ${LOG}"
elif [ "$EXIT_CODE" -eq 0 ]; then
    # 搜索完成，清理 cron 中的重试任务
    (crontab -l 2>/dev/null | grep -v 'flight-monitor-retry') | crontab -
    echo "$(date '+%Y-%m-%d %H:%M:%S') 搜索全部完成" >> "$LOG"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') 搜索异常退出 (退出码: $EXIT_CODE)" >> "$LOG"
fi
