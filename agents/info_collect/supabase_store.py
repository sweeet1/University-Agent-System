"""基于 Supabase 的竞赛数据存储，支持全文搜索。"""

import logging
import os
import re
import threading
from datetime import datetime
from typing import Optional

from supabase import create_client, Client

logger = logging.getLogger(__name__)

# raw_item 字段到 SQL 列的映射
FIELDS = [
    "title", "url", "source", "publish_date", "description",
    "organizer", "organizer_list", "co_organizers", "supporters",
    "regist_start", "regist_end", "contest_start", "contest_end",
    "category", "level", "attachments", "raw_text",
]

_COMPETITIONS_DDL = """\
CREATE TABLE IF NOT EXISTS competitions (
    id            BIGSERIAL PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT '',
    url           TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT '',
    publish_date  TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    organizer     TEXT NOT NULL DEFAULT '',
    organizer_list JSONB NOT NULL DEFAULT '[]'::jsonb,
    co_organizers  JSONB NOT NULL DEFAULT '[]'::jsonb,
    supporters     JSONB NOT NULL DEFAULT '[]'::jsonb,
    regist_start  TEXT NOT NULL DEFAULT '',
    regist_end    TEXT NOT NULL DEFAULT '',
    contest_start TEXT NOT NULL DEFAULT '',
    contest_end   TEXT NOT NULL DEFAULT '',
    category      TEXT NOT NULL DEFAULT '',
    level         TEXT NOT NULL DEFAULT '',
    attachments   JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_text      TEXT NOT NULL DEFAULT '',
    collected_at  TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL DEFAULT '',
    UNIQUE (url, source)
);"""

_CRAWL_LOGS_DDL = """\
CREATE TABLE IF NOT EXISTS crawl_logs (
    id            BIGSERIAL PRIMARY KEY,
    task_id       TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT '',
    pages_crawled INTEGER NOT NULL DEFAULT 0,
    items_found   INTEGER NOT NULL DEFAULT 0,
    items_new     INTEGER NOT NULL DEFAULT 0,
    items_updated INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    started_at    TEXT NOT NULL DEFAULT '',
    finished_at   TEXT
);"""


def _extract_project_ref(supabase_url: str) -> str | None:
    """Extract the Supabase project reference from a dashboard URL."""
    m = re.search(r"https?://([^.]+)\.supabase\.co", supabase_url)
    return m.group(1) if m else None


def _build_pg_dsn(supabase_url: str, password: str) -> str:
    """Build a direct PostgreSQL connection DSN (bypasses PgBouncer for DDL)."""
    ref = _extract_project_ref(supabase_url)
    if not ref:
        raise ValueError(f"Cannot extract project ref from SUPABASE_URL: {supabase_url}")
    return f"postgresql://postgres.{ref}:{password}@db.{ref}.supabase.co:5432/postgres"


