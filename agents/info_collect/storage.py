"""JSON 文件存储 — 原始数据保存到 data/raw/，简单可移植。"""

import json
import os
import re
import threading
from datetime import datetime
from typing import Optional

import logging

# 自动加载 .env 文件（确保 SUPABASE_URL 等环境变量可用）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)


class Storage:
    """基于 JSON 文件的竞赛数据存储，无需数据库，可直接用编辑器打开。"""

    def __init__(self, raw_data_path: str):
        os.makedirs(raw_data_path, exist_ok=True)
        self.items_file = os.path.join(raw_data_path, "competitions.json")
        self.logs_file = os.path.join(raw_data_path, "crawl_logs.json")
        self._lock = threading.Lock()
        self._init_files()

    def _init_files(self):
        for path in [self.items_file, self.logs_file]:
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump([], f, ensure_ascii=False)

    def _read_json(self, path: str) -> list:
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, path: str, data: list):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def exists(self, url: str, source: str) -> bool:
        items = self._read_json(self.items_file)
        return any(it.get("url") == url and it.get("source") == source for it in items)

    def upsert_item(self, item: dict) -> str:
        """插入或更新一条竞赛记录。返回 'new' | 'updated'。"""
        with self._lock:
            items = self._read_json(self.items_file)
            for i, existing in enumerate(items):
                if existing.get("url") == item["url"] and existing.get("source") == item["source"]:
                    existing.update(item)
                    existing["collected_at"] = datetime.now().isoformat()
                    items[i] = existing
                    self._write_json(self.items_file, items)
                    return "updated"

            item["collected_at"] = datetime.now().isoformat()
            items.append(item)
            self._write_json(self.items_file, items)
            return "new"

    def start_crawl_log(self, task_id: str, source: str) -> int:
        logs = self._read_json(self.logs_file)
        log_id = len(logs) + 1
        logs.append({
            "id": log_id,
            "task_id": task_id,
            "source": source,
            "pages_crawled": 0,
            "items_found": 0,
            "items_new": 0,
            "items_updated": 0,
            "status": "running",
            "error_message": None,
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
        })
        self._write_json(self.logs_file, logs)
        return log_id

    def update_crawl_log(self, log_id: int, **kwargs):
        with self._lock:
            logs = self._read_json(self.logs_file)
            for log in logs:
                if log["id"] == log_id:
                    log.update(kwargs)
                    break
            self._write_json(self.logs_file, logs)

    def search(self, keywords: list[str], limit: int = 20) -> list[dict]:
        """Search stored competitions by keywords, matching title/description/organizer.

        Returns items sorted by collected_at descending, up to *limit*.
        """
        if not keywords:
            return []
        items = self._read_json(self.items_file)
        matched = []
        kw_lower = [k.lower() for k in keywords]
        for item in items:
            text = " ".join([
                str(item.get("title", "")),
                str(item.get("description", "")),
                str(item.get("organizer", "")),
            ]).lower()
            if any(kw in text for kw in kw_lower):
                matched.append(item)
        matched.sort(key=lambda x: x.get("collected_at", ""), reverse=True)
        return matched[:limit]

    def get_all_items(self, source: Optional[str] = None) -> list[dict]:
        items = self._read_json(self.items_file)
        if source:
            items = [it for it in items if it.get("source") == source]
        return sorted(items, key=lambda x: x.get("collected_at", ""), reverse=True)

    # ---- 工厂方法 ----

    @staticmethod
    def _resolve_env(value: str) -> str:
        """解析配置值中的 ${VAR} 环境变量引用。"""
        import re
        if not isinstance(value, str):
            return value
        def _replace(m):
            var_name = m.group(1)
            return os.getenv(var_name, "")
        return re.sub(r"\$\{(\w+)\}", _replace, value)

    @staticmethod
    def create(config: dict):
        """根据配置选择后端：json（本地文件）或 supabase（云端）。

        优先级: 传入 config > 环境变量 SUPABASE_STORE > json
        """
        storage_cfg = config.get("storage", {})
        backend = (
            storage_cfg.get("backend")
            or os.getenv("SUPABASE_STORE", "")
            or "json"
        )

        if backend == "supabase":
            try:
                from .supabase_store import SupabaseStore
            except ImportError:
                raise ImportError(
                    "请安装 supabase 库: pip install supabase"
                )

            # 解析 config 中的 ${VAR} 引用，fallback 到环境变量
            url = Storage._resolve_env(
                storage_cfg.get("supabase_url", "")
            ) or os.getenv("SUPABASE_URL", "")
            key = Storage._resolve_env(
                storage_cfg.get("supabase_key", "")
            ) or os.getenv("SUPABASE_ANON_KEY", "")

            if not url or not key:
                logger.warning(
                    "Supabase 配置不完整，回退到 JSON 存储。"
                    "请设置 SUPABASE_URL 和 SUPABASE_ANON_KEY 环境变量。"
                )
                return Storage._json_fallback(config)

            logger.info("使用 Supabase 云存储: %s", url[:40])
            return SupabaseStore(url=url, key=key)

        # 默认 JSON 存储
        return Storage._json_fallback(config)

    @staticmethod
    def _json_fallback(config: dict) -> "Storage":
        raw_path = config.get("storage", {}).get("raw_data_path", "./data/raw")
        if raw_path.startswith("./"):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            raw_path = os.path.join(project_root, raw_path[2:])
        logger.info("使用本地 JSON 存储: %s", raw_path)
        return Storage(raw_path)
