"""JSON 文件存储 — 原始数据保存到 data/raw/，简单可移植。"""

import json
import os
import threading
from datetime import datetime
from typing import Optional


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

    def get_all_items(self, source: Optional[str] = None) -> list[dict]:
        items = self._read_json(self.items_file)
        if source:
            items = [it for it in items if it.get("source") == source]
        return sorted(items, key=lambda x: x.get("collected_at", ""), reverse=True)
