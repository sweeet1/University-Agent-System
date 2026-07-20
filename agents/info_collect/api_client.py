"""赛氪 API 客户端 — 直接调用 apiv4buffer.saikr.com 接口。"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://apiv4buffer.saikr.com"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://www.saikr.com/",
    "Accept": "application/json, text/plain, */*",
}


class SaikrAPIClient:
    """封装赛氪 API 调用。"""

    def __init__(self, timeout: int = 60):
        self.client = httpx.Client(timeout=timeout, headers=DEFAULT_HEADERS)

    def close(self):
        self.client.close()

    def get_contests(
        self,
        page: int = 1,
        limit: int = 20,
        class_id: str = "",
        level: int = 0,
        sort: int = 0,
    ) -> dict:
        """获取竞赛列表。

        Args:
            page: 页码
            limit: 每页条数 (最大 20)
            class_id: 分类ID，空字符串表示全部
            level: 级别 (0=全部)
            sort: 排序 (0=默认)
        """
        params = {
            "page": page,
            "limit": min(limit, 20),
            "univs_id": "",
            "class_id": class_id,
            "level": level,
            "sort": sort,
        }
        resp = self.client.get(f"{BASE_URL}/api/pc/contest/lists", params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"API 返回错误: {data.get('msg', 'unknown')}")
        return data["data"]

    def get_config(self) -> dict:
        """获取分类配置 (classData)。"""
        resp = self.client.get(f"{BASE_URL}/api/pc/contest/listConfig")
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"API 返回错误: {data.get('msg', 'unknown')}")
        return data["data"]

    def get_featured(self) -> list[dict]:
        """获取首页推荐竞赛。"""
        resp = self.client.get(f"{BASE_URL}/api/pc/home/index")
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"API 返回错误: {data.get('msg', 'unknown')}")
        return data["data"].get("contest_data", [])

    def get_contest_detail(self, contest_url: str) -> dict:
        """获取竞赛详情（描述、附件、赛程、主办方等）。

        Args:
            contest_url: 列表 API 返回的 contest_url 字段，如 "58394", "TFB2026"
        """
        resp = self.client.get(
            f"{BASE_URL}/api/pc/contest/info",
            params={"contest_url": contest_url, "isp": ""},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"API 返回错误: {data.get('msg', 'unknown')}")
        return data["data"]
