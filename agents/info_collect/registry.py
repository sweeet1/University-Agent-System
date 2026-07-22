"""数据源注册表 — 管理所有已注册的网站爬取实现。"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SourceSpec:
    """描述一个数据源的 Client + Parser 组合。"""

    name: str
    client_class: type
    parser_class: type


class SourceRegistry:
    """全局注册表，各模块在文件末尾自注册。"""

    _sources: dict[str, SourceSpec] = {}

    @classmethod
    def register(cls, name: str, client_class: type, parser_class: type):
        """注册一个数据源。通常在 parser 文件末尾调用。"""
        if name in cls._sources:
            logger.warning("覆盖已注册的数据源: %s", name)
        cls._sources[name] = SourceSpec(
            name=name, client_class=client_class, parser_class=parser_class
        )
        logger.info("注册数据源: %s", name)

    @classmethod
    def get(cls, name: str) -> Optional[SourceSpec]:
        """获取指定数据源的描述。"""
        return cls._sources.get(name)

    @classmethod
    def list_all(cls) -> list[str]:
        """返回所有已注册数据源名称。"""
        return list(cls._sources.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """检查数据源是否已注册。"""
        return name in cls._sources

    @classmethod
    def clear(cls):
        """清空注册表（主要用于测试）。"""
        cls._sources.clear()
