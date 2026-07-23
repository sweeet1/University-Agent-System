"""
六维打分：连续兴趣/能力分 + 信号收集（Step 5–6）。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from .synonyms import (
    DEFAULT_MAJOR_GROUPS,
    conceptual_overlap_detail,
    count_skill_overlap,
    user_ability_corpus,
)
from .utils import (
    DEADLINE_PARSE_FALLBACK,
    DEADLINE_UNKNOWN,
    days_until_deadline,
    enrollment_to_grade,
    grade_to_min_year,
    parse_available_month_range,
    safe_int,
)


def default_if_missing(dim_name: str, user_value: str, fallback: float) -> float:
    """数据缺失时的默认分值。"""
    _ = dim_name, user_value
    return fallback


def _clamp(score: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, round(score, 1)))


def score_major(
    user: dict,
    item: dict,
    major_groups: Optional[dict] = None,
) -> float:
    """维度一：专业匹配度。"""
    user_major = (user.get("major") or "").strip()
    reqs = item.get("requirements", {})
    if not isinstance(reqs, dict):
        return default_if_missing("专业匹配", user_major, 70.0)

    targets = reqs.get("target_majors", [])
    if not targets:
        return 90.0

    user_lower = user_major.lower()
    for t in targets:
        t_lower = t.strip().lower()
        if user_lower == t_lower:
            return 100.0
        if t_lower in user_lower or user_lower in t_lower:
            return 85.0

    groups = major_groups if major_groups is not None else DEFAULT_MAJOR_GROUPS
    user_category = None
    proj_category = None
    for cat, keywords in groups.items():
        for kw in keywords:
            if kw in user_lower:
                user_category = cat
            for t in targets:
                if kw in t.strip().lower():
                    proj_category = cat

    if user_category and user_category == proj_category:
        return 80.0
    return 30.0


def score_grade(user: dict, item: dict, today: Optional[date] = None) -> float:
    """维度二：年级/学历匹配度。"""
    if today is None:
        today = date.today()
    enrollment_year = safe_int(user.get("enrollment_year", 0), 0)
    education = (user.get("education_level") or "").strip()

    reqs = item.get("requirements", {})
    if not isinstance(reqs, dict):
        return default_if_missing("年级匹配", "", 70.0)

    target_grades = reqs.get("target_grades", []) or []
    target_edu = reqs.get("target_education", []) or []

    if not target_grades and not target_edu:
        return 90.0

    if not target_grades and target_edu:
        if not education:
            return 50.0
        edu_match = any(education in e or e in education for e in target_edu)
        return 100.0 if edu_match else 50.0

    user_grade = enrollment_to_grade(enrollment_year, today)

    edu_match = True
    if target_edu:
        if not education:
            edu_match = False
        else:
            edu_match = any(education in e or e in education for e in target_edu)

    grade_match = any(str(g).strip() == user_grade for g in target_grades)

    if grade_match and edu_match:
        return 100.0
    if grade_match and not edu_match:
        return 50.0

    latest_enroll = grade_to_min_year(target_grades, today)
    if latest_enroll != 9999 and enrollment_year > latest_enroll:
        return 40.0
    return 60.0


def score_interest(
    user: dict,
    item: dict,
    synonym_groups: list = None,
) -> Tuple[float, List[str]]:
    """维度三：兴趣连续分 = 100 * overlap / max(|U|, |T|, 1)。

    Returns:
        (score, matched_interest_signals)
    """
    user_interests = user.get("interests", []) or []
    reqs = item.get("requirements", {})
    if not isinstance(reqs, dict):
        return default_if_missing("兴趣匹配", "", 70.0), []

    tags = list(reqs.get("tags", []) or [])
    category = (reqs.get("category", "") or "").strip()
    if category and category.lower() not in ("unknown", "学科竞赛", "其他"):
        tags.append(category)

    if not user_interests or not tags:
        return 70.0, []

    overlap, signals = conceptual_overlap_detail(
        user_interests, tags, synonym_groups
    )
    denom = max(len(user_interests), len(tags), 1)
    return _clamp(100.0 * overlap / denom), signals


def has_related_experience(user: dict, item: dict, corpus: str = None) -> bool:
    """检查用户是否有与项目相关的竞赛/科研经历。"""
    combined = corpus if corpus is not None else user_ability_corpus(user)
    reqs = item.get("requirements", {})
    if not isinstance(reqs, dict):
        return False

    tags = reqs.get("tags", []) or []
    category = (reqs.get("category", "") or "").strip()
    keywords = list(tags)
    if category and category.lower() not in ("unknown", "学科竞赛", "其他"):
        keywords.append(category)

    for kw in keywords:
        text = str(kw).strip().lower()
        if len(text) >= 2 and text in combined:
            return True
    return False


def score_ability(
    user: dict,
    item: dict,
    corpus: str = None,
    skill_normalize: Optional[dict] = None,
) -> Tuple[float, List[str], List[str]]:
    """维度四：能力连续分 ≈ 100 * matched/required，相关经历软加分。

    Returns:
        (score, matched_skill_signals, unmatched_skill_signals)
    """
    user_skills = {str(s).lower() for s in (user.get("skills") or []) if s}
    if corpus is None:
        corpus = user_ability_corpus(user)
    reqs = item.get("requirements", {})
    if not isinstance(reqs, dict):
        return default_if_missing("能力匹配", "", 70.0), [], []

    required = reqs.get("required_skills", []) or []
    related = has_related_experience(user, item, corpus)

    if not required:
        score = 85.0 if related else 70.0
        signals = ["能力:有相关竞赛/科研经历"] if related else []
        return score, signals, []

    overlap, total, matched, unmatched = count_skill_overlap(
        user_skills, required, corpus, skill_normalize
    )
    ratio = overlap / total if total > 0 else 0.0
    score = 100.0 * ratio
    if related:
        if score <= 0:
            score = 45.0
        else:
            score = min(100.0, score + 15.0)

    matched_signals = [f"技能命中:{s}" for s in matched]
    if related and not matched_signals:
        matched_signals.append("能力:有相关竞赛/科研经历")
    unmatched_signals = [f"技能未命中:{s}" for s in unmatched]
    return _clamp(score), matched_signals, unmatched_signals


def score_deadline(
    deadline_str: str,
    today: date,
    available_time: str = "",
) -> float:
    """维度五：截止时间可行性。"""
    days = days_until_deadline(deadline_str, today)
    if days == DEADLINE_UNKNOWN:
        base = 70.0
    elif days > 30:
        base = 100.0
    elif days >= 15:
        base = 80.0
    elif days >= 7:
        base = 50.0
    elif days >= 0:
        base = 20.0
    else:
        return 0.0

    month_range = parse_available_month_range(available_time)
    if (
        month_range
        and days not in (DEADLINE_UNKNOWN, DEADLINE_PARSE_FALLBACK)
        and days >= 0
    ):
        deadline_date = today + timedelta(days=days)
        (y1, m1), (y2, m2) = month_range
        start = date(y1, m1, 1)
        if m2 == 12:
            end = date(y2, 12, 31)
        else:
            end = date(y2, m2 + 1, 1) - timedelta(days=1)
        if not (start <= deadline_date <= end):
            base = min(base, 40.0)
    return base


def score_team(user: dict, item: dict) -> Tuple[float, List[str], List[str]]:
    """维度六：团队匹配度。

    Returns:
        (score, matched_signals, unmatched_signals)
    """
    user_team = (user.get("team_status") or "").strip()
    reqs = item.get("requirements", {})
    if not isinstance(reqs, dict):
        return default_if_missing("团队匹配", user_team, 70.0), [], []

    team_req = (reqs.get("team_requirement", "") or "").strip()
    if not team_req:
        return 90.0, [], []

    user_solo = user_team == "单人申报"
    user_looking = user_team == "寻找队友"
    user_has_team = user_team == "已有团队"
    req_alone = team_req in ("单人", "个人", "单人申报")
    req_team = team_req in ("组队", "团队", "3-5人")
    req_any = team_req in ("均可", "不限", "单人/组队")

    if req_any:
        sig = [f"团队:{user_team or '未填'}<->{team_req}(不限)"] if user_team else []
        return 90.0, sig, []
    if user_solo and req_alone:
        return 100.0, [f"团队:单人申报<->{team_req}"], []
    if user_has_team and req_team:
        return 100.0, [f"团队:已有团队<->{team_req}"], []
    if user_looking and req_team:
        return 90.0, [f"团队:寻找队友<->{team_req}"], []
    if user_looking and req_alone:
        return 70.0, [], [f"团队:寻找队友 vs 要求{team_req}"]
    if user_solo and req_team:
        return 30.0, [], [f"团队:单人申报 vs 要求{team_req}"]
    if user_has_team and req_alone:
        return 60.0, [], [f"团队:已有团队 vs 要求{team_req}"]
    return 60.0, [], []


def _award_signals(user: dict, item: dict) -> List[str]:
    """绑定奖项与项目 tags 的命中信号。"""
    signals = []
    reqs = item.get("requirements", {})
    tags = []
    if isinstance(reqs, dict):
        tags = [str(t).lower() for t in (reqs.get("tags") or [])]
        cat = (reqs.get("category") or "").strip().lower()
        if cat and cat not in ("unknown", "学科竞赛", "其他"):
            tags.append(cat)

    for award in user.get("awards") or []:
        if not isinstance(award, dict):
            continue
        name = str(award.get("competition_name") or "")
        level = str(award.get("level") or "")
        award_name = str(award.get("award_name") or "")
        blob = f"{name} {award_name}".lower()
        if any(t and t in blob for t in tags):
            label = "·".join(x for x in (name, level, award_name) if x)
            signals.append(f"奖项:{label}")
    return signals


def score_all_dimensions(
    user: dict,
    item: dict,
    deadline: str,
    today: date,
    ability_corpus: str = None,
    synonym_groups: list = None,
    major_groups: Optional[dict] = None,
    skill_normalize: Optional[dict] = None,
) -> Tuple[dict, List[str], List[str]]:
    """一次算出六维分数 + matched/unmatched signals。"""
    interest_score, interest_matched = score_interest(user, item, synonym_groups)
    ability_score, ability_matched, ability_unmatched = score_ability(
        user, item, ability_corpus, skill_normalize
    )
    team_score, team_matched, team_unmatched = score_team(user, item)

    scores = {
        "major_score": score_major(user, item, major_groups),
        "grade_score": score_grade(user, item, today),
        "interest_score": interest_score,
        "ability_score": ability_score,
        "deadline_score": score_deadline(
            deadline, today, user.get("available_time", "")
        ),
        "team_score": team_score,
    }

    matched = []
    matched.extend(interest_matched)
    matched.extend(ability_matched)
    matched.extend(team_matched)
    matched.extend(_award_signals(user, item))

    unmatched = []
    unmatched.extend(ability_unmatched)
    unmatched.extend(team_unmatched)

    return scores, matched, unmatched
