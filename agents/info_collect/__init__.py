# agents/info_collect/__init__.py
# 触发子模块 import，完成 SourceRegistry 自注册

from . import registry   # noqa: F401
from . import parsers     # noqa: F401 (triggers parser self-registration)
from . import clients     # noqa: F401
from .registry import SourceRegistry
