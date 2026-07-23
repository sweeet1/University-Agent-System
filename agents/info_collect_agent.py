"""信息收集 Agent — 从第三方竞赛平台爬取原始竞赛信息。

数据来源（按 PROJECT_SPEC_CN.md 规范）：
  - 网页 (saikr 等第三方平台 API)
  - 用户上传文件 (PDF / DOCX / TXT / Excel)
  - 本地知识库（待扩展）
"""

import os
import logging
from datetime import datetime
from typing import Any

import yaml

from .info_collect.storage import Storage
from .info_collect.crawler import Crawler
from .info_collect.file_parser import parse_files
from .info_collect.registry import SourceRegistry

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")


class InfoCollectAgent:
    """负责根据用户需求采集原始竞赛信息。

    严格遵循 PROJECT_SPEC_CN.md 规范：
    - run(input_data: dict) -> dict 是唯一外部调用入口
    - 输入/输出均使用统一 JSON 格式
    """

    def __init__(self, config: dict | str | None = None):
        """接收配置 dict 或 config.yaml 路径。"""
        if config is None:
            config = DEFAULT_CONFIG_PATH
        if isinstance(config, str):
            with open(config, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        self.config = config
        self._storage: Storage | None = None
        self._crawler: Crawler | None = None

    def _get_storage(self) -> Storage:
        if self._storage is None:
            self._storage = Storage.create(self.config)
        return self._storage

    def _get_crawler(self) -> Crawler:
        if self._crawler is None:
            self._crawler = Crawler(self.config, self._get_storage())
        return self._crawler

    @staticmethod
    def _build_raw_items(all_items: list[dict]) -> list[dict]:
        """Build standard-format raw_items from collected competition dicts."""
        return [
            {
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "source": it.get("source", ""),
                "raw_text": it.get("raw_text", ""),
                "publish_date": it.get("publish_date", ""),
                "collected_at": it.get("collected_at", ""),
                "description": it.get("description", ""),
                "organizer": it.get("organizer", ""),
                "organizer_list": it.get("organizer_list", []),
                "co_organizers": it.get("co_organizers", []),
                "supporters": it.get("supporters", []),
                "regist_start": it.get("regist_start", ""),
                "regist_end": it.get("regist_end", ""),
                "contest_start": it.get("contest_start", ""),
                "contest_end": it.get("contest_end", ""),
                "category": it.get("category", ""),
                "level": it.get("level", ""),
                "attachments": it.get("attachments", []),
                "file_type": it.get("file_type", ""),
                "file_name": it.get("file_name", ""),
            }
            for it in all_items
        ]

    def _search_storage(
        self, storage: Storage, keywords: list[str], limit: int
    ) -> list[dict]:
        """Query stored competition data with keyword expansion."""
        from .info_collect.crawler import Crawler

        expanded = Crawler._expand_keywords(keywords) if keywords else []
        if hasattr(storage, "search_by_keywords"):
            return storage.search_by_keywords(expanded, limit=limit)  # type: ignore[union-attr]
        return storage.search(expanded, limit=limit)

    # ---- 统一接口 ----

    def run(self, input_data: dict) -> dict:
        """唯一外部调用入口。"""
        task_id = input_data.get("task_id", "")
        try:
            self.validate_input(input_data)
            data, message, stats = self.process(input_data)

            return {
                "task_id": task_id,
                "agent_name": "info_collect_agent",
                "status": "success",
                "data": data,
                "message": message,
                "error": None,
                "next_action": "info_extraction",
                "metadata": {
                    "execution_time": datetime.now().isoformat(),
                    "stats": stats,
                },
            }

        except ValueError as e:
            is_need_input = "请提供" in str(e)
            return {
                "task_id": task_id,
                "agent_name": "info_collect_agent",
                "status": "need_input" if is_need_input else "failed",
                "data": {},
                "message": str(e),
                "error": None if is_need_input else {
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "suggestion": "请检查 input_data 中的 sources 和 keywords",
                },
                "next_action": "ask_user" if is_need_input else None,
                "metadata": {"execution_time": datetime.now().isoformat()},
            }

        except Exception as e:
            logger.exception("InfoCollectAgent 执行异常")
            return {
                "task_id": task_id,
                "agent_name": "info_collect_agent",
                "status": "failed",
                "data": {},
                "message": f"执行失败: {e}",
                "error": {
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "suggestion": "请稍后重试或联系管理员",
                },
                "next_action": None,
                "metadata": {"execution_time": datetime.now().isoformat()},
            }

    def validate_input(self, input_data: dict):
        """校验 input_data 字段是否合法。"""
        inner = input_data.get("input_data", {})
        if not inner:
            raise ValueError("input_data 不能为空")

        sources = inner.get("sources", [])
        if not sources:
            raise ValueError("请提供 sources 参数，例如 ['saikr'] 或 ['local_file']")

        web_sources = set(SourceRegistry.list_all())
        local_sources = {"local_file"}
        valid_sources = web_sources | local_sources

        has_web = False
        has_local = False
        for s in sources:
            if s not in valid_sources:
                raise ValueError(
                    f"不支持的数据源: '{s}'，目前支持: {', '.join(sorted(valid_sources))}"
                )
            if s in web_sources:
                has_web = True
            if s in local_sources:
                has_local = True

        if has_web:
            keywords = inner.get("keywords", [])
            if not keywords:
                raise ValueError("网页采集需要提供 keywords 参数，例如 ['数学建模']")
            max_results = inner.get("max_results", 10)
            if not isinstance(max_results, int) or max_results < 1 or max_results > 100:
                raise ValueError("max_results 必须在 1-100 之间")

        if has_local:
            file_paths = inner.get("file_paths", [])
            if not file_paths:
                raise ValueError("本地文件采集需要提供 file_paths 参数，例如 ['通知.pdf', '竞赛.docx']")
            for fp in file_paths:
                if not os.path.exists(fp):
                    raise ValueError(f"文件不存在: {fp}")

    def process(self, input_data: dict) -> tuple[dict, str, dict]:
        """核心业务逻辑：根据 sources 类型分发到网页爬虫或本地文件解析。"""
        inner = input_data.get("input_data", {})
        task_id = input_data.get("task_id", "unknown")
        sources = inner.get("sources", SourceRegistry.list_all())

        storage = self._get_storage()
        all_items = []
        all_stats: dict[str, Any] = {}

        web_sources = set(SourceRegistry.list_all())

        # 网页采集：先查存储，不够再爬
        web_srcs = [s for s in sources if s in web_sources]
        if web_srcs:
            keywords = inner.get("keywords", [])
            max_results = inner.get("max_results", 10)

            # 1. 先从本地/云端存储搜索已有数据
            cached = self._search_storage(storage, keywords, max_results)
            cache_hits = len(cached)
            if cache_hits >= max_results:
                all_items.extend(cached[:max_results])
                all_stats["web"] = {
                    "pages_crawled": 0, "items_found": cache_hits,
                    "items_new": 0, "items_updated": 0,
                    "cache_hits": cache_hits, "source": "storage",
                }
            else:
                all_items.extend(cached)
                remaining = max_results - cache_hits
                cached_urls = {it.get("url") for it in cached}

                crawler = self._get_crawler()
                log_id = storage.start_crawl_log(task_id, ",".join(web_srcs))
                try:
                    web_items, wstats = crawler.crawl(keywords, web_srcs, remaining, log_id)
                finally:
                    try:
                        crawler.close()
                    except Exception:
                        pass
                storage.update_crawl_log(
                    log_id,
                    pages_crawled=wstats.get("pages_crawled", 0),
                    items_found=wstats.get("items_found", 0),
                    items_new=wstats.get("items_new", 0),
                    items_updated=wstats.get("items_updated", 0),
                    status="completed",
                    finished_at=datetime.now().isoformat(),
                )

                new_items = [it for it in web_items if it.get("url") not in cached_urls]
                all_items.extend(new_items)
                wstats["cache_hits"] = cache_hits
                all_stats["web"] = wstats

        # 本地文件解析
        if "local_file" in sources:
            file_paths = inner.get("file_paths", [])
            log_id = storage.start_crawl_log(task_id, "local_file")
            fstats = {"files_found": len(file_paths), "files_parsed": 0, "files_failed": 0}
            try:
                file_items = parse_files(file_paths)
                for item in file_items:
                    storage.upsert_item(item)
                    all_items.append(item)
                fstats["files_parsed"] = len(file_items)
                fstats["files_failed"] = len(file_paths) - len(file_items)
            except RuntimeError as e:
                storage.update_crawl_log(
                    log_id,
                    items_found=len(file_paths),
                    items_new=0,
                    items_updated=0,
                    status="failed",
                    error_message=str(e),
                    finished_at=datetime.now().isoformat(),
                )
                raise
            storage.update_crawl_log(
                log_id,
                items_found=len(file_paths),
                items_new=fstats["files_parsed"],
                items_updated=0,
                status="completed",
                finished_at=datetime.now().isoformat(),
            )
            all_stats["local_file"] = fstats

        # 组装 raw_items（按规范 12.1 格式）
        collected = self._build_raw_items(all_items)

        data = {"raw_items": collected, "stats": all_stats}

        msg_parts = []
        if "web" in all_stats:
            ws = all_stats["web"]
            cache_str = (
                f"缓存命中 {ws.get('cache_hits', 0)} 条, "
                if ws.get("cache_hits")
                else ""
            )
            msg_parts.append(
                f"网页采集: {cache_str}"
                f"爬取 {ws.get('pages_crawled', 0)} 页, "
                f"匹配 {ws.get('items_found', 0)} 条, "
                f"新增 {ws.get('items_new', 0)} 条"
            )
        if "local_file" in all_stats:
            fs = all_stats["local_file"]
            msg_parts.append(
                f"文件解析: {fs['files_found']} 个文件, "
                f"成功 {fs['files_parsed']} 个"
            )
        message = "采集完成 | " + " | ".join(msg_parts) if msg_parts else "未执行任何采集"

        return data, message, all_stats
