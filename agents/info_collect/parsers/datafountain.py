"""DataFountain 数据解析器 — 解析 JSON API 响应。

API 格式:
  列表: {"cmpt": {"competitions": [{id, title, startTime, endTime, ...}, ...]}}
  详情: {"id": ..., "title": ..., "cmptDescription": ..., "reward": ..., ...}
"""

import json
from datetime import datetime
from bs4 import BeautifulSoup
from .base import BaseParser

DETAIL_BASE = "https://www.datafountain.cn"


class DatafountainParser(BaseParser):
    """解析 DataFountain 竞赛数据。"""

    def __init__(self, config: dict):
        super().__init__(config)

    def parse_list(self, data) -> list[dict]:
        """解析 API 返回的竞赛列表 JSON。"""
        if isinstance(data, dict):
            return self._parse_api_list(data)
        if isinstance(data, str) and data.strip().startswith("{"):
            return self._parse_api_list(json.loads(data))
        return self._parse_html_list(data) if isinstance(data, str) else []

    def _parse_api_list(self, data: dict) -> list[dict]:
        """解析 /api/competitions 返回的 JSON。"""
        competitions = data.get("cmpt", {}).get("competitions", [])
        return [self._parse_competition_item(c) for c in competitions]

    def _parse_competition_item(self, c: dict) -> dict:
        cid = c.get("id", "")
        return {
            "title": c.get("title", ""),
            "url": f"{DETAIL_BASE}/competitions/{cid}",
            "source": "datafountain",
            "raw_text": json.dumps(c, ensure_ascii=False),
            "publish_date": "",
            "collected_at": datetime.now().isoformat(),
            "description": c.get("subTitle", "") or "",
            "organizer": self._get_organizers(c),
            "regist_start": _fmt_iso(c.get("startTime")),
            "regist_end": _fmt_iso(c.get("endTime")),
            "contest_start": _fmt_iso(c.get("startTime")),
            "contest_end": _fmt_iso(c.get("endTime")),
            "category": ", ".join(c.get("tags", [])) if c.get("tags") else "",
            "level": c.get("typeLabel", ""),
            "attachments": [],
        }

    def parse_detail(self, data) -> dict:
        """解析竞赛详情 JSON。"""
        if isinstance(data, dict):
            return self._parse_api_detail(data)
        if isinstance(data, str):
            if data.strip().startswith("{"):
                return self._parse_api_detail(json.loads(data))
            return self._parse_html_detail(data)
        return {}

    def _parse_api_detail(self, detail: dict) -> dict:
        desc_html = detail.get("cmptDescription") or ""
        desc = _html_to_text(desc_html) if isinstance(desc_html, str) else ""

        return {
            "description": desc,
            "organizer": "",
            "regist_start": _fmt_iso(detail.get("startTime")),
            "regist_end": _fmt_iso(detail.get("endTime")),
            "contest_start": _fmt_iso(detail.get("startTime")),
            "contest_end": _fmt_iso(detail.get("endTime")),
            "category": "",
            "level": "",
            "attachments": [],
            "reward": detail.get("reward") or detail.get("totalBonus", ""),
            "raw_detail": json.dumps(detail, ensure_ascii=False),
        }

    def _parse_html_list(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if not href.startswith("/competitions/") or href == "/competitions":
                continue
            title = a_tag.get_text(strip=True)
            if not title:
                continue
            results.append({
                "title": title,
                "url": f"{DETAIL_BASE}{href}" if href.startswith("/") else href,
                "source": "datafountain",
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

    @staticmethod
    def _get_organizers(c: dict) -> str:
        """从 organizers/teams/users 字段提取主办方。"""
        orgs = c.get("organizers", [])
        if orgs and isinstance(orgs, list):
            if isinstance(orgs[0], dict):
                return ", ".join(o.get("name", "") for o in orgs if o.get("name"))
            return ", ".join(str(o) for o in orgs)
        return ""


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(separator="\n", strip=True)


def _fmt_iso(val) -> str:
    """格式化 ISO 时间字符串为日期。"""
    if not val:
        return ""
    s = str(val)
    # "2026-04-06T16:00:00.000Z" → "2026-04-06"
    if "T" in s:
        return s.split("T")[0]
    return s[:10] if len(s) >= 10 else s


# ---- 自注册 ----
from ..registry import SourceRegistry  # noqa: E402
from ..clients.datafountain import DatafountainClient  # noqa: E402

SourceRegistry.register("datafountain", DatafountainClient, DatafountainParser)
