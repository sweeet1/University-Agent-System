"""赛氪数据解析器 — 将 API JSON 响应转换为标准 raw_item 格式。"""

import json
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup
from .base import BaseParser

DETAIL_BASE = "https://www.saikr.com/"


class SaikrParser(BaseParser):
    """解析赛氪 API 返回的竞赛数据（列表 + 详情）。"""

    def __init__(self, config: dict):
        super().__init__(config)
        self._class_map: dict[str, str] = {}

    def configure(self, config_data):
        """接收分类配置，建立 class_id → 中文名 的映射。"""
        class_data = config_data.get("classData", [])
        for top in class_data:
            for son in top.get("sons", []):
                self._class_map[str(son.get("value", ""))] = son.get("label", "")

    def get_class_name(self, class_id: str) -> str:
        return self._class_map.get(str(class_id), class_id)

    # ---- 列表解析 ----

    def parse_list(self, data: dict) -> list[dict]:
        """解析 API 返回的列表 JSON，返回 raw_item 列表。"""
        items = data.get("list", [])
        return [self.parse_contest_item(item) for item in items]

    def parse_featured_list(self, items: list[dict]) -> list[dict]:
        """解析首页推荐数据，返回 raw_item 列表。"""
        return [self.parse_featured_item(item) for item in items]

    def parse_contest_item(self, item: dict) -> dict:
        url = item.get("contest_url", "")
        if url and not url.startswith("http"):
            url = DETAIL_BASE + url

        return {
            "title": item.get("contest_name", ""),
            "url": url,
            "source": "saikr",
            "raw_text": json.dumps(item, ensure_ascii=False),
            "publish_date": _ts_to_date(item.get("regist_start_time")) or "",
            "collected_at": datetime.now().isoformat(),
            # 详情占位，后续由 merge_detail 填充
            "description": "",
            "organizer": item.get("organiser_name", ""),
            "regist_start": "",
            "regist_end": "",
            "contest_start": "",
            "contest_end": "",
            "category": self.get_class_name(str(item.get("contest_class_second_id", ""))),
            "level": item.get("level_name", ""),
            "attachments": [],
        }

    def parse_featured_item(self, item: dict) -> dict:
        url = item.get("url", "")
        if url and not url.startswith("http"):
            url = DETAIL_BASE + url

        return {
            "title": item.get("title", ""),
            "url": url,
            "source": "saikr",
            "raw_text": json.dumps(item, ensure_ascii=False),
            "publish_date": item.get("contest_time", ""),
            "collected_at": datetime.now().isoformat(),
            "description": "",
            "organizer": item.get("organiser", ""),
            "regist_start": "",
            "regist_end": "",
            "contest_start": "",
            "contest_end": "",
            "category": "",
            "level": "",
            "attachments": [],
        }

    # ---- 详情解析 ----

    def parse_detail(self, detail: dict) -> dict:
        """将详情 API 返回的数据提取为结构化字段。"""
        content_html = detail.get("content", "")

        return {
            "description": _html_to_text(content_html),
            "organizer": _join_organizers(detail),
            "organizer_list": detail.get("organiser", []),
            "co_organizers": detail.get("other_organiser", []),
            "supporters": [s.get("organizer", "") for s in detail.get("sup_organizer", [])],
            "regist_start": _fmt_time(detail.get("regist_start_time")),
            "regist_end": _fmt_time(detail.get("regist_end_time")),
            "contest_start": _fmt_time(detail.get("contest_start_time")),
            "contest_end": _fmt_time(detail.get("contest_end_time")),
            "category": self.get_class_name(str(detail.get("contest_class_second_id", ""))),
            "level": str(detail.get("contest_level", "")),
            "attachments": _parse_attachments(detail.get("attachment", [])),
            "participation": detail.get("participation_explain", ""),
            "contest_stage": _parse_stages(detail.get("contest_stage", {})),
            "raw_detail": json.dumps(detail, ensure_ascii=False),
        }

    def merge_detail(self, item: dict, detail_fields: dict) -> dict:
        """将详情字段合并到列表项中。"""
        item.update(detail_fields)
        # raw_text 合并列表和详情数据
        list_data = {}
        try:
            list_data = json.loads(item.get("raw_text", "{}"))
        except (json.JSONDecodeError, TypeError):
            pass
        detail_data = {}
        try:
            detail_data = json.loads(detail_fields.get("raw_detail", "{}"))
        except (json.JSONDecodeError, TypeError):
            pass
        item["raw_text"] = json.dumps({"list": list_data, "detail": detail_data}, ensure_ascii=False)
        item.pop("raw_detail", None)
        return item


# ---- 辅助函数 ----

def _ts_to_date(ts) -> Optional[str]:
    if not ts or ts == 0:
        return None
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return None


def _fmt_time(val) -> str:
    if not val:
        return ""
    s = str(val)
    # "2026/09/10 18:00:00" 或 "2026-09-10 18:00:00" 格式，只取日期部分
    sep = "/" if "/" in s else "-"
    if sep in s and len(s) >= 10:
        space_idx = s.find(" ")
        date_part = s[:space_idx] if space_idx > 0 else s
        parts = date_part.split(sep)
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            return "-".join(parts)
    # Unix 时间戳
    if s.isdigit() and len(s) >= 10:
        return _ts_to_date(int(s)) or s
    return s


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(separator="\n", strip=True)


def _parse_attachments(attachments: list) -> list[dict]:
    result = []
    for a in attachments:
        if isinstance(a, dict):
            result.append({
                "name": a.get("name", a.get("title", "")),
                "url": a.get("url", a.get("src", "")),
            })
    return result


def _parse_stages(stage: dict) -> list[dict]:
    """解析赛程安排。"""
    if not stage:
        return []
    return [{"name": k, "time": str(v)} for k, v in stage.items() if v]


def _join_organizers(detail: dict) -> str:
    """将主办方/协办方合并为可读字符串。"""
    def _strs(lst):
        return [str(x) if isinstance(x, str) else x.get("organizer", x.get("name", str(x))) for x in lst]

    parts = []
    organiser = _strs(detail.get("organiser", []))
    if organiser:
        parts.append("、".join(organiser))
    co = _strs(detail.get("other_organiser", []))
    if co:
        parts.append("协办: " + "、".join(co))
    return " | ".join(parts) if parts else ""


# ---- 自注册 ----
from ..registry import SourceRegistry  # noqa: E402
from ..clients.saikr import SaikrAPIClient  # noqa: E402

SourceRegistry.register("saikr", SaikrAPIClient, SaikrParser)
