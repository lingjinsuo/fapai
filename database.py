#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================
法拍监控系统 - 数据库操作模块
所有 fp_* 表的 CRUD 都集中在此
============================================
"""

import json
from datetime import datetime, date
from decimal import Decimal

import pymysql
from pymysql.cursors import DictCursor

from config import DB_CONFIG, DONE_STATUSES


# ========== 数据库连接 ==========

def get_connection():
    """获取数据库连接"""
    return pymysql.connect(**DB_CONFIG)


# ========== 关键词操作 ==========

def get_all_keywords(include_deleted=False):
    """获取所有关键词"""
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            if include_deleted:
                sql = "SELECT * FROM fp_keywords ORDER BY id DESC"
            else:
                sql = "SELECT * FROM fp_keywords WHERE is_deleted = 0 ORDER BY id DESC"
            cursor.execute(sql)
            return cursor.fetchall()
    finally:
        conn.close()


def get_enabled_keywords():
    """获取所有启用的关键词"""
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            sql = "SELECT * FROM fp_keywords WHERE enabled = 1 AND is_deleted = 0 ORDER BY id"
            cursor.execute(sql)
            return cursor.fetchall()
    finally:
        conn.close()


def get_keyword_by_id(keyword_id):
    """根据 ID 获取关键词"""
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            sql = "SELECT * FROM fp_keywords WHERE id = %s AND is_deleted = 0"
            cursor.execute(sql, (keyword_id,))
            return cursor.fetchone()
    finally:
        conn.close()


def add_keyword(keyword, remark=None, enabled=1):
    """新增关键词（已存在则返回现有 ID）"""
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            cursor.execute(
                "SELECT id FROM fp_keywords WHERE keyword = %s AND is_deleted = 0",
                (keyword,),
            )
            row = cursor.fetchone()
            if row:
                return row['id']
            cursor.execute(
                "INSERT INTO fp_keywords (keyword, remark, enabled) VALUES (%s, %s, %s)",
                (keyword, remark, enabled),
            )
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()


def update_keyword(keyword_id, keyword=None, enabled=None, remark=None):
    """更新关键词"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            fields, params = [], []
            if keyword is not None:
                fields.append("keyword = %s")
                params.append(keyword)
            if enabled is not None:
                fields.append("enabled = %s")
                params.append(enabled)
            if remark is not None:
                fields.append("remark = %s")
                params.append(remark)
            if not fields:
                return False
            params.append(keyword_id)
            sql = f"UPDATE fp_keywords SET {', '.join(fields)} WHERE id = %s"
            cursor.execute(sql, params)
            conn.commit()
            return cursor.rowcount > 0
    finally:
        conn.close()


