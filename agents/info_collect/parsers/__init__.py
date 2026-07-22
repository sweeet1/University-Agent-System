# agents/info_collect/parsers/__init__.py
# 触发各 parser 模块的 import 以完成自注册

from . import saikr       # noqa: F401
from . import jingsai52   # noqa: F401
from . import tianchi     # noqa: F401
from . import heywhale    # noqa: F401
from . import datafountain  # noqa: F401
