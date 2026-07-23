"""
路径、配置加载，以及年级 / 截止日等通用工具。

不含打分与业务判断；同义词、技能匹配等见 synonyms / scoring。
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Union

# deadline 解析哨兵：表示日期未知（区别于已过期或解析失败）
DEADLINE_UNKNOWN = -999998

# 解析失败但非 unknown 时的占位天数（视为「很远」，避免当已过期）
DEADLINE_PARSE_FALLBACK = 99999


def project_root() -> Path:
    """返回项目根目录（含 config/、data/、agents/ 的目录）。

    本文件位于 agents/ReAgent_New/，因此向上两级到仓库根。
    """
    return Path(__file__).resolve().parents[2]


def resolve_path(path_value: Union[str, Path]) -> Path:
    """将配置中的相对路径解析为基于项目根的绝对 Path（不写死盘符）。"""
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (project_root() / path).resolve()


def load_config(config_path: Optional[str] = None) -> dict:
    """从 config/config.yaml 加载配置；失败时返回空 dict，不中断进程。"""
    path = (
        resolve_path(config_path)
        if config_path
        else project_root() / "config" / "config.yaml"
    )
    if not path.exists():
        return {}
    try:
        import yaml

        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_json_file(filepath: Union[str, Path]) -> dict:
    """读取 JSON 文件；不存在或解析失败时返回空 dict。"""
    path = Path(filepath)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def build_sample_input(
    config: Optional[dict] = None,
    sample_path: Optional[str] = None,
) -> dict:
    """从项目 data/processed 下的标准样例组装 RecommendationAgent 输入。

    样例路径优先顺序：
    1. 显式传入 sample_path
    2. config.recommendation.sample_input_path
    3. 默认 ./data/processed/recommendation_input_sample.json
    """
    cfg = config or {}
    rec_cfg = cfg.get("recommendation", {}) if isinstance(cfg, dict) else {}
    default_path = "./data/processed/recommendation_input_sample.json"
    path_value = sample_path or (
        rec_cfg.get("sample_input_path", default_path)
        if isinstance(rec_cfg, dict)
        else default_path
    )
    path = resolve_path(path_value)
    payload = load_json_file(path)
    if not payload:
        return {
            "task_id": "",
            "user_input": "",
            "task_type": "recommendation",
            "user_profile": {},
            "context": {},
            "input_data": {},
            "history": [],
            "required_output": "markdown",
            "metadata": {
                "sample_path": str(path),
                "load_error": "sample_input_not_found_or_invalid",
            },
        }
    return payload


def safe_int(value, default: int = 0) -> int:
    """将入学年份等字段安全转为 int。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def enrollment_to_grade(enrollment_year, today: Optional[date] = None) -> str:
    """根据入学年份推断当前年级文字描述。

    使用实时日期计算，而非硬编码年份月份。
    业务规则：每年 9 月开学后年级自动进阶。
    """
    year = safe_int(enrollment_year, 0)
    if year <= 0:
        return "未知"
    if today is None:
        today = date.today()
    # 例：2024 年 9 月入学 → 2024-09~2025-08 为大一
    academic_years = today.year - year
    if today.month < 9:
        academic_years -= 1
    grade_index = academic_years + 1  # 1=大一
    if grade_index <= 1:
        return "大一"
    if grade_index == 2:
        return "大二"
    if grade_index == 3:
        return "大三"
    if grade_index == 4:
        return "大四"
    return f"大{grade_index}及以上"


def grade_to_min_year(target_grades: list, today: Optional[date] = None) -> int:
    """将目标年级列表转换为「满足最低年级要求」的最晚入学年份。

    例：要求大三及以上、今天 2026-07 → 最晚入学年约为 2023。
    无有效年级限制时返回 9999。
    """
    if not target_grades:
        return 9999
    if today is None:
        today = date.today()
    grade_map = {"大一": 1, "大二": 2, "大三": 3, "大四": 4, "大五": 5}
    min_grade = 5
    found = False
    for g in target_grades:
        key = str(g).strip()
        if key in grade_map:
            min_grade = min(min_grade, grade_map[key])
            found = True
    if not found:
        return 9999
    offset = 1 if today.month >= 9 else 0
    return today.year + offset - min_grade


def days_until_deadline(deadline_str: str, today: Optional[date] = None) -> int:
    """解析截止日期字符串，计算距离今天的天数。

    支持格式：2026-08-15 / 2026/08/15 / 2026.08.15

    Returns:
        天数差；unknown/空 返回 DEADLINE_UNKNOWN；其他解析失败返回 DEADLINE_PARSE_FALLBACK
    """
    if today is None:
        today = date.today()
    if not deadline_str or str(deadline_str).strip().lower() == "unknown":
        return DEADLINE_UNKNOWN
    text = str(deadline_str).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            dt = datetime.strptime(text, fmt).date()
            return (dt - today).days
        except ValueError:
            continue
    return DEADLINE_PARSE_FALLBACK


def parse_available_month_range(available_time: str):
    """解析 available_time 中的起止年月，失败返回 None。

    支持示例：2026年7月-9月 / 2026年7月-2026年9月 / 2026-07~2026-09

    Returns:
        ((y1, m1), (y2, m2)) 或 None
    """
    if not available_time:
        return None
    text = str(available_time).strip()
    patterns = [
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*[-~—至到]+\s*(\d{4})\s*年\s*(\d{1,2})\s*月",
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*[-~—至到]+\s*(\d{1,2})\s*月",
        r"(\d{4})[-/.](\d{1,2})\s*[-~—至到]+\s*(\d{4})[-/.](\d{1,2})",
    ]
    m = re.search(patterns[0], text)
    if m:
        y1, mo1, y2, mo2 = map(int, m.groups())
        return (y1, mo1), (y2, mo2)
    m = re.search(patterns[1], text)
    if m:
        y1, mo1, mo2 = map(int, m.groups())
        return (y1, mo1), (y1, mo2)
    m = re.search(patterns[2], text)
    if m:
        y1, mo1, y2, mo2 = map(int, m.groups())
        return (y1, mo1), (y2, mo2)
    return None
