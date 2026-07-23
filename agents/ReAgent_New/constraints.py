"""
硬性门槛、偏好过滤、质量门槛。
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

from .constants import LEVEL_ORDER
from .diversity import category_key, infer_prestige
from .scoring import score_major
from .utils import DEADLINE_UNKNOWN, days_until_deadline, enrollment_to_grade

DEFAULT_QUALITY_GATE = {
    "enabled": True,
    "min_primary_level": "A",  # 低于此等级标 is_backup
    "allow_backup": True,  # 全是备选时仍返回并标记
    "prefer_fewer": True,  # 有主推时丢掉备选（宁少勿滥）
}


def check_hard_constraints(
    user: dict,
    item: dict,
    deadline: str,
    today: date,
    hard_major_min_score: float = 50.0,
    major_groups: Optional[dict] = None,
) -> Tuple[bool, str]:
    """硬性门槛校验。

    Returns:
        (是否通过, 拒绝原因)
    """
    days = days_until_deadline(deadline, today)
    if days != DEADLINE_UNKNOWN and days < 0:
        return False, "已超过报名截止时间"

    reqs = item.get("requirements", {})
    if not isinstance(reqs, dict):
        return True, ""

    target_majors = reqs.get("target_majors", [])
    if target_majors:
        if score_major(user, item, major_groups) < hard_major_min_score:
            return False, "专业不在面向范围内"

    target_edu = reqs.get("target_education", [])
    education = (user.get("education_level") or "").strip()
    if target_edu:
        if not education:
            return False, "缺少学历信息，无法核验项目学历要求"
        edu_match = any(education in e or e in education for e in target_edu)
        if not edu_match:
            return False, "学历层次不符合要求"

    target_grades = reqs.get("target_grades", [])
    if target_grades:
        user_grade = enrollment_to_grade(user.get("enrollment_year", 0), today)
        grade_match = any(str(g).strip() == user_grade for g in target_grades)
        if not grade_match:
            return False, "年级不符合要求"

    return True, ""


def extract_deadline(item: dict) -> str:
    """从项目字段或 requirements 中取 deadline。"""
    deadline = item.get("deadline", "") or ""
    reqs = item.get("requirements", {})
    if isinstance(reqs, dict):
        deadline = reqs.get("deadline", "") or deadline
    return deadline


def _team_req_is_team(team_req: str) -> bool:
    text = (team_req or "").strip()
    if text in ("均可", "不限", "单人/组队", ""):
        return False
    return any(k in text for k in ("组队", "团队", "人队")) or text in ("3-5人",)


def _team_req_is_solo(team_req: str) -> bool:
    text = (team_req or "").strip()
    return text in ("单人", "个人", "单人申报") or (
        "单人" in text and "组队" not in text
    )


def check_preference_filters(
    item: dict,
    prefs: Optional[dict],
    prestige_tier: Optional[str] = None,
) -> Tuple[bool, str]:
    """用户偏好过滤（recommendation_rules.prefs）。

    支持：
      - require_prestige: ["national"] 或 "national"
      - require_team: "组队" | "单人"
      - exclude_tags: ["英语"]
      - exclude_categories: ["英语"]
    """
    if not isinstance(prefs, dict) or not prefs:
        return True, ""

    tier = prestige_tier or infer_prestige(item)
    req_prestige = prefs.get("require_prestige")
    if req_prestige:
        allowed = (
            [str(x).lower() for x in req_prestige]
            if isinstance(req_prestige, (list, tuple))
            else [str(req_prestige).lower()]
        )
        if tier.lower() not in allowed:
            return False, f"偏好过滤: 只要层级 {allowed}，当前为 {tier}"

    require_team = (prefs.get("require_team") or "").strip()
    if require_team:
        reqs = item.get("requirements", {})
        team_req = ""
        if isinstance(reqs, dict):
            team_req = (reqs.get("team_requirement") or "").strip()
        flexible = team_req in ("", "均可", "不限", "单人/组队")
        if require_team in ("组队", "团队"):
            if _team_req_is_solo(team_req) and not flexible:
                return False, f"偏好过滤: 只要组队，当前要求为「{team_req}」"
        elif require_team in ("单人", "个人", "单人申报"):
            if _team_req_is_team(team_req) and not flexible:
                return False, f"偏好过滤: 只要单人，当前要求为「{team_req}」"

    exclude_tags = prefs.get("exclude_tags") or []
    if exclude_tags:
        reqs = item.get("requirements", {})
        tags = []
        if isinstance(reqs, dict):
            tags = [str(t).lower() for t in (reqs.get("tags") or [])]
            cat = (reqs.get("category") or "").strip().lower()
            if cat:
                tags.append(cat)
        title = str(item.get("title") or "").lower()
        blob = " ".join(tags) + " " + title
        for ex in exclude_tags:
            ex_l = str(ex).strip().lower()
            if ex_l and ex_l in blob:
                return False, f"偏好过滤: 排除含「{ex}」的项目"

    exclude_categories = prefs.get("exclude_categories") or []
    if exclude_categories:
        key = category_key(item)
        for ex in exclude_categories:
            if str(ex).strip() and str(ex).strip() in key:
                return False, f"偏好过滤: 排除分类「{ex}」"

    return True, ""


def load_quality_gate(rec_cfg: Optional[dict] = None) -> dict:
    """合并默认与 config.recommendation.quality_gate。"""
    settings = dict(DEFAULT_QUALITY_GATE)
    rec_cfg = rec_cfg if isinstance(rec_cfg, dict) else {}
    custom = rec_cfg.get("quality_gate", {})
    if isinstance(custom, dict):
        settings.update(custom)
    settings["enabled"] = bool(settings.get("enabled", True))
    settings["allow_backup"] = bool(settings.get("allow_backup", True))
    settings["prefer_fewer"] = bool(settings.get("prefer_fewer", True))
    return settings


def apply_quality_gate(
    recommendations: List[dict],
    quality_gate: Optional[dict] = None,
) -> List[dict]:
    """分数门槛：低于 min_primary_level 标 is_backup；有主推时宁少勿滥。"""
    settings = quality_gate or dict(DEFAULT_QUALITY_GATE)
    if not settings.get("enabled", True):
        for r in recommendations:
            r.setdefault("is_backup", False)
        return recommendations

    min_level = str(settings.get("min_primary_level") or "A")
    min_order = LEVEL_ORDER.get(min_level, 3)

    for r in recommendations:
        level = r.get("recommend_level", "C")
        r["is_backup"] = LEVEL_ORDER.get(level, 0) < min_order

    primaries = [r for r in recommendations if not r.get("is_backup")]
    backups = [r for r in recommendations if r.get("is_backup")]

    if primaries and settings.get("prefer_fewer", True):
        # 有主推则不带备选，并重排 rank
        return primaries
    if primaries:
        return primaries + backups
    if settings.get("allow_backup", True):
        return backups
    return []
