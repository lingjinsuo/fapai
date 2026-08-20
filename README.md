# 法拍监控系统 (fapai)

监控淘宝 / 阿里资产司法拍卖网站 (`https://sf.taobao.com`) 的标的，自动归档到 MySQL 数据库。

> 原型参考：[xianyu-app-deal-price](../xianyu-app-deal-price) 的代码风格与功能布局

## 功能特性

- **多关键词监控**：每个关键词每日自动抓取
- **智能终止**：遇到数据库中已存在且「已结束」(done/closed) 的标的自动停止抓取
- **每日快照**：每个标的每天保留一条历史记录，用于价格趋势分析
- **定时任务**：每日 09:00 自动跑批（可在 `config.py` 中修改）
- **Web 控制台**：左侧导航 + SSE 实时日志面板
- **手动触发**：前端按钮一键抓取

## 快速开始

### 1. 初始化数据库

```bash
mysql -h127.0.0.1 -P4000 -uroot -p123456 < sql/fp_init.sql
```

### 2. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 修改配置（可选）

所有配置集中在 `config.py`，根据需要调整：

- `DB_CONFIG`：数据库连接
- `FA_PAI_LIST_URL` / `FA_PAI_BASE_PARAMS` / `FA_PAI_HEADERS`：抓取配置
- `SCRAPER_PAGE_INTERVAL_RANGE`：每次请求随机间隔（默认 3~8 秒）
- `SCHEDULE_DAILY_TIME`：每日跑批时间（默认 `09:00`）
- `WEB_PORT`：Web 端口（默认 `5002`）

### 4. 启动 Web 服务（含定时任务）

```bash
bash run.sh
# 或：
python3 web.py
```

访问 http://127.0.0.1:5002

**启动行为**：
- 启动 web 时**不会**立刻抓数据（避免在非工作时间浪费带宽/触发风控）
- 内置 APScheduler 已在后台运行，每天 `SCHEDULE_DAILY_TIME`（默认 09:00）自动跑批
- 如需立即抓取：
  - 前端 `/fp-keys` 页面 → 点击「立即抓取全部」或单个关键词的「抓取」按钮
  - 或调用 API：`POST /api/fp/run-now`

> `scheduler.py` 保留作为独立运行入口，效果一致。

## 目录结构

```
fapai/
├── config.py            # 全局配置
├── database.py          # 数据库操作
├── fp_scraper.py        # 抓取主程序
├── scheduler.py         # 定时调度器
├── web.py               # Flask Web 服务
├── requirements.txt     # 依赖
├── run.sh               # 启动脚本
├── sql/
│   └── fp_init.sql      # 初始化 SQL 脚本
├── templates/           # HTML 模板
│   ├── base.html
│   ├── fp_keys.html
│   ├── fp_items.html
│   ├── fp_item_detail.html
│   └── fp_logs.html
├── logs/                # 运行日志
└── tmp_data/            # 抓取中间数据
```

## 数据库表（fp_ 前缀）

- `fp_keywords`：监控关键词
- `fp_items`：拍卖标的（最新状态）
- `fp_item_history`：标的每日快照
- `fp_run_logs`：抓取运行日志

## 手动抓取

```bash
# 抓取所有启用的关键词
python3 fp_scraper.py

# 抓取单个关键词
python3 fp_scraper.py --keyword 服务器

# 抓取指定 ID 的关键词
python3 fp_scraper.py --keyword-id 3
```

## 注意事项

- 淘宝 / 阿里资产对未登录访问会触发**验证码拦截**（返回 `action=captcha`）。
  脚本会自动检测验证码并重试，但长期抓取建议使用**已登录的 Cookie**。
- 翻页上限由 `SCRAPER_MAX_PAGES_PER_KEYWORD` 控制（默认 50）。
- 默认每关键词抓取间隔 3~8 秒，可在 `config.py` 中调整。

## 抓取策略说明

`config.py` 中 `SCRAPER_MODE` 控制：

- `'keyword'`（**默认**）：URL 带 `q=关键词` 走淘宝搜索接口，精准命中
- `'homepage'`：URL 不带 q 抓首页全量，再用客户端 title 过滤

**关键参数**：所有请求都自动带上 `_input_charset=utf-8`（在 `FA_PAI_BASE_PARAMS` 中）。
此参数让淘宝切换到搜索模式返回相关结果；缺失则可能返回空数据。

### 停止规则（业务核心）

遍历首页原始数据时，**任意一条**满足以下任一条件，立即停止本次抓取（剩余条目不再处理）：

| 触发条件 | 含义 | 日志 |
|---|---|---|
| `sf_item_id` 已存在数据库中（任意状态） | 重复 | `🛑 标的 XXX 已存在数据库中（重复），停止本次抓取` |
| 标的当前 `status ∈ (done, closed)` | 已结束 | `🛑 标的 XXX 已结束 (status=done)，停止本次抓取` |

## 技术要点：HTTP 后端

按以下优先级选择：

1. **系统 curl**（默认，最稳定）：`subprocess` 调用 `curl` 命令行，淘宝对其 TLS 指纹最友好
2. **curl-cffi**（备选）：模拟 Chrome 120 的 TLS 指纹
3. **requests**（兜底）：仅用于简单场景，可能被风控
