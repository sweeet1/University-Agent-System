"""52jingsai 竞赛网客户端 — 从 /bisai/ 目录抓取竞赛列表。

列表页: https://www.52jingsai.com/bisai/              (主列表)
分页:   https://www.52jingsai.com/bisai/index.php?page=N  (第338页)
分类:   https://www.52jingsai.com/bisai/yingyujingsai/    (英语竞赛)
状态:   ?jsstatus=2 (正在报名)  ?jsstatus=6 (报名结束)

列表项结构: div.bbda.list_bbda  (每项以 | 分隔: 标题|摘要||截止/主办|分类|日期|浏览)
详情页: article-XXXXX-1.html
编码: GBK
"""

import logging
from .base import BaseSourceClient

logger = logging.getLogger(__name__)

BASE_URL = "https://www.52jingsai.com"
LIST_URL = f"{BASE_URL}/bisai/"


class Jingsai52Client(BaseSourceClient):

    def _default_headers(self) -> dict:
        headers = super()._default_headers()
        headers["Accept-Charset"] = "gbk,utf-8;q=0.7,*;q=0.3"
        return headers

    def get_contests(self, page: int = 1, limit: int = 20) -> str:
        """获取 /bisai/ 列表页 HTML，支持分页。

        每页约 20 条竞赛，共 338+ 页。
        page=1 返回首页 URL 本身。
        """
        if page == 1:
            url = LIST_URL
        else:
            url = f"{LIST_URL}index.php?page={page}"

        resp = self.get_with_retry(url)
        resp.encoding = "gbk"
        return resp.text

    def get_contest_detail(self, contest_id: str) -> str:
        """获取竞赛详情页 HTML。"""
        if contest_id.startswith("http"):
            url = contest_id
        elif contest_id.startswith("/"):
            url = f"{BASE_URL}{contest_id}"
        elif contest_id.startswith("article-"):
            url = f"{BASE_URL}/{contest_id}.html"
        else:
            url = f"{BASE_URL}/article-{contest_id}-1.html"
        resp = self.get_with_retry(url)
        resp.encoding = "gbk"
        return resp.text

    def get_featured(self) -> list[dict]:
        return []

    def get_config(self) -> dict:
        return {}
