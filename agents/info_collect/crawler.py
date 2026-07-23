"""爬虫核心 — 注册表驱动的多数据源采集。"""

import random
import logging
import time
from typing import Optional

from .registry import SourceRegistry, SourceSpec
from .storage import Storage
from .dedup import DedupManager

logger = logging.getLogger(__name__)


class Crawler:
    """编排数据采集流程。通过 SourceRegistry 动态加载各平台的 Client + Parser。"""

    def __init__(self, config: dict, storage: Storage):
        cfg = config.get("info_collect", {})
        self.delay_min = cfg.get("request_delay_min", 1)
        self.delay_max = cfg.get("request_delay_max", 3)
        self.max_pages = cfg.get("max_pages", 10)
        self.client_timeout = cfg.get("client_timeout", 10)
        self.source_configs = cfg.get("sources", {})
        self.storage = storage
        self.dedup = DedupManager(storage)
        self._closed = False

    def close(self):
        """Release any resources held by the crawler."""
        self._closed = True

    def _random_delay(self):
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    # 关键词 → 标题中可能出现的等价表述
    _KEYWORD_ALIASES: dict[str, list[str]] = {
        "人工智能": ["ai", "agent", "llm", "机器学习", "深度学习", "计算机视觉", "nlp", "自然语言处理"],
        "数据分析": ["数据挖掘", "大数据", "data"],
        "软件开发": ["编程", "coding", "hackathon", "黑客松", "程序设计", "hack"],
        "创新创业": ["创业", "创新", "startup", "商业"],
        "算法": ["算法赛", "algorithm", "程序", "acm"],
        "数学建模": ["数学", "建模", "math"],
        "机器人": ["robot", "ros", "无人", "自动化"],
        "电子设计": ["电子", "硬件", "嵌入式", "iot", "物联网", "stm32"],
        "自动化": ["控制", "pid", "plc"],
        "市场营销": ["营销", "商业策划", "策划"],
        "网络安全": ["安全", "ctf", "攻防", "security"],
    }

    @classmethod
    def _expand_keywords(cls, keywords: list[str]) -> list[str]:
        """Expand user keywords with known aliases for broader matching."""
        expanded = list(keywords)
        for kw in keywords:
            lower_kw = kw.lower()
            for base, aliases in cls._KEYWORD_ALIASES.items():
                if lower_kw == base.lower() or lower_kw in [a.lower() for a in aliases]:
                    expanded.extend(aliases)
                    if base.lower() not in [e.lower() for e in expanded]:
                        expanded.append(base)
        return expanded

    @classmethod
    def _match(cls, item: dict, keywords: list[str]) -> bool:
        """检查竞赛标题是否包含任一关键词（不区分大小写），含别名扩展。
        当 keywords 为空或包含 '*' 时，匹配所有条目。
        """
        if not keywords or "*" in keywords:
            return True
        title = (item.get("contest_name") or item.get("title") or "").lower()
        expanded = cls._expand_keywords(keywords)
        return any(kw.lower() in title for kw in expanded)

    def crawl(
        self,
        keywords: list[str],
        sources: list[str],
        max_results: int,
        log_id: int,
    ) -> tuple[list[dict], dict]:
        """执行数据采集：遍历 sources，为每个来源调用对应的 Client + Parser。"""
        all_items = []
        seen_urls = set()
        stats = {"pages_crawled": 0, "items_found": 0, "items_new": 0, "items_updated": 0, "available_titles": []}

        def _add(parsed: dict) -> bool:
            nonlocal all_items, seen_urls
            if parsed["url"] in seen_urls:
                return False
            seen_urls.add(parsed["url"])
            all_items.append(parsed)
            return True

        for source in sources:
            spec = SourceRegistry.get(source)
            if spec is None:
                logger.warning("未注册的数据源，跳过: %s", source)
                continue

            logger.info("开始采集数据源: %s", source)
            sc = self.source_configs.get(source, {})
            timeout = sc.get("timeout", self.client_timeout)
            max_pages = sc.get("max_pages", self.max_pages)
            client = spec.client_class(timeout=timeout)
            if hasattr(client, "set_search_keywords"):
                client.set_search_keywords(keywords)
            parser = spec.parser_class({})

            try:
                # 获取站点配置（如分类映射）
                try:
                    config_data = _retry(client.get_config, f"{source} 配置")
                    if config_data:
                        parser.configure(config_data)
                except Exception as e:
                    logger.warning("获取 %s 配置失败: %s", source, e)

                # 首页推荐
                try:
                    featured = _retry(lambda: client.get_featured(), f"{source} 首页推荐")
                    if featured:
                        parsed_list = parser.parse_featured_list(featured)
                        for item in parsed_list:
                            if len(all_items) >= max_results:
                                break
                            if not self._match(item, keywords):
                                continue
                            stats["items_found"] += 1
                            _add(item)
                except Exception as e:
                    logger.warning("获取 %s 首页推荐失败: %s", source, e)

                # 记录当前 source 匹配到的项（用于后续详情获取）
                source_matched: list[dict] = []

                # 分页列表
                page = 1
                all_parsed: list[dict] = []  # 所有解析到的条目（含未匹配的）
                while len(all_items) < max_results and page <= max_pages:
                    try:
                        data = _retry(
                            lambda p=page: client.get_contests(page=p, limit=20),
                            f"{source} 列表分页(p{page})",
                        )
                    except Exception as e:
                        logger.error("%s API 请求失败 (page=%d): %s", source, page, e)
                        break

                    # data 可能是 dict（JSON API）或 str（HTML），交给 parser 处理
                    parsed_list = parser.parse_list(data)
                    if not parsed_list:
                        break

                    all_parsed.extend(parsed_list)
                    stats["pages_crawled"] += 1

                    for item in parsed_list:
                        if len(all_items) >= max_results:
                            break
                        if not self._match(item, keywords):
                            continue
                        stats["items_found"] += 1
                        _add(item)
                        source_matched.append(item)

                    page += 1
                    if page <= max_pages:
                        self._random_delay()

                # 只对当前 source 匹配到的条目获取详情
                if source_matched:
                    for item in source_matched:
                        ident = _extract_ident(item["url"])
                        if not ident:
                            continue
                        _fetch_detail(client, parser, item, ident, source=source)
                elif stats["pages_crawled"] > 0:
                    # 分析未匹配原因
                    reason = _diagnose_no_match(all_parsed, keywords, source)

                    logger.warning(
                        "关键词 %s 在 %s 的 %d 页 / %d 条中未匹配到任何条目。%s",
                        keywords, source, stats["pages_crawled"], len(all_parsed), reason,
                    )

                    # 保存可用标题供调用方展示（全部，不止 10 条）
                    stats["available_titles"] = [it.get("title", "")[:60] for it in all_parsed]
                    stats["total_parsed"] = len(all_parsed)
                    logger.warning(
                        "%s 共解析 %d 条，前 10 条可用标题: %s",
                        source, len(all_parsed), stats["available_titles"][:10],
                    )

            finally:
                client.close()

        # 详情获取完毕后统一入库
        for item in all_items:
            op = self.storage.upsert_item(item)
            if op == "new":
                stats["items_new"] += 1
            else:
                stats["items_updated"] += 1

        return all_items, stats


