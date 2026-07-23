"""阿里天池客户端 — 通过 Open API 获取竞赛数据。

API:
  GET /v3/proxy/competition/api/race/page
    参数: visualTab(分类), raceName(搜索), pageNum, pageSize, isAll=true
    返回: {data: {list: [{raceId, name, introduction, raceStartTime, raceEndTime,
           signupStartTime, signupEndTime, bonus, teamCount, tagsList, trackList, ...}]}}

  isSeries=1 的竞赛有 trackList 子赛道，isSeries=0 的为独立赛道。
"""

import logging
from .base import BaseSourceClient

logger = logging.getLogger(__name__)

BASE_URL = "https://tianchi.aliyun.com"
API_URL = f"{BASE_URL}/v3/proxy/competition/api/race/page"

TIANCHI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://tianchi.aliyun.com/competition",
}


class TianchiClient(BaseSourceClient):

    def __init__(self, timeout: int = 30):
        super().__init__(timeout)
        self._search_keywords: list[str] = []

    def set_search_keywords(self, keywords: list[str]):
        """Receive keywords from the crawler for server-side search."""
        self._search_keywords = list(keywords) if keywords else []

    def _default_headers(self) -> dict:
        return TIANCHI_HEADERS

    def get_contests(self, page: int = 1, limit: int = 20) -> dict:
        """获取竞赛列表。

        GET /v3/proxy/competition/api/race/page
        """
        race_name = " ".join(self._search_keywords) if self._search_keywords else ""
        resp = self.get_with_retry(API_URL, params={
            "visualTab": "",
            "raceName": race_name,
            "pageNum": page,
            "pageSize": limit,
            "isAll": "true",
        })
        return resp.json()

    def get_contest_detail(self, contest_id: str) -> dict:
        """获取竞赛详情。

        contest_id: raceId，如 "532503"。
        详情信息已在列表 API 的 introduction/trackList 字段中，此方法返回空。
        """
        # 天池的列表 API 已经包含 introduction + bonus + teamCount + tagsList
        # 详情页为 SSR HTML，不再单独请求
        return {}

    def get_config(self) -> dict:
        return {}

    def get_featured(self) -> list[dict]:
        return []
