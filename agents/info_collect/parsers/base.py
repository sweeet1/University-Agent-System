"""Parser 抽象基类 — 每个平台实现自己的 parser 子类。"""

from abc import ABC, abstractmethod


class BaseParser(ABC):
    """每个平台实现自己的 parser 子类。

    子类需要实现:
      - parse_list(data) → list[dict]  解析列表数据为 raw_item 列表
      - parse_detail(data) → dict      解析详情数据为结构化字段

    可选覆盖:
      - merge_detail(item, detail_fields) → dict  合并详情到列表项
      - configure(config_data)                     接收配置/分类数据
    """

    def __init__(self, config: dict):
        self.config = config

    def configure(self, config_data):
        """接收客户端提供的辅助配置（如分类映射），子类按需覆盖。"""

    @abstractmethod
    def parse_list(self, data) -> list[dict]:
        """解析列表页数据，返回 raw_item 列表。

        data 类型取决于具体 Client 的返回：JSON API 返回 dict，HTML 页面返回 str。
        每个 raw_item 至少包含: title, url, source, raw_text, publish_date, collected_at
        """
        ...

    @abstractmethod
    def parse_detail(self, data) -> dict:
        """解析详情页数据，返回结构化字段。

        返回的字段包括: description, organizer, regist_start, regist_end,
                       contest_start, contest_end, category, level, attachments 等
        """
        ...

    def merge_detail(self, item: dict, detail_fields: dict) -> dict:
        """合并详情字段到列表项，子类可按需覆盖（如 raw_text 合并策略）。"""
        item.update(detail_fields)
        return item

    def parse_featured_list(self, items: list[dict]) -> list[dict]:
        """解析首页/推荐数据为 raw_item 列表。子类按需覆盖，默认返回空列表。"""
        return []