def _diagnose_no_match(parsed_items: list[dict], keywords: list[str], source: str) -> str:
    """诊断未匹配原因：关键词不对、数据为空、或爬取失败。"""
    if not parsed_items:
        return f"网站 {source} 返回了空列表，可能是页面结构变化或反爬限制"

    titles = [it.get("contest_name") or it.get("title") or "" for it in parsed_items]
    titles = [t for t in titles if t]  # 去掉空标题

    if not titles:
        return f"网站 {source} 返回了数据但标题全为空，可能是解析器不匹配实际页面结构"

    # 检查关键词是否可能在标题中（部分匹配）
    kw_lower = [k.lower() for k in keywords]
    partial_hits = []
    for t in titles:
        for kw in kw_lower:
            if kw.lower() in t.lower():
                partial_hits.append(t[:50])
                break

    if partial_hits:
        # 有关键词部分匹配但未命中 → 可能是 match 逻辑的问题
        return (
            f"部分标题包含关键词子串但未命中: {partial_hits[:3]}。"
            f"可能是 _match 逻辑需要调整"
        )
    else:
        return f"关键词 {keywords} 与所有 {len(titles)} 条标题都不匹配"


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


def _fetch_detail(client, parser, item: dict, ident: str, max_retries: int = 2, source: str = ""):
    """获取单条竞赛详情，带重试。"""
    for attempt in range(max_retries + 1):
        try:
            # 请求间隔 1-2 秒（已在分页循环中有更长延迟）
            time.sleep(random.uniform(1, 3))
            detail = client.get_contest_detail(ident)
            detail_fields = parser.parse_detail(detail)
            parser.merge_detail(item, detail_fields)
            logger.info("详情获取成功 [%s]: %s", source, item["title"][:40])
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


def _extract_ident(url: str) -> str:
    """从竞赛 URL 中提取平台标识符，用于调用详情 API。

    支持的模式:
      https://www.saikr.com/vse/58394         → 58394
      https://www.52jingsai.com/article-23897-1.html → article-23897-1
      https://www.datafountain.cn/competitions/1169  → 1169
      https://tianchi.aliyun.com/competition/532495  → 532495
    """
    # saikr 特殊处理
    if "/vse/" in url:
        ident = url.split("/vse/")[-1]
        return ident.split("?")[0]

    # 通用策略：取最后一个路径段
    from urllib.parse import urlparse
    path = urlparse(url).path.rstrip("/")
    if path:
        ident = path.split("/")[-1]
        # 去掉文件扩展名 (.html, .htm, .aspx, 等)
        import re
        ident = re.sub(r"\.\w+$", "", ident)
        return ident
    return ""