class SupabaseStore:
    """基于 Supabase PostgreSQL 的存储后端。

    接口与 Storage 对齐：upsert_item / exists / get_all_items / crawl_log。

    额外提供 search() 方法供下游 RAG agent 使用。
    """

    def __init__(self, url: str, key: str):
        self.client: Client = create_client(url, key)
        self._lock = threading.Lock()
        self._ensure_tables(url)

    def _ensure_tables(self, supabase_url: str):
        """Auto-create required tables on first run via direct PostgreSQL connection.

        If SUPABASE_DB_PASSWORD is set in .env, tables are created automatically
        via a direct connection to the underlying PostgreSQL database (bypassing
        PgBouncer so DDL is supported).  Otherwise a clear message with the DDL
        is logged so the user can run it manually.
        """
        try:
            self.client.table("competitions").select("id", count="exact").limit(1).execute()
            return  # tables already exist
        except Exception:
            pass  # tables missing — try to create them

        password = os.getenv("SUPABASE_DB_PASSWORD", "").strip()
        if not password or password == "your_database_password_here":
            logger.warning(
                "competitions 表不存在。设置 SUPABASE_DB_PASSWORD 可自动建表，"
                "或手动在 Supabase SQL Editor 中执行：\n%s\n%s",
                _COMPETITIONS_DDL, _CRAWL_LOGS_DDL,
            )
            return

        try:
            import psycopg2
            dsn = _build_pg_dsn(supabase_url, password)
            conn = psycopg2.connect(dsn)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(_COMPETITIONS_DDL)
                cur.execute(_CRAWL_LOGS_DDL)
            conn.close()
            logger.info("Supabase 表已自动创建：competitions, crawl_logs")
        except Exception as exc:
            logger.warning(
                "自动建表失败 (%s)。请在 Supabase SQL Editor 中执行：\n%s\n%s",
                exc, _COMPETITIONS_DDL, _CRAWL_LOGS_DDL,
            )

    # ---- 竞赛数据 CRUD ----

    def exists(self, url: str, source: str) -> bool:
        result = (
            self.client.table("competitions")
            .select("id", count="exact")
            .eq("url", url)
            .eq("source", source)
            .execute()
        )
        return result.count > 0

    def upsert_item(self, item: dict) -> str:
        """插入或更新一条竞赛记录。去重键 = url + source。返回 'new' | 'updated'。"""
        is_new = not self.exists(item["url"], item["source"])

        if is_new:
            self._insert(item)
            return "new"
        else:
            self._update(item)
            return "updated"

    def _insert(self, item: dict):
        row = self._to_row(item)
        row["collected_at"] = datetime.now().isoformat()
        row["updated_at"] = row["collected_at"]

        resp = self.client.table("competitions").insert(row).execute()
        if resp.data:
            logger.info("Supabase 插入成功: %s", item.get("title", "")[:40])

    def _update(self, item: dict):
        row = self._to_row(item)
        row["updated_at"] = datetime.now().isoformat()

        resp = (
            self.client.table("competitions")
            .update(row)
            .eq("url", item["url"])
            .eq("source", item["source"])
            .execute()
        )
        if resp.data:
            logger.info("Supabase 更新成功: %s", item.get("title", "")[:40])

    def get_all_items(self, source: Optional[str] = None) -> list[dict]:
        """返回所有竞赛记录，可按来源过滤。"""
        query = self.client.table("competitions").select("*").order("collected_at", desc=True)
        if source:
            query = query.eq("source", source)
        result = query.execute()
        return result.data if result.data else []

    # ---- 爬取日志 ----

    def start_crawl_log(self, task_id: str, source: str) -> int:
        resp = (
            self.client.table("crawl_logs")
            .insert({
                "task_id": task_id,
                "source": source,
                "status": "running",
                "started_at": datetime.now().isoformat(),
            })
            .execute()
        )
        log_id = resp.data[0]["id"] if resp.data else 0
        return log_id

    def update_crawl_log(self, log_id: int, **kwargs):
        if "finished_at" not in kwargs:
            kwargs["finished_at"] = datetime.now().isoformat()
        (
            self.client.table("crawl_logs")
            .update(kwargs)
            .eq("id", log_id)
            .execute()
        )

    # ---- RAG 全文搜索 ----

    def search(
        self,
        query: str,
        limit: int = 20,
        category: Optional[str] = None,
        source: Optional[str] = None,
        regist_end_after: Optional[str] = None,
    ) -> list[dict]:
        """全文搜索竞赛。

        Args:
            query: 搜索词，如 "大学生数学竞赛"
            limit: 返回条数上限
            category: 按分类过滤
            source: 按来源过滤
            regist_end_after: 截止日期之后，如 "2026-08-01"
        """
        # 用 ilike 实现模糊搜索（PostgreSQL 原生，中文可用）
        q = (
            self.client.table("competitions")
            .select("*")
            .ilike("title", f"%{query}%")
            .order("collected_at", desc=True)
            .limit(limit)
        )

        if category:
            q = q.eq("category", category)
        if source:
            q = q.eq("source", source)
        if regist_end_after:
            q = q.gte("regist_end", regist_end_after)

        result = q.execute()
        return result.data if result.data else []

    def search_multi(
        self,
        query: str,
        limit: int = 20,
        **filters,
    ) -> list[dict]:
        """多字段模糊搜索（title + description + organizer）。"""
        q = (
            self.client.table("competitions")
            .select("*")
            .ilike("title", f"%{query}%")
            .order("collected_at", desc=True)
            .limit(limit)
        )
        for k, v in filters.items():
            if v:
                q = q.eq(k, v)
        result = q.execute()
        return result.data if result.data else []

    def search_by_keywords(self, keywords: list[str], limit: int = 20) -> list[dict]:
        """Search competitions by multiple keywords across title + description."""
        if not keywords:
            return []
        or_parts = []
        for kw in keywords:
            escaped = kw.replace("%", r"\%").replace("_", r"\_")
            or_parts.append(f"title.ilike.%{escaped}%")
            or_parts.append(f"description.ilike.%{escaped}%")
        or_filter = ",".join(or_parts)
        try:
            q = (
                self.client.table("competitions")
                .select("*")
                .or_(or_filter)
                .order("collected_at", desc=True)
                .limit(limit)
            )
            result = q.execute()
            return result.data if result.data else []
        except Exception:
            logger.warning("Supabase search_by_keywords failed, falling back.", exc_info=True)
            return []

    # ---- 实用方法 ----

    def get_categories(self) -> list[str]:
        result = (
            self.client.table("competitions")
            .select("category", count="exact")
            .not_.is_("category", "null")
            .neq("category", "")
            .execute()
        )
        cats = set()
        for row in (result.data or []):
            cat = row.get("category", "").strip()
            if cat:
                cats.add(cat)
        return sorted(cats)

    def count(self, source: Optional[str] = None) -> int:
        q = self.client.table("competitions").select("id", count="exact")
        if source:
            q = q.eq("source", source)
        result = q.execute()
        # count 在 result.count 中
        if result.count is not None:
            return result.count
        return len(result.data) if result.data else 0

    # ---- 内部 ----

    @staticmethod
    def _to_row(item: dict) -> dict:
        row = {}
        for f in FIELDS:
            val = item.get(f)
            if val is None:
                val = "" if f not in ("attachments", "organizer_list", "co_organizers", "supporters", "raw_text") else []
            row[f] = val
        return row
