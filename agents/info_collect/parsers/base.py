"""Parser 抽象基类，定义统一接口。"""

from abc import ABC, abstractmethod


class BaseParser(ABC):
    """每个平台实现自己的 parser 子类。"""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def parse_list_page(self, html: str) -> list[dict]:
        """解析列表页内容，返回 [{title, url, publish_date}]。"""
        ...

    @abstractmethod
    async def parse_detail_page(self, html: str) -> str:
        """解析详情页内容，返回原始文本。"""
        ...
