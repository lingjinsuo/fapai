#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================
法拍监控系统 - 定时调度器
- 使用 APScheduler 的 BackgroundScheduler
- 每日 SCHEDULE_DAILY_TIME 触发一次全量抓取
- 可独立运行：python scheduler.py
============================================
"""

import logging
import sys
import threading
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    SCHEDULE_DAILY_TIME,
    SCHEDULE_TIMEZONE,
    SCHEDULE_RUN_ON_START,
    LOG_DIR,
    LOG_LEVEL,
    APP_NAME,
)

import fp_scraper


def _setup_logger():
    """简单的文件 + 控制台 logger（与项目其他模块解耦）"""
    logger = logging.getLogger("fapai_scheduler")
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    logger.handlers.clear()

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # 文件
    try:
        import os
        os.makedirs(LOG_DIR, exist_ok=True)
        from logging.handlers import RotatingFileHandler
        from config import LOG_FILENAME, LOG_MAX_BYTES, LOG_BACKUP_COUNT
        fh = RotatingFileHandler(
            filename=f"{LOG_DIR}/{LOG_FILENAME}",
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        logger.warning(f"无法创建文件日志: {e}")
    return logger


logger = _setup_logger()


def _parse_time(hhmm):
    """解析 'HH:MM' -> (hour, minute)"""
    try:
        h, m = hhmm.strip().split(":")
        return int(h), int(m)
    except Exception:
        logger.warning(f"SCHEDULE_DAILY_TIME={hhmm!r} 格式错误，回退到 09:00")
        return 9, 0


# 任务触发器 - 全局唯一，加锁防重入
_job_lock = threading.Lock()
_is_running = False


def scheduled_job():
    """每日定时任务 - 全量抓取所有启用的关键词"""
    global _is_running
    if not _job_lock.acquire(blocking=False):
        logger.warning("上一次抓取尚未结束，跳过本次触发")
        return
    try:
        if _is_running:
            logger.warning("任务运行中，跳过")
            return
        _is_running = True
        logger.info(f"⏰ 触发每日抓取任务 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            results = fp_scraper.scrape_all_enabled()
            ok = sum(1 for r in results if r.get('status') == 'success')
            fail = len(results) - ok
            logger.info(f"✅ 每日抓取完成: 成功 {ok} / 失败 {fail} / 共 {len(results)}")
        except Exception as e:
            logger.exception(f"❌ 每日抓取异常: {e}")
        finally:
            _is_running = False
    finally:
        _job_lock.release()


def build_scheduler():
    """构造并启动后台调度器"""
    hour, minute = _parse_time(SCHEDULE_DAILY_TIME)
    sched = BackgroundScheduler(timezone=SCHEDULE_TIMEZONE)
    sched.add_job(
        scheduled_job,
        CronTrigger(hour=hour, minute=minute),
        id="daily_scrape",
        name=f"每日{SCHEDULE_DAILY_TIME}抓取任务",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    return sched


def main():
    logger.info(f"=== {APP_NAME} 调度器启动 ===")
    sched = build_scheduler()
    sched.start()
    if SCHEDULE_RUN_ON_START:
        logger.info("SCHEDULE_RUN_ON_START=True，立即触发一次抓取")
        # 异步触发，避免阻塞调度器主线程
        threading.Thread(target=scheduled_job, daemon=True).start()

    # 打印 next_run_time
    job = sched.get_job("daily_scrape")
    if job:
        logger.info(f"下次抓取时间: {job.next_run_time}")

    logger.info("调度器已进入后台运行，按 Ctrl+C 退出")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("收到退出信号，正在关闭调度器...")
        sched.shutdown(wait=False)
        logger.info("调度器已退出")


if __name__ == "__main__":
    main()
