"""
用现有 DeepSeek Chat 对关键词初筛结果做兴趣/能力精排。

流程：关键词打分 → 取 Top 池 → 一次 Chat 批量打分 → 与关键词分混合 → 重算综合分。
失败或未配置时原样返回（回退关键词）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .constants import WEIGHT_KEYS
from .llm_copy import _call_chat_completions, _profile_brief, _resolve_llm_credentials


DEFAULT_SEMANTIC_RERANK = {
    "enabled": True,
    "blend": 0.7,           # 语义分权重；关键词为 1-blend
    "pool_size": 8,         # 精排候选池大小（按初分取前 N）
    "temperature": 0.1,
    "max_tokens": 900,
    "timeout": 45,
}


def load_semantic_rerank_settings(rec_cfg: Optional[dict] = None) -> dict:
    settings = dict(DEFAULT_SEMANTIC_RERANK)
    rec_cfg = rec_cfg if isinstance(rec_cfg, dict) else {}
    custom = rec_cfg.get("semantic_rerank", {})
    if isinstance(custom, dict):
        settings.update(custom)
    settings["enabled"] = bool(settings.get("enabled", True))
    try:
        settings["blend"] = min(1.0, max(0.0, float(settings.get("blend", 0.7))))
    except (TypeError, ValueError):
        settings["blend"] = 0.7
    try:
        settings["pool_size"] = max(1, int(settings.get("pool_size", 8)))
    except (TypeError, ValueError):
        settings["pool_size"] = 8
    return settings


def _clamp(score: float) -> float:
    return max(0.0, min(100.0, round(float(score), 1)))


def _item_brief(item: dict) -> dict:
    reqs = item.get("requirements", {}) if isinstance(item.get("requirements"), dict) else {}
    return {
        "title": item.get("title", ""),
        "summary": str(item.get("summary") or "")[:220],
        "category": reqs.get("category", ""),
        "tags": (reqs.get("tags") or [])[:8],
        "required_skills": (reqs.get("required_skills") or [])[:8],
        "team_requirement": reqs.get("team_requirement", ""),
    }


def _parse_rerank_json(text: str) -> Optional[list]:
    if not text:
        return None
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped)
    if fence:
        stripped = fence.group(1).strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        brace = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", stripped)
        if not brace:
            return None
        try:
            data = json.loads(brace.group(0))
        except json.JSONDecodeError:
            return None

    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items
        return None
    if isinstance(data, list):
        return data
    return None


def apply_semantic_rerank(
    scored: List[dict],
    user: dict,
    weights: dict,
    *,
    config: Optional[dict] = None,
    settings: Optional[dict] = None,
) -> tuple[List[dict], dict]:
    """对 scored 前 pool_size 条做 DeepSeek 兴趣/能力精排。

    Returns:
        (updated_scored, meta)  meta 含 used / error / pool_size
    """
    settings = settings or load_semantic_rerank_settings()
    meta: Dict[str, Any] = {
        "used": False,
        "error": None,
        "pool_size": 0,
        "blend": settings.get("blend", 0.7),
    }
    if not settings.get("enabled", True) or not scored:
        return scored, meta

    creds = _resolve_llm_credentials(config)
    if not creds.get("enabled"):
        meta["error"] = {"message": "LLM credentials unavailable"}
        return scored, meta

    pool_size = min(int(settings.get("pool_size", 8)), len(scored))
    pool = scored[:pool_size]
    meta["pool_size"] = pool_size

    payload = {
        "user_profile": _profile_brief(user),
        "candidates": [
            {
                "id": idx,
                "competition": _item_brief(entry["item"]),
                "keyword_scores": {
                    "interest_score": entry["scores"].get("interest_score"),
                    "ability_score": entry["scores"].get("ability_score"),
                },
            }
            for idx, entry in enumerate(pool)
        ],
    }

    system = (
        "你是大学生竞赛推荐精排助手。根据用户画像与竞赛信息，为每条候选重打 "
        "interest_score（兴趣契合）和 ability_score（能力/技能契合），范围 0-100。"
        "不要被标题中的营销词误导；算法编程竞答与 AI 应用/知识赛要区分。"
        "只输出 JSON："
        '{"items":[{"id":0,"interest_score":0,"ability_score":0,'
        '"matched":["短信号"],"unmatched":["短信号"]}]}。'
        "id 必须对应输入 candidates 的 id；不要输出其它文字。"
    )
    user_content = json.dumps(payload, ensure_ascii=False)

    result = _call_chat_completions(
        api_key=creds["api_key"],
        base_url=creds["base_url"],
        model=creds["model"],
        timeout=int(settings.get("timeout") or creds.get("timeout") or 45),
        system=system,
        user_content=user_content,
        temperature=float(settings.get("temperature", 0.1)),
        max_tokens=int(settings.get("max_tokens", 900)),
    )
    if not result.get("ok"):
        meta["error"] = result.get("error") or {"message": "chat call failed"}
        return scored, meta

    items = _parse_rerank_json(result.get("content", ""))
    if not items:
        meta["error"] = {"message": "LLM returned unusable JSON"}
        return scored, meta

    by_id: Dict[int, dict] = {}
    for row in items:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        by_id[idx] = row

    if not by_id:
        meta["error"] = {"message": "No valid scored items in LLM response"}
        return scored, meta

    blend = float(settings.get("blend", 0.7))
    keyword_w = 1.0 - blend
    updated = list(scored)

    for idx, entry in enumerate(pool):
        row = by_id.get(idx)
        if not row:
            continue
        scores = dict(entry.get("scores") or {})
        kw_interest = float(scores.get("interest_score", 0) or 0)
        kw_ability = float(scores.get("ability_score", 0) or 0)
        try:
            llm_interest = _clamp(row.get("interest_score", kw_interest))
        except (TypeError, ValueError):
            llm_interest = kw_interest
        try:
            llm_ability = _clamp(row.get("ability_score", kw_ability))
        except (TypeError, ValueError):
            llm_ability = kw_ability

        new_interest = _clamp(blend * llm_interest + keyword_w * kw_interest)
        new_ability = _clamp(blend * llm_ability + keyword_w * kw_ability)
        scores["interest_score_keyword"] = kw_interest
        scores["ability_score_keyword"] = kw_ability
        scores["interest_score_llm"] = llm_interest
        scores["ability_score_llm"] = llm_ability
        scores["interest_score"] = new_interest
        scores["ability_score"] = new_ability

        total = round(
            sum(float(scores.get(k, 0) or 0) * float(weights.get(k, 0) or 0) for k in WEIGHT_KEYS),
            1,
        )

        matched = list(entry.get("matched_signals") or [])
        unmatched = list(entry.get("unmatched_signals") or [])
        for sig in row.get("matched") or []:
            text = str(sig).strip()
            if text:
                matched.append(f"精排:{text}")
        for sig in row.get("unmatched") or []:
            text = str(sig).strip()
            if text:
                unmatched.append(f"精排缺口:{text}")

        updated[idx] = {
            **entry,
            "scores": scores,
            "total": total,
            "matched_signals": matched,
            "unmatched_signals": unmatched,
            "semantic_reranked": True,
        }

    meta["used"] = True
    return updated, meta
