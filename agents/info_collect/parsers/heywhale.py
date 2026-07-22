"""和鲸社区数据解析器 — 从 HTML 页面提取竞赛数据。"""

import json
from datetime import datetime
from bs4 import BeautifulSoup
from .base import BaseParser

DETAIL_BASE = "https://www.heywhale.com"


class HeywhaleParser(BaseParser):
    """解析和鲸社区竞赛数据。"""

    def __init__(self, config: dict):
        super().__init__(config)

    def parse_list(self, data) -> list[dict]:
        """解析列表数据。"""
        if isinstance(data, dict):
            return self._parse_json_list(data)
        if isinstance(data, str) and data.strip().startswith("{"):
            return self._parse_json_list(json.loads(data))
        return self._parse_html_list(data) if isinstance(data, str) else []

    def _parse_json_list(self, data: dict) -> list[dict]:
        items = (
            data.get("data", {}).get("list")
            or data.get("data", {}).get("results")
            or data.get("data")
            or data.get("list")
            or data.get("results")
            or []
        )
        if isinstance(items, dict):
            items = items.get("list") or items.get("results") or []
        if not isinstance(items, list):
            return []

        return [self._parse_json_item(item) for item in items]

    def _parse_json_item(self, item: dict) -> dict:
        url = item.get("url") or item.get("competition_url") or item.get("share_url") or ""
        if url and not url.startswith("http"):
            url = DETAIL_BASE + url
        return {
            "title": item.get("title") or item.get("name") or item.get("competition_name") or "",
            "url": url,
            "source": "heywhale",
            "raw_text": json.dumps(item, ensure_ascii=False),
            "publish_date": item.get("create_time") or item.get("publish_date") or "",
            "collected_at": datetime.now().isoformat(),
            "description": item.get("description") or item.get("brief") or "",
            "organizer": item.get("organizer") or item.get("organizer_name") or "",
            "regist_start": item.get("sign_up_start") or item.get("regist_start_time") or "",
            "regist_end": item.get("sign_up_end") or item.get("regist_end_time") or item.get("deadline") or "",
            "contest_start": item.get("start_time") or "",
            "contest_end": item.get("end_time") or "",
            "category": item.get("category") or item.get("tag") or "",
            "level": item.get("level") or "",
            "attachments": [],
        }

    def _parse_html_list(self, html: str) -> list[dict]:
        """从 HTML 页面提取竞赛链接。"""
        soup = BeautifulSoup(html, "lxml")
        results = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/competition/" not in href:
                continue
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            if not href.startswith("http"):
                href = DETAIL_BASE + href

            results.append({
                "title": title,
                "url": href,
                "source": "heywhale",
                "raw_text": title,
                "publish_date": "",
                "collected_at": datetime.now().isoformat(),
                "description": "",
                "organizer": "",
                "regist_start": "",
                "regist_end": "",
                "contest_start": "",
                "contest_end": "",
                "category": "",
                "level": "",
                "attachments": [],
            })
        return results

    def parse_detail(self, data) -> dict:
        """解析详情。"""
        if isinstance(data, dict):
            return self._parse_json_detail(data)
        if isinstance(data, str) and data.strip().startswith("{"):
            return self._parse_json_detail(json.loads(data))
        return self._parse_html_detail(data) if isinstance(data, str) else {}

    def _parse_json_detail(self, detail: dict) -> dict:
        content = detail.get("content") or detail.get("description") or ""
        return {
            "description": _html_to_text(content) if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
            "organizer": detail.get("organizer") or "",
            "regist_start": detail.get("sign_up_start") or detail.get("regist_start_time") or "",
            "regist_end": detail.get("sign_up_end") or detail.get("regist_end_time") or detail.get("deadline") or "",
            "contest_start": detail.get("start_time") or "",
            "contest_end": detail.get("end_time") or "",
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
            "organizer": "",
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
from ..clients.heywhale import HeywhaleClient  # noqa: E402

SourceRegistry.register("heywhale", HeywhaleClient, HeywhaleParser)
