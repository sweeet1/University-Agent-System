"""赛氪 API 客户端 — 直接调用 apiv4buffer.saikr.com 接口。"""

import logging

import httpx
from .base import BaseSourceClient

logger = logging.getLogger(__name__)

BASE_URL = "https://apiv4buffer.saikr.com"

# saikr 需要特殊的请求头
SAIKR_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://www.saikr.com/",
    "Accept": "application/json, text/plain, */*",
}


class SaikrAPIClient(BaseSourceClient):
    """封装赛氪 API 调用。"""

    def _default_headers(self) -> dict:
        return SAIKR_HEADERS

    def get_contests(self, page: int = 1, limit: int = 20, **kwargs) -> dict:
        params = {
            "page": page,
            "limit": min(limit, 20),
            "univs_id": "",
            "class_id": kwargs.get("class_id", ""),
            "level": kwargs.get("level", 0),
            "sort": kwargs.get("sort", 0),
        }
        resp = self.get_with_retry(f"{BASE_URL}/api/pc/contest/lists", params=params)
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"API 返回错误: {data.get('msg', 'unknown')}")
        return data["data"]

    def get_config(self) -> dict:
        resp = self.get_with_retry(f"{BASE_URL}/api/pc/contest/listConfig")
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"API 返回错误: {data.get('msg', 'unknown')}")
        return data["data"]

    def get_featured(self) -> list[dict]:
        resp = self.get_with_retry(f"{BASE_URL}/api/pc/home/index")
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"API 返回错误: {data.get('msg', 'unknown')}")
        return data["data"].get("contest_data", [])

    def get_contest_detail(self, contest_url: str) -> dict:
        resp = self.get_with_retry(
            f"{BASE_URL}/api/pc/contest/info",
            params={"contest_url": contest_url, "isp": ""},
        )
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"API 返回错误: {data.get('msg', 'unknown')}")
        return data["data"]
