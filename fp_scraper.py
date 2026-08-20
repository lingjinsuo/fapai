#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================
法拍监控系统 - 抓取主程序
- 单关键词: 逐页抓取 sf.taobao.com 列表
- 终止条件: 数据库中该标的「已结束」(done/closed) → 停止本次抓取
- 同时维护 fp_items（最新）和 fp_item_history（每日快照）
============================================

使用方式:
  python fp_scraper.py                       # 抓取所有启用的关键词
  python fp_scraper.py --keyword 服务器        # 只抓指定关键词（不存在会自动新增）
  python fp_scraper.py --keyword-id 3         # 只抓指定 ID 的关键词
  python fp_scraper.py --once                 # 同无参数，但 scheduler 调用时用
"""

import argparse
import json
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from urllib.parse import urlencode, quote

# 备选方案：curl_cffi（仅在 curl 不可用时启用）
try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except Exception:
    HAS_CURL_CFFI = False
    cffi_requests = None

import database as db
from config import (
    FA_PAI_LIST_URL,
    FA_PAI_BASE_PARAMS,
    FA_PAI_HEADERS,
    FA_PAI_PAGE_PARAM,
    SCRAPER_MAX_PAGES_PER_KEYWORD,
    SCRAPER_PAGE_INTERVAL_RANGE,
    SCRAPER_REQUEST_TIMEOUT,
    SCRAPER_RETRY_TIMES,
    SCRAPER_RETRY_INTERVAL_RANGE,
    SCRAPER_MODE,
    CAPTCHA_KEYWORDS,
    APP_NAME,
)

LIST_DATA_REGEX = re.compile(
    r'<script[^>]*id="sf-item-list-data"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


# ========== 日志（带 SSE 推送） ==========

def _log(msg, level="info"):
    """统一日志 - 同时输出到 stdout 和 SSE 队列（如已初始化）"""
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        from web import send_log_to_frontend  # 避免 web 未加载时报错
        send_log_to_frontend(line)
    except Exception:
        pass


# ========== HTTP 请求 ==========

def _build_session():
    """
    构造 HTTP 会话
    - 默认用 subprocess 调用系统 curl（最稳定，淘宝对其 TLS 指纹最友好）
    - 备选：curl_cffi（仅在 curl 不可用时启用）
    """
    # 检查 curl 是否可用
    curl_ok = False
    try:
        r = subprocess.run(['curl', '--version'], capture_output=True, timeout=5)
        curl_ok = (r.returncode == 0)
    except Exception:
        curl_ok = False

    if curl_ok:
        class _CurlSession:
            def __init__(self):
                self._headers = dict(FA_PAI_HEADERS)
                self.backend = 'curl'
            def get(self, url, timeout=None):
                # 用 curl 命令行，TLS 指纹 = curl/libcurl（淘宝对其友好）
                cmd = [
                    'curl', '-sL',
                    '--max-time', str(int(timeout or SCRAPER_REQUEST_TIMEOUT)),
                    '-A', self._headers['User-Agent'],
                    '-H', f"Referer: {self._headers.get('Referer','')}",
                    '-H', f"Accept-Language: {self._headers.get('Accept-Language','zh-CN,zh;q=0.9')}",
                    url,
                ]
                proc = subprocess.run(cmd, capture_output=True, timeout=timeout or SCRAPER_REQUEST_TIMEOUT + 10)
                return _CurlResponse(proc.stdout)
        return _CurlSession()

    if HAS_CURL_CFFI:
        class _CffiSession:
            def __init__(self):
                self._headers = dict(FA_PAI_HEADERS)
                self.backend = 'curl_cffi'
            def get(self, url, timeout=None):
                return cffi_requests.get(
                    url, headers=self._headers, timeout=timeout or SCRAPER_REQUEST_TIMEOUT,
                    impersonate='chrome120',
                )
        return _CffiSession()

    # 最后的兜底
    class _ReqSession:
        def __init__(self):
            self._headers = dict(FA_PAI_HEADERS)
            self.backend = 'requests'
        def get(self, url, timeout=None):
            import requests
            return requests.get(
                url, headers=self._headers, timeout=timeout or SCRAPER_REQUEST_TIMEOUT,
            )
    return _ReqSession()


class _CurlResponse:
    """subprocess curl 的响应包装，对齐 requests 的 .content 接口"""
    def __init__(self, raw_bytes):
        self._raw = raw_bytes
    @property
    def content(self):
        return self._raw
    def raise_for_status(self):
        if not self._raw:
            raise RuntimeError('curl returned empty body')


def fetch_page(session, keyword, page=1, use_keyword_search=None):
    """
    抓取一页列表 HTML，返回 (html, used_url)

    - use_keyword_search=None（默认）：按 SCRAPER_MODE 配置（'keyword' / 'homepage'）
    - use_keyword_search=True：强制按 ?q=keyword 搜索
    - use_keyword_search=False：强制抓首页（不带 q）
    """
    params = dict(FA_PAI_BASE_PARAMS)
    if use_keyword_search is None:
        use_keyword_search = (SCRAPER_MODE == 'keyword')
    if use_keyword_search and keyword:
        params['q'] = keyword
    params[FA_PAI_PAGE_PARAM] = page

    url = f"{FA_PAI_LIST_URL}?{urlencode(params)}"
    resp = session.get(url, timeout=SCRAPER_REQUEST_TIMEOUT)
    resp.raise_for_status()
    raw = resp.content
    try:
        html = raw.decode('gbk', errors='ignore')
    except Exception:
        html = raw.decode('utf-8', errors='ignore')
    return html, url


def is_captcha_page(html):
    """检查是否触发了验证码拦截页"""
    if not html:
        return True
    for kw in CAPTCHA_KEYWORDS:
        if kw in html:
            return True
    return False


def title_matches(title, keyword):
    """
    客户端过滤：标题中是否含关键词

    规则：
    - 关键词为空 → 全部命中
    - 标题为空 → 不命中
    - 否则把关键词按空白拆成多个 token，任一 token 出现在标题中就算命中
      例如 "服务器拍卖" 拆成 ["服务器", "拍卖"]，标题 "三明市传媒..." 不含，
      但 "61 台微型服务器" 命中
    """
    if not keyword:
        return True
    if not title:
        return False
    title_lower = str(title).lower()
    # 拆分关键词（按空白）
    tokens = [t for t in keyword.split() if t]
    if not tokens:
        # 没有空格时，整串匹配
        return keyword.lower() in title_lower
    # 任一 token 命中即返回 True
    return any(t.lower() in title_lower for t in tokens)


def search_mode_all_match(title, keyword):
    """
    搜索模式下：所有服务端返回的 item 都已经过服务端 q= 过滤，
    直接全部入库即可，不再做客户端 title 过滤（避免误杀）。
    """
    return True


def parse_list_data(html):
    """
    从页面 HTML 中提取嵌入的 sf-item-list-data JSON
    返回 list[dict] 或 None
    """
    m = LIST_DATA_REGEX.search(html)
    if not m:
        return None
    raw = m.group(1)
    try:
        data = json.loads(raw)
    except Exception:
        cleaned = re.sub(r'\bundefined\b', 'null', raw)
        try:
            data = json.loads(cleaned)
        except Exception:
            return None
    if isinstance(data, dict):
        return data.get('data') or []
    if isinstance(data, list):
        return data
    return None


# ========== 抓取核心 ==========

def scrape_keyword(keyword_row, session=None):
    """
    抓取单个关键词（仅首页 1 页）：

      1) 请求首页，不带 q（拿到原始全量 ~60 条）
      2) 每一条原始数据都打印（ID / 标题 / 状态 / 当前价）
      3) 按顺序遍历原始列表：
         - 若 sf_item_id 已存在数据库中（任意状态）→ 视为「重复」，立即停止抓取
         - 若 sf_item_id 当前 status ∈ done/closed → 视为「已结束」，立即停止抓取
         - 否则 upsert + 写每日快照
      4) 标题含关键词的会在入库的同时打 [命中] 标记

    返回 dict 统计信息
    """
    if isinstance(keyword_row, dict):
        kw_id = keyword_row['id']
        kw_name = keyword_row['keyword']
    else:
        kw_id = None
        kw_name = str(keyword_row)

    # 若 kw_id 为空，先确保 DB 中存在
    if kw_id is None:
        kw_id = db.add_keyword(kw_name)
        _log(f"🔖 自动新增关键词: {kw_name} (id={kw_id})")

    start_at = datetime.now()
    pages = 0
    scanned_total = 0    # 抓到的原始条数
    new_cnt = 0
    updated_cnt = 0
    skipped_repeat = 0
    skipped_done = 0
    stopped = False
    stop_reason = None
    error_msg = None

    session = session or _build_session()
    _log(f"\n{'='*60}")
    _log(f"🚀 开始抓取关键词: {kw_name} (id={kw_id})  [仅首页第 1 页]")
    _log(f"{'='*60}")

    # ========== 仅抓第 1 页 ==========
    page = 1
    html = None
    used_url = None
    last_err = None
    for attempt in range(1, SCRAPER_RETRY_TIMES + 1):
        try:
            html, used_url = fetch_page(session, kw_name, page)
            # 在每次成功拿到响应后立刻打印 URL 和关键信息
            _log(f"🌐 抓取 URL: {used_url}")
            _log(f"🔧 后端: {getattr(session, 'backend', 'unknown')}  | 尝试: 第 {attempt} 次")
            _log(f"📦 响应字节: {len(html.encode('utf-8'))} chars  |  is_captcha: {is_captcha_page(html)}")
            if is_captcha_page(html):
                last_err = "触发验证码拦截 (action=captcha)"
                _log(f"   ⚠️ 第 {attempt} 次：{last_err}，等待后重试")
                time.sleep(random.uniform(*SCRAPER_RETRY_INTERVAL_RANGE))
                continue
            break
        except Exception as e:
            last_err = f"请求异常: {e}"
            _log(f"   ⚠️ 第 {attempt} 次：{last_err}")
            time.sleep(random.uniform(*SCRAPER_RETRY_INTERVAL_RANGE))
    if html is None or is_captcha_page(html):
        error_msg = last_err or "页面为空 / 被拦截"
        _log(f"❌ 关键词 {kw_name} 抓取失败：{error_msg}")
        if used_url:
            _log(f"   最后一次请求的 URL: {used_url}")
    else:
        items = parse_list_data(html)
        pages = 1

        if not items:
            _log(f"📄 第 1 页无数据，停止")
            _log(f"   URL: {used_url}")
        else:
            scanned_total = len(items)
            _log(f"📄 第 1 页: 原始 {scanned_total} 条  |  来自: {used_url}")
            _log(f"{'─'*60}")
            _log(f"{'序号':<4} {'标的ID':<16} {'状态':<8} {'当前价':<12} {'标题（前40字）'}")
            _log(f"{'─'*60}")

            hit_stop = False
            use_search_mode = (SCRAPER_MODE == 'keyword')
            for idx, it in enumerate(items, 1):
                sf_id = it.get('id')
                title = (it.get('title') or '').replace('\n', ' ').strip()
                status = it.get('status') or '-'
                cur_price = it.get('currentPrice')
                price_str = f"{float(cur_price):,.2f}" if cur_price is not None else '-'

                # 命中判定：
                # - 搜索模式 (SCRAPER_MODE='keyword')：服务端已过滤，全部命中
                # - 首页模式 (SCRAPER_MODE='homepage')：客户端按 title 匹配
                if use_search_mode:
                    matched_kw = True
                    tag = ' [服务端]'
                else:
                    matched_kw = title_matches(title, kw_name)
                    tag = ' [命中]' if matched_kw else ''

                if not sf_id:
                    _log(f"{idx:<4} {'-':<16} {status:<8} {price_str:<12} {title[:40]}{tag}")
                    continue

                # 已结束 → 停止
                if status in ('done', 'closed'):
                    _log(f"{idx:<4} {sf_id:<16} {status:<8} {price_str:<12} {title[:40]}{tag}")
                    _log(f"   🛑 标的 {sf_id} 已结束 (status={status})，停止本次抓取")
                    hit_stop = True
                    stopped = True
                    stop_reason = f"hit_done:{sf_id}"
                    skipped_done += 1
                    break

                # 已存在（任意状态）→ 视为重复，停止
                if db.is_item_seen(sf_id):
                    _log(f"{idx:<4} {sf_id:<16} {status:<8} {price_str:<12} {title[:40]}{tag}")
                    _log(f"   🛑 标的 {sf_id} 已存在数据库中（重复），停止本次抓取")
                    hit_stop = True
                    stopped = True
                    stop_reason = f"repeat:{sf_id}"
                    skipped_repeat += 1
                    break

                # 标题不含关键词（仅首页模式）→ 跳过入库
                if not matched_kw:
                    _log(f"{idx:<4} {sf_id:<16} {status:<8} {price_str:<12} {title[:40]}{tag}")
                    continue

                # 命中 + 新标的 → 入库
                item_pk, is_new = db.upsert_fp_item(it, keyword_id=kw_id)
                if is_new:
                    new_cnt += 1
                    action = '🆕 新增'
                else:
                    updated_cnt += 1
                    action = '🔄 更新'
                db.upsert_item_history(sf_id, item_pk, it)
                _log(f"{idx:<4} {sf_id:<16} {status:<8} {price_str:<12} {title[:40]}{tag}  ← {action}")

            _log(f"{'─'*60}")

    end_at = datetime.now()
    duration = int((end_at - start_at).total_seconds())
    # 状态：出错=failed；遇到停止信号=stopped；其他=success
    if error_msg:
        status = "failed"
    elif stopped:
        status = "stopped"
    else:
        status = "success"

    _log(f"\n📊 关键词 {kw_name} 抓取完成: "
         f"扫到原始={scanned_total} 新增={new_cnt} 更新={updated_cnt} "
         f"命中={new_cnt + updated_cnt} 耗时={duration}s 状态={status}"
         + (f"  停止原因={stop_reason}" if stop_reason else ""))

    db.update_keyword_run_status(kw_id, new_cnt + updated_cnt, status, error=error_msg)
    db.insert_run_log(
        keyword_id=kw_id, keyword_name=kw_name,
        start_at=start_at, end_at=end_at,
        pages_scanned=pages, items_found=scanned_total,
        items_new=new_cnt, items_updated=updated_cnt,
        status=status, error_msg=error_msg,
    )

    return {
        'keyword_id': kw_id,
        'keyword': kw_name,
        'pages': pages,
        'scanned_total': scanned_total,
        'found': new_cnt + updated_cnt,
        'new': new_cnt,
        'updated': updated_cnt,
        'skipped_repeat': skipped_repeat,
        'skipped_done': skipped_done,
        'duration': duration,
        'status': status,
        'stopped_by_done_or_repeat': stopped,
        'stop_reason': stop_reason,
        'error': error_msg,
    }


def scrape_all_enabled():
    """抓取所有启用的关键词"""
    keywords = db.get_enabled_keywords()
    if not keywords:
        _log("⚠️ 没有启用的关键词")
        return []

    _log(f"📋 共 {len(keywords)} 个启用的关键词")
    session = _build_session()
    results = []
    for kw in keywords:
        try:
            r = scrape_keyword(kw, session=session)
            results.append(r)
        except Exception as e:
            _log(f"❌ 关键词 {kw.get('keyword')} 抓取异常: {e}")
            try:
                db.insert_run_log(
                    keyword_id=kw.get('id'), keyword_name=kw.get('keyword'),
                    start_at=datetime.now(), end_at=datetime.now(),
                    pages_scanned=0, items_found=0,
                    items_new=0, items_updated=0,
                    status='failed', error_msg=str(e),
                )
            except Exception:
                pass
            results.append({'keyword_id': kw.get('id'), 'keyword': kw.get('keyword'),
                            'status': 'failed', 'error': str(e)})
        time.sleep(random.uniform(*SCRAPER_PAGE_INTERVAL_RANGE))
    return results


# ========== CLI 入口 ==========

def main():
    parser = argparse.ArgumentParser(description=f'{APP_NAME} - 抓取脚本')
    parser.add_argument('--keyword', type=str, help='指定单个关键词（不存在会自动新增）')
    parser.add_argument('--keyword-id', type=int, help='指定关键词 ID')
    parser.add_argument('--once', action='store_true', help='跑一次')
    args = parser.parse_args()

    if args.keyword_id:
        row = db.get_keyword_by_id(args.keyword_id)
        if not row:
            print(f"❌ 关键词 id={args.keyword_id} 不存在")
            sys.exit(1)
        scrape_keyword(row)
    elif args.keyword:
        scrape_keyword(args.keyword)
    else:
        scrape_all_enabled()


if __name__ == '__main__':
    main()
