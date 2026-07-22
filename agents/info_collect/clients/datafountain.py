"""DataFountain 客户端 — 使用已确认的 REST API。

API 确认:
  GET /api/competitions        → 竞赛列表
  GET /api/competitions/{id}   → 竞赛详情
"""

import logging
from .base import BaseSourceClient

logger = logging.getLogger(__name__)

BASE_URL = "https://www.datafountain.cn"

DF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.datafountain.cn/competitions",
}


class DatafountainClient(BaseSourceClient):

    def _default_headers(self) -> dict:
        return DF_HEADERS

    def get_contests(self, page: int = 1, limit: int = 20) -> dict:
        """获取竞赛列表。DF 的 API 一次性返回所有竞赛，无需分页。"""
        resp = self.get_with_retry(f"{BASE_URL}/api/competitions")
        data = resp.json()
        # 返回原始 JSON，parser 负责提取
        return data

    def get_contest_detail(self, contest_id: str) -> dict:
        """获取单条竞赛详情。

        contest_id: 竞赛数字 ID，如 "1169"
        """
        # 支持传入完整 URL
        if contest_id.startswith("http"):
            import re
            m = re.search(r"/competitions?/(\d+)", contest_id)
            contest_id = m.group(1) if m else contest_id.split("/")[-1]

        resp = self.get_with_retry(f"{BASE_URL}/api/competitions/{contest_id}")
        data = resp.json()
        return data