def delete_keyword(keyword_id):
    """逻辑删除关键词"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE fp_keywords SET is_deleted = 1, updated_at = NOW() WHERE id = %s",
                (keyword_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
    finally:
        conn.close()


def update_keyword_run_status(keyword_id, total, status, error=None):
    """更新关键词最近一次运行信息"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE fp_keywords
                   SET last_run_at = NOW(),
                       last_total = %s,
                       last_status = %s,
                       last_error = %s,
                       updated_at = NOW()
                   WHERE id = %s""",
                (total, status, (error or '')[:1000], keyword_id),
            )
            conn.commit()
    finally:
        conn.close()


# ========== 通用辅助 ==========

def _decode_price(v):
    """把 Decimal/数字统一转 float；None 维持 None"""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ms_to_dt(ms):
    """毫秒时间戳 -> datetime"""
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000)
    except (TypeError, ValueError, OSError):
        return None


def _normalize_url(url):
    """协议相对 URL //host/path -> https://host/path
    已经是 http/https 的保持不变；空值返回 None。
    """
    if not url:
        return None
    s = str(url).strip()
    if not s:
        return None
    if s.startswith('//'):
        return 'https:' + s
    if s.startswith('http://') or s.startswith('https://'):
        return s
    # 裸路径，补 https://
    if s.startswith('/'):
        return 'https://sf.taobao.com' + s
    return 'https://' + s


# ========== 标的（fp_items）操作 ==========

def is_item_seen_and_done(sf_item_id):
    """核心判定：标的已存在且状态为「已结束」(done/closed)，则停止抓取。
    返回 True / False
    """
    if not sf_item_id:
        return False
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            placeholders = ','.join(['%s'] * len(DONE_STATUSES))
            sql = f"""SELECT 1 FROM fp_items
                       WHERE sf_item_id = %s
                         AND status IN ({placeholders})
                         AND is_deleted = 0 LIMIT 1"""
            cursor.execute(sql, (sf_item_id, *DONE_STATUSES))
            return cursor.fetchone() is not None
    finally:
        conn.close()


def is_item_seen(sf_item_id):
    """
    判定：标的在数据库中是否已存在（任意状态）
    用于"重复即停止"判断。
    返回 True / False
    """
    if not sf_item_id:
        return False
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            cursor.execute(
                "SELECT 1 FROM fp_items WHERE sf_item_id = %s AND is_deleted = 0 LIMIT 1",
                (sf_item_id,),
            )
            return cursor.fetchone() is not None
    finally:
        conn.close()


def upsert_fp_item(item, keyword_id=None):
    """
    标的 upsert：
    - 不存在 -> INSERT
    - 已存在 -> UPDATE  状态 / 价格 / 计数 / last_seen_at / url 等
    返回: (id, is_new)
    """
    sf_item_id = int(item.get('id')) if item.get('id') is not None else None
    if not sf_item_id:
        return None, False

    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            cursor.execute(
                "SELECT id FROM fp_items WHERE sf_item_id = %s AND is_deleted = 0",
                (sf_item_id,),
            )
            row = cursor.fetchone()
            now = datetime.now()

            fields = {
                'title': item.get('title'),
                'status': item.get('status'),
                'initial_price': _decode_price(item.get('initialPrice')),
                'current_price': _decode_price(item.get('currentPrice')),
                'consult_price': _decode_price(item.get('consultPrice')),
                'market_price': _decode_price(item.get('marketPrice')),
                'apply_count': int(item.get('applyCount') or 0),
                'bid_count': int(item.get('bidCount') or 0),
                'viewer_count': int(item.get('viewerCount') or 0),
                'delay_count': int(item.get('delayCount') or 0),
                'start_at': _ms_to_dt(item.get('start')),
                'end_at': _ms_to_dt(item.get('end')),
                'support_loans': int(item.get('supportLoans') or 0),
                'sell_off': 1 if item.get('sellOff') else 0,
                'item_url': _normalize_url(item.get('itemUrl')),
                'pic_url': _normalize_url(item.get('picUrl')),
                'last_seen_at': now,
            }

            if row is None:
                insert_fields = list(fields.keys()) + ['sf_item_id', 'keyword_id', 'first_seen_at']
                placeholders = ','.join(['%s'] * len(insert_fields))
                sql = f"INSERT INTO fp_items ({','.join(insert_fields)}) VALUES ({placeholders})"
                values = [fields[k] for k in fields.keys()] + [sf_item_id, keyword_id, now]
                cursor.execute(sql, values)
                new_id = cursor.lastrowid
                conn.commit()
                return new_id, True
            else:
                sets = ', '.join([f"{k} = %s" for k in fields.keys()])
                sql = f"UPDATE fp_items SET {sets} WHERE id = %s"
                values = [fields[k] for k in fields.keys()] + [row['id']]
                cursor.execute(sql, values)
                conn.commit()
                return row['id'], False
    finally:
        conn.close()


def get_item_by_sf_id(sf_item_id):
    """根据 sf_item_id 获取标的详情"""
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM fp_items WHERE sf_item_id = %s AND is_deleted = 0",
                (sf_item_id,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def search_items(keyword=None, status=None, sf_item_id=None,
                 date_from=None, date_to=None, limit=500, offset=0):
    """标的搜索 / 列表"""
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            conds = ["is_deleted = 0"]
            params = []
            if keyword:
                conds.append("title LIKE %s")
                params.append(f"%{keyword}%")
            if status:
                conds.append("status = %s")
                params.append(status)
            if sf_item_id:
                conds.append("sf_item_id = %s")
                params.append(sf_item_id)
            if date_from:
                conds.append("DATE(end_at) >= %s")
                params.append(date_from)
            if date_to:
                conds.append("DATE(end_at) <= %s")
                params.append(date_to)
            where = ' AND '.join(conds)
            sql = f"""SELECT * FROM fp_items
                       WHERE {where}
                       ORDER BY end_at DESC, id DESC
                       LIMIT %s OFFSET %s"""
            cursor.execute(sql, (*params, limit, offset))
            return cursor.fetchall()
    finally:
        conn.close()


def get_items_with_keyword_count(keyword_filter=None):
    """按关键词聚合 - 标的数 + 最近运行状态"""
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            base_sql = """SELECT k.id AS keyword_id,
                                 k.keyword AS keyword,
                                 k.enabled,
                                 k.last_run_at,
                                 k.last_total,
                                 k.last_status,
                                 COUNT(i.id) AS item_count
                            FROM fp_keywords k
                       LEFT JOIN fp_items i ON i.keyword_id = k.id AND i.is_deleted = 0
                           WHERE k.is_deleted = 0 {extra}
                        GROUP BY k.id
                        ORDER BY k.id DESC"""
            if keyword_filter:
                cursor.execute(base_sql.format(extra="AND k.keyword LIKE %s"),
                               (f"%{keyword_filter}%",))
            else:
                cursor.execute(base_sql.format(extra=""))
            return cursor.fetchall()
    finally:
        conn.close()


def get_item_summary_stats():
    """首页汇总统计"""
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total, "
                "       SUM(status='doing') AS doing, "
                "       SUM(status='todo')  AS todo, "
                "       SUM(status IN ('done','closed')) AS done "
                "FROM fp_items WHERE is_deleted = 0"
            )
            item_stats = cursor.fetchone()
            cursor.execute(
                "SELECT COUNT(*) AS total, "
                "       SUM(enabled=1) AS enabled "
                "FROM fp_keywords WHERE is_deleted = 0"
            )
            kw_stats = cursor.fetchone()
            return {
                'total_items': int(item_stats['total'] or 0),
                'doing_items': int(item_stats['doing'] or 0),
                'todo_items': int(item_stats['todo'] or 0),
                'done_items': int(item_stats['done'] or 0),
                'total_keywords': int(kw_stats['total'] or 0),
                'enabled_keywords': int(kw_stats['enabled'] or 0),
            }
    finally:
        conn.close()


# ========== 标的快照（fp_item_history）操作 ==========

def upsert_item_history(sf_item_id, item_pk, item):
    """
    每天每个标的最多一条快照：以 (sf_item_id, snapshot_date) 唯一
    返回: True 新增 / False 更新 / None 跳过
    """
    if not sf_item_id or not item_pk:
        return None
    today = date.today()
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            cursor.execute(
                "SELECT id FROM fp_item_history WHERE sf_item_id = %s AND snapshot_date = %s",
                (sf_item_id, today),
            )
            row = cursor.fetchone()
            fields = {
                'status': item.get('status'),
                'current_price': _decode_price(item.get('currentPrice')),
                'apply_count': int(item.get('applyCount') or 0),
                'bid_count': int(item.get('bidCount') or 0),
                'viewer_count': int(item.get('viewerCount') or 0),
            }
            if row is None:
                insert_fields = list(fields.keys()) + ['sf_item_id', 'item_pk', 'snapshot_date']
                placeholders = ','.join(['%s'] * len(insert_fields))
                sql = f"INSERT INTO fp_item_history ({','.join(insert_fields)}) VALUES ({placeholders})"
                values = [fields[k] for k in fields.keys()] + [sf_item_id, item_pk, today]
                cursor.execute(sql, values)
                conn.commit()
                return True
            else:
                sets = ', '.join([f"{k} = %s" for k in fields.keys()])
                sql = f"UPDATE fp_item_history SET {sets}, snapshot_at = NOW() WHERE id = %s"
                values = [fields[k] for k in fields.keys()] + [row['id']]
                cursor.execute(sql, values)
                conn.commit()
                return False
    finally:
        conn.close()


def get_item_history(sf_item_id, limit=60):
    """获取标的的快照历史"""
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM fp_item_history WHERE sf_item_id = %s AND is_deleted = 0 "
                "ORDER BY snapshot_date DESC LIMIT %s",
                (sf_item_id, limit),
            )
            return cursor.fetchall()
    finally:
        conn.close()


# ========== 抓取运行日志（fp_run_logs） ==========

def insert_run_log(keyword_id, keyword_name, start_at, end_at,
                   pages_scanned, items_found, items_new, items_updated,
                   status, error_msg=None):
    """新增一条抓取运行日志"""
    duration = int((end_at - start_at).total_seconds()) if start_at and end_at else 0
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO fp_run_logs
                   (keyword_id, keyword_name, start_at, end_at, duration_sec,
                    pages_scanned, items_found, items_new, items_updated,
                    status, error_msg)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (keyword_id, keyword_name, start_at, end_at, duration,
                 pages_scanned, items_found, items_new, items_updated,
                 status, (error_msg or '')[:2000]),
            )
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()


def get_recent_run_logs(limit=50):
    """获取最近的抓取运行日志"""
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM fp_run_logs ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            return cursor.fetchall()
    finally:
        conn.close()
