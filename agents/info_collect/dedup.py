from .storage import Storage


class DedupManager:
    """基于 URL + source 的去重管理。"""

    def __init__(self, storage: Storage):
        self.storage = storage

    def is_duplicate(self, url: str, source: str) -> bool:
        return self.storage.exists(url, source)

    def filter_new_items(self, items: list[dict]) -> list[dict]:
        """过滤出未收录的竞赛，已存在的标记为 updated。"""
        new_items = []
        for item in items:
            if not self.is_duplicate(item["url"], item["source"]):
                new_items.append(item)
        return new_items
