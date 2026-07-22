"""和鲸社区客户端 — 通过页面抓取获取竞赛数据。

现状: 和鲸竞赛页为 React SPA，无公开 JSON API。
      GraphQL 端点存在但竞赛数据非查询字段。
      暂使用 HTML 页面抓取，数据可能不完整。
"""

import logging
from .base import BaseSourceClient

logger = logging.getLogger(__name__)

BASE_URL = "https://www.heywhale.com"


class HeywhaleClient(BaseSourceClient):

    def get_contests(self, page: int = 1, limit: int = 20) -> str:
        """获取竞赛相关页面 HTML。"""
        # 尝试列表页
        urls = [
            f"{BASE_URL}/competition",
            f"{BASE_URL}/about/competition",
        ]
        for url in urls:
            try:
                resp = self.get_with_retry(url, params={"page": page} if page > 1 else None)
                if resp.status_code == 200:
                    return resp.text
            except Exception:
                continue
        return ""

    def get_contest_detail(self, contest_id: str) -> str:
        """获取竞赛详情页 HTML。"""
        if contest_id.startswith("http"):
            url = contest_id
        else:
            url = f"{BASE_URL}/competition/{contest_id}"
        resp = self.get_with_retry(url)
        return resp.text
