"""阿里天池数据解析器 — 从 SSR HTML 页面提取竞赛数据。"""

import re
import json
from datetime import datetime
from bs4 import BeautifulSoup
from .base import BaseParser

DETAIL_BASE = "https://tianchi.aliyun.com"


class TianchiParser(BaseParser):
    """解析阿里天池竞赛页面。"""

    def __init__(self, config: dict):
        super().__init__(config)

    def parse_list(self, data) -> list[dict]:
        """解析列表页 HTML。"""
        if isinstance(data, str) and not data.strip().startswith("{"):
            return self._parse_html_list(data)
        # JSON 格式（备用）
        if isinstance(data, dict):
            return self._parse_json_list(data)
        if isinstance(data, str):
            return self._parse_json_list(json.loads(data))
        return []

    def _parse_html_list(self, html: str) -> list[dict]:
        """从天池 SSR 页面提取竞赛列表。"""
        soup = BeautifulSoup(html, "lxml")
        results = []

        # 天池的竞赛卡片通常以 /competition/{id} 为链接
        seen = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            m = re.match(r"/competition/(\d+)", href)
            if not m:
                continue
            cid = m.group(1)
            if cid in seen:
                continue
            seen.add(cid)

            # 尝试找到标题文本
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 3:
                # 尝试从父级元素找标题
                parent = a_tag.find_parent(["div", "li", "section"])
                if parent:
                    title_el = parent.select_one(
                        ".title, .name, .race-name, .competition-name, h2, h3, h4, [class*=title]"
                    )
                    if title_el:
                        title = title_el.get_text(strip=True)
                if not title:
                    title = a_tag.get("title", "")

            if not title:
                continue

            results.append({
                "title": title,
                "url": f"{DETAIL_BASE}{href}",
                "source": "ali_tianchi",
                "raw_text": title,
                "publish_date": "",
                "collected_at": datetime.now().isoformat(),
                "description": "",
                "organizer": "阿里云天池",
                "regist_start": "",
                "regist_end": "",
                "contest_start": "",
                "contest_end": "",
                "category": "",
                "level": "",
                "attachments": [],
            })

        return results

    def _parse_json_list(self, data: dict) -> list[dict]:
        """兼容 JSON API 格式（备用）。"""
        items = (
            data.get("data", {}).get("list")
            or data.get("data", {}).get("content")
            or data.get("data")
            or data.get("list")
            or []
        )
        if isinstance(items, dict):
            items = items.get("list") or items.get("content") or []
        if not isinstance(items, list):
            return []

        return [self._parse_json_item(item) for item in items]

    def _parse_json_item(self, item: dict) -> dict:
        url = item.get("url") or item.get("competitionUrl") or item.get("detailUrl") or ""
        if url and not url.startswith("http"):
            url = DETAIL_BASE + url
        return {
            "title": item.get("title") or item.get("name") or item.get("competitionName") or "",
            "url": url,
            "source": "ali_tianchi",
            "raw_text": json.dumps(item, ensure_ascii=False),
            "publish_date": "",
            "collected_at": datetime.now().isoformat(),
            "description": item.get("description") or item.get("brief") or "",
            "organizer": item.get("organizer") or "阿里云天池",
            "regist_start": item.get("signUpStartTime") or item.get("registStartTime") or "",
            "regist_end": item.get("signUpEndTime") or item.get("registEndTime") or item.get("deadline") or "",
            "contest_start": item.get("startTime") or "",
            "contest_end": item.get("endTime") or "",
            "category": item.get("category") or "",
            "level": item.get("level") or "",
            "attachments": [],
        }

    def parse_detail(self, data) -> dict:
        """解析竞赛详情。"""
        if isinstance(data, dict):
            return self._parse_json_detail(data)
        if isinstance(data, str):
            if data.strip().startswith("{"):
                return self._parse_json_detail(json.loads(data))
            return self._parse_html_detail(data)
        return {}

    def _parse_json_detail(self, detail: dict) -> dict:
        content = detail.get("content") or detail.get("description") or detail.get("detailDesc") or ""
        return {
            "description": _html_to_text(content) if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
            "organizer": detail.get("organizer") or "阿里云天池",
            "regist_start": detail.get("signUpStartTime") or detail.get("registStartTime") or "",
            "regist_end": detail.get("signUpEndTime") or detail.get("registEndTime") or detail.get("deadline") or "",
            "contest_start": detail.get("startTime") or "",
            "contest_end": detail.get("endTime") or "",
            "category": detail.get("category") or "",
            "level": detail.get("level") or "",
            "attachments": detail.get("attachments") or [],
            "raw_detail": json.dumps(detail, ensure_ascii=False),
        }

    def _parse_html_detail(self, html: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
        body = soup.find("body") or soup
        return {
            "description": body.get_text(separator="\n", strip=True),
            "organizer": "阿里云天池",
            "regist_start": "",
            "regist_end": "",
            "contest_start": "",
            "contest_end": "",
            "category": "",
            "level": "",
            "attachments": [],
        }


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(separator="\n", strip=True)


# ---- 自注册 ----
from ..registry import SourceRegistry  # noqa: E402
from ..clients.tianchi import TianchiClient  # noqa: E402

SourceRegistry.register("ali_tianchi", TianchiClient, TianchiParser)
