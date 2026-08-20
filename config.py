#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================
法拍监控系统 - 全局配置文件
所有可调整参数均集中在此文件中
============================================
"""

import os

# ========== 数据库配置 ==========
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 4000,
    'user': 'root',
    'password': '123456',
    'database': 'by_hardware',
    'charset': 'utf8mb4'
}

# ========== 文件输出配置 ==========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, 'tmp_data')           # 抓取中间数据
SCREENSHOT_DIR = os.path.join(OUTPUT_DIR, 'screen')       # 预留：截图
LOG_DIR = os.path.join(BASE_DIR, 'logs')                  # 日志目录

# ========== 法拍抓取配置 ==========
# 列表入口 URL（基础地址，不含查询参数）
FA_PAI_LIST_URL = 'https://sf.taobao.com/item_list.htm'

# 基础查询参数（模拟正常浏览器侧栏参数，能一定程度绕过风控）
# 关键参数 _input_charset=utf-8：让服务端知道客户端用 UTF-8 解码，
# 切换为搜索模式（不带这个参数时 q= 可能返回 0 条）
FA_PAI_BASE_PARAMS = {
    '_input_charset': 'utf-8',
    'spm': 'a213w.7398504.search_index_input.1',
    'keywordSource': '5',
    'auction_source': '0',
    'st_param': '-1',
    'auction_start_seg': '-1',
}

# 请求头（UA / Referer / 语言等）
FA_PAI_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Referer': 'https://sf.taobao.com/',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

# 翻页参数名（淘宝法拍 url 中翻页字段）
FA_PAI_PAGE_PARAM = 'p'

# 抓取策略
# - 'keyword'（默认）：URL 带 q=关键词 走淘宝搜索接口，能精准拿到相关标的
# - 'homepage'         ：URL 不带 q 抓首页全量，再用客户端 title 过滤
SCRAPER_MODE = 'keyword'

# 单个关键词最多翻多少页（硬上限；遇空页也会提前停）
SCRAPER_MAX_PAGES_PER_KEYWORD = 50

# 每次请求之间的随机停顿区间（秒） - 避免被风控
SCRAPER_PAGE_INTERVAL_RANGE = (3, 8)

# 单次 HTTP 超时（秒）
SCRAPER_REQUEST_TIMEOUT = 30

# 重试次数与重试间隔（秒）
SCRAPER_RETRY_TIMES = 3
SCRAPER_RETRY_INTERVAL_RANGE = (5, 12)

# 当页面返回验证码/拦截时的关键字检测
CAPTCHA_KEYWORDS = ['_____tmd_____', 'action":"captcha"', 'punish?x5secdata']

# ========== 定时任务配置 ==========
# 每日跑批时间（24h 制，"HH:MM"）。例如 "09:00" 表示每天早上 9 点
SCHEDULE_DAILY_TIME = '12:20'
# 调度器时区
SCHEDULE_TIMEZONE = 'Asia/Shanghai'
# 启动时是否立即先跑一次（True / False）
SCHEDULE_RUN_ON_START = False

# ========== Web 服务配置 ==========
WEB_HOST = '0.0.0.0'
WEB_PORT = 5002
WEB_DEBUG = False

# ========== 应用配置 ==========
APP_NAME = '法拍监控系统'

# ========== 日志配置 ==========
LOG_LEVEL = 'INFO'                       # DEBUG / INFO / WARNING / ERROR
LOG_TO_FILE = True                       # 是否输出到 logs/ 目录
LOG_FILENAME = 'fapai.log'               # 日志文件名
LOG_MAX_BYTES = 10 * 1024 * 1024         # 单文件 10MB
LOG_BACKUP_COUNT = 5                     # 保留 5 个备份

# 标的「已结束」判定（数据库 status 字段值集合）
DONE_STATUSES = ('done', 'closed')
