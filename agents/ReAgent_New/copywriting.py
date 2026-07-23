"""
等级映射与 reason / risk / suggested_action 文案（含个性化解释）。
"""

from __future__ import annotations

from typing import List, Optional

from .constants import COPY_DIM_KEYS, DIM_NAME_MAP, LEVEL_ORDER


def to_level(score: float, level_thresholds: list) -> tuple:
    """根据综合得分返回 (等级代码, 等级中文描述)。"""
    for threshold, code, label in level_thresholds:
        if score >= threshold:
            return code, label
    return "C", "不推荐"


def apply_level_cap(level_code: str, detail: dict, caps: dict) -> str:
    """年级或能力明显不足时封顶推荐等级（如最高 B）。"""
    max_level = caps.get("max_level", "B")
    grade_threshold = caps.get("grade_score_below", 40)
    ability_threshold = caps.get("ability_score_below", 30)
    should_cap = (
        detail.get("grade_score", 100) < grade_threshold
        or detail.get("ability_score", 100) < ability_threshold
    )
    if should_cap and LEVEL_ORDER.get(level_code, 0) > LEVEL_ORDER.get(max_level, 0):
        return max_level
    return level_code


def build_reason_template(detail: dict) -> str:
    """模板理由：优先高分维度，否则取相对优势维度。"""
    high_dims = [
        f"{DIM_NAME_MAP[k]}({int(detail[k])}分)"
        for k in COPY_DIM_KEYS
        if detail.get(k, 0) >= 85
    ]
    if high_dims:
        return "、".join(high_dims)

    ranked = sorted(
        ((k, detail.get(k, 0)) for k in COPY_DIM_KEYS if k in detail),
        key=lambda x: x[1],
        reverse=True,
    )
    top = [
        f"{DIM_NAME_MAP[k]}({int(score)}分)"
        for k, score in ranked[:2]
        if score > 0
    ]
    return "、".join(top) if top else "综合匹配一般，可作为备选关注"


def build_reason(
    detail: dict,
    user: Optional[dict] = None,
    item: Optional[dict] = None,
    matched_signals: Optional[List[str]] = None,
    unmatched_signals: Optional[List[str]] = None,
) -> str:
    """个性化推荐理由：把信号翻成完整句子；失败回退模板。"""
    sentences: List[str] = []
    signals = list(matched_signals or [])

    for sig in signals:
        if not isinstance(sig, str) or ":" not in sig:
            continue
        kind, text = sig.split(":", 1)
        text = text.strip()
        if not text:
            continue
        if kind == "兴趣":
            if "<->" in text:
                left, right = [x.strip() for x in text.split("<->", 1)]
                if left == right:
                    sentences.append(f"你的兴趣「{left}」与该赛主题高度吻合")
                else:
                    sentences.append(
                        f"你的兴趣「{left}」与赛事标签「{right}」相符"
                    )
            else:
                sentences.append(f"你的兴趣「{text}」与该赛方向一致")
        elif kind == "奖项":
            sentences.append(
                text if text.startswith("你有") else f"你有{text}相关经历"
            )
        elif kind == "团队":
            if "<->" in text:
                left, right = [x.strip() for x in text.split("<->", 1)]
                sentences.append(f"该赛要求{right}，与你当前「{left}」状态匹配")
            else:
                sentences.append(f"组队情况：{text}")
        elif kind == "技能命中":
            sentences.append(f"你的技能「{text}」能覆盖赛事要求")
        elif kind == "能力":
            sentences.append(text if "经历" in text else f"能力方面：{text}")
        if len(sentences) >= 3:
            break

    if not sentences and user and item:
        awards = user.get("awards") or []
        if awards and isinstance(awards[0], dict):
            a = awards[0]
            name = a.get("competition_name") or ""
            level = a.get("level") or ""
            award_name = a.get("award_name") or ""
            if name or award_name:
                sentences.append(f"你有{name}{level}{award_name}")
        team = (user.get("team_status") or "").strip()
        reqs = item.get("requirements", {}) if isinstance(item, dict) else {}
        team_req = ""
        if isinstance(reqs, dict):
            team_req = (reqs.get("team_requirement") or "").strip()
        if team and team_req:
            sentences.append(f"该赛要求{team_req}，与你「{team}」一致")

    if sentences:
        return "；".join(sentences[:3])
    return build_reason_template(detail)


def build_risk(
    detail: dict,
    unmatched_signals: Optional[List[str]] = None,
) -> str:
    """根据得分细节与未匹配信号构建风险提示。"""
    low_dims = [
        f"{DIM_NAME_MAP[k]}({int(detail[k])}分)"
        for k in COPY_DIM_KEYS
        if detail.get(k, 0) < 50
    ]

    extra = []
    for sig in (unmatched_signals or [])[:2]:
        text = sig.split(":", 1)[-1] if ":" in sig else sig
        if text:
            extra.append(text)

    if not low_dims:
        team_score = detail.get("team_score", 100)
        if 50 <= team_score < 70:
            msg = (
                f"提示: {DIM_NAME_MAP['team_score']}({int(team_score)}分)，"
                "建议确认参赛形式"
            )
            if extra:
                msg += f"；另需关注：{'、'.join(extra)}"
            return msg
        if extra:
            return f"提示: 建议关注 {'、'.join(extra)}"
        return "无明显风险，建议优先申请"

    msg = f"风险提示: {'; '.join(low_dims)}"
    if extra:
        msg += f"；{'、'.join(extra)}"
    return msg


def build_action(level_code: str, detail: dict, is_backup: bool = False) -> str:
    """根据推荐等级和得分细节生成建议行动。"""
    if is_backup:
        return "可作为备选关注，优先考虑更高匹配项目"
    if level_code == "S":
        return "强烈建议立即准备申请材料，优先排序靠前"
    if level_code == "A":
        actionable = {k: detail[k] for k in COPY_DIM_KEYS if k in detail}
        if actionable:
            low_key, low_score = min(actionable.items(), key=lambda x: x[1])
            if low_score < 70:
                return f"建议关注{DIM_NAME_MAP[low_key]}后尽快申请"
        return "建议尽快准备申请材料"
    if level_code == "B":
        actionable = {k: detail[k] for k in COPY_DIM_KEYS if k in detail}
        if actionable:
            low_key, low_score = min(actionable.items(), key=lambda x: x[1])
            if low_score < 50 and low_key in DIM_NAME_MAP:
                return (
                    f"建议关注{DIM_NAME_MAP[low_key]}，"
                    "同时寻找更匹配的备选项目"
                )
        return "建议关注，同时寻找更匹配的备选项目"
    return "不建议投入精力，推荐关注其他项目"
