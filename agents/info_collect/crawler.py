"""爬虫核心 — API 优先，Playwright 作为降级方案。"""

import random
import logging
import time
from typing import Optional

from .api_client import SaikrAPIClient
from .parsers.saikr import SaikrParser
from .storage import Storage
from .dedup import DedupManager

logger = logging.getLogger(__name__)


class Crawler:
    """编排数据采集流程。MVP 使用 API 直连，避免反爬问题。"""

    def __init__(self, config: dict, storage: Storage):
        cfg = config.get("info_collect", {})
        self.delay_min = cfg.get("request_delay_min", 1)
        self.delay_max = cfg.get("request_delay_max", 3)
        self.max_pages = cfg.get("max_pages", 10)
        self.storage = storage
        self.dedup = DedupManager(storage)
        self._api: Optional[SaikrAPIClient] = None

    def _get_api(self) -> SaikrAPIClient:
        if self._api is None:
            self._api = SaikrAPIClient()
        return self._api

    def close(self):
        if self._api:
            self._api.close()
            self._api = None

    def _random_delay(self):
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    @staticmethod
    def _fetch_detail(api, parser, item: dict, slug: str, max_retries: int = 2):
        """获取单条竞赛详情，带重试和回退。"""
        for attempt in range(max_retries + 1):
            try:
                # 详情请求间隔比列表更长，3-6 秒随机
                time.sleep(random.uniform(3, 6))
                detail = api.get_contest_detail(slug)
                detail_fields = parser.parse_detail(detail)
                parser.merge_detail(item, detail_fields)
                return
            except Exception as e:
                if attempt < max_retries:
                    wait = (attempt + 1) * 5
                    logger.debug(
                        "详情获取重试 [%s] (%d/%d): %s",
                        item["title"][:30], attempt + 1, max_retries, e,
                    )
                    time.sleep(wait)
                else:
                    logger.warning("获取详情失败 [%s]: %s", item["title"][:30], e)

    @staticmethod
    def _match(item: dict, keywords: list[str]) -> bool:
        """检查竞赛标题是否包含任一关键词（不区分大小写）。"""
        title = (item.get("contest_name") or item.get("title") or "").lower()
        return any(kw.lower() in title for kw in keywords)

    def crawl(
        self,
        keywords: list[str],
        sources: list[str],
        max_results: int,
        log_id: int,
    ) -> tuple[list[dict], dict]:
        """执行数据采集：API 拉取全量 → 本地按关键词匹配过滤。"""
        all_items = []
        seen_urls = set()  # 同次爬取去重
        stats = {"pages_crawled": 0, "items_found": 0, "items_new": 0, "items_updated": 0}

        def _add(parsed: dict):
            nonlocal all_items, seen_urls
            if parsed["url"] in seen_urls:
                return False
            seen_urls.add(parsed["url"])
            all_items.append(parsed)
            return True

        for source in sources:
            if source != "saikr":
                logger.warning("目前仅支持 saikr 数据源，跳过: %s", source)
                continue

            api = self._get_api()
            parser = SaikrParser({})

            # 获取分类配置
            try:
                config_data = _retry(api.get_config, "分类配置")
                parser.set_class_map(config_data.get("classData", []))
            except Exception as e:
                logger.warning("获取分类配置失败: %s", e)

            # 首页推荐
            try:
                featured = _retry(lambda: api.get_featured(), "首页推荐")
                for item in featured:
                    if len(all_items) >= max_results:
                        break
                    if not self._match(item, keywords):
                        continue
                    stats["items_found"] += 1
                    parsed = parser.parse_featured_item(item)
                    _add(parsed)
            except Exception as e:
                logger.warning("获取首页推荐失败: %s", e)

            # 分页列表（API 不支持关键词过滤，在本地按标题匹配）
            page = 1
            while len(all_items) < max_results and page <= self.max_pages:
                try:
                    data = _retry(lambda: api.get_contests(page=page, limit=20), f"列表分页(p{page})")
                except Exception as e:
                    logger.error("API 请求失败 (page=%d): %s", page, e)
                    break

                items = data.get("list", [])
                stats["pages_crawled"] += 1

                if not items:
                    break

                for item in items:
                    if len(all_items) >= max_results:
                        break
                    if not self._match(item, keywords):
                        continue
                    stats["items_found"] += 1
                    parsed = parser.parse_contest_item(item)
                    _add(parsed)

                page += 1
                if page <= self.max_pages:
                    self._random_delay()

        # 获取每条匹配竞赛的详情，带重试和较长间隔防止被限流
        for item in all_items:
            slug = _extract_slug(item["url"])
            if not slug:
                continue
            self._fetch_detail(api, parser, item, slug)

        # 详情获取完毕后统一入库
        for item in all_items:
            op = self.storage.upsert_item(item)
            if op == "new":
                stats["items_new"] += 1
            else:
                stats["items_updated"] += 1

        return all_items, stats


def _retry(fn, label: str = "", max_retries: int = 2):
    """通用重试，带指数退避。"""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt < max_retries:
                wait = (attempt + 1) * 3
                logger.debug("%s 重试 (%d/%d): %s", label, attempt + 1, max_retries, e)
                time.sleep(wait)
            else:
                raise


def _extract_slug(url: str) -> str:
    """从竞赛 URL 中提取 API 用的 contest_url 参数。

    https://www.saikr.com/vse/58394  → 58394
    https://new.saikr.com/vse/TFB2026 → TFB2026
    https://www.saikr.com/vse/Bett-Grammar-Fourth → Bett-Grammar-Fourth
    """
    if "/vse/" in url:
        slug = url.split("/vse/")[-1]
        slug = slug.split("?")[0]  # 去掉 query string
        return slug
    return ""
