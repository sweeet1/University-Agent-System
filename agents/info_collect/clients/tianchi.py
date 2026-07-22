"""阿里天池客户端 — 通过页面抓取获取竞赛数据。

现状: 天池竞赛列表页为服务端渲染，API 端点均需登录。使用 HTML 抓取作为主要方式。
竞赛链接格式: https://tianchi.aliyun.com/competition/{id}
"""

import logging
from .base import BaseSourceClient

logger = logging.getLogger(__name__)

BASE_URL = "https://tianchi.aliyun.com"

TIANCHI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://tianchi.aliyun.com/",
}


class TianchiClient(BaseSourceClient):

    def _default_headers(self) -> dict:
        return TIANCHI_HEADERS

    def get_contests(self, page: int = 1, limit: int = 20) -> str:
        """获取竞赛列表页 HTML（SSR 页面）。"""
        resp = self.get_with_retry(f"{BASE_URL}/competition",
                                   params={"page": page} if page > 1 else None)
        return resp.text

    def get_contest_detail(self, contest_id: str) -> str:
        """获取竞赛详情页 HTML。

        contest_id: 竞赛 ID，如 "532495"，或完整 URL。
        """
        if contest_id.startswith("http"):
            url = contest_id
        else:
            url = f"{BASE_URL}/competition/{contest_id}"
        resp = self.get_with_retry(url)
        return resp.text
