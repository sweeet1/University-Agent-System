"""
多样性截取与赛事层级（含金量）加权。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 默认配置（可被 config.yaml recommendation 段覆盖）
# ---------------------------------------------------------------------------

DEFAULT_DIVERSITY = {
    "enabled": True,
    "max_per_category": 1,
}

DEFAULT_PRESTIGE = {
    "enabled": True,
    "mode": "soft_add",  # soft_add | tie_break
    "boost": {
        "national": 10,
        "provincial": 5,
        "association": 2,
        "city": 0,
        "unknown": 0,
    },
}

# 分类归一：避免「数学」与「数学建模」被当成两类而多样性失效
_CATEGORY_NORMALIZE = {
    "数学": "数学建模",
    "数学竞赛": "数学建模",
    "数学建模": "数学建模",
    "建模": "数学建模",
    "计算机": "计算机",
    "算法": "计算机",
    "算法编程": "计算机",
    "算法竞赛": "计算机",
    "编程": "计算机",
    "acm": "计算机",
    "计算机博弈": "计算机博弈",
    "博弈": "计算机博弈",
    "外语": "英语",
    "英语": "英语",
    "英语竞赛": "英语",
    "翻译": "英语",
    "商务英语": "英语",
}

_GENERIC_CATEGORIES = {"", "unknown", "学科竞赛", "其他", "竞赛"}

_TITLE_CATEGORY_HINTS = (
    ("数学建模", "数学建模"),
    ("建模", "数学建模"),
    ("计算机博弈", "计算机博弈"),
    ("算法", "计算机"),
    ("编程", "计算机"),
    ("英语", "英语"),
    ("翻译", "英语"),
)


def load_diversity_settings(rec_cfg: Optional[dict] = None) -> dict:
    """合并默认与 config.recommendation.diversity。"""
    settings = dict(DEFAULT_DIVERSITY)
    rec_cfg = rec_cfg if isinstance(rec_cfg, dict) else {}
    custom = rec_cfg.get("diversity", {})
    if isinstance(custom, dict):
        settings.update(custom)
        try:
            settings["max_per_category"] = max(1, int(settings.get("max_per_category", 1)))
        except (TypeError, ValueError):
            settings["max_per_category"] = 1
        settings["enabled"] = bool(settings.get("enabled", True))
    return settings


def load_prestige_settings(rec_cfg: Optional[dict] = None) -> dict:
    """合并默认与 config.recommendation.prestige / prestige_boost。"""
    settings = {
        "enabled": DEFAULT_PRESTIGE["enabled"],
        "mode": DEFAULT_PRESTIGE["mode"],
        "boost": dict(DEFAULT_PRESTIGE["boost"]),
    }
    rec_cfg = rec_cfg if isinstance(rec_cfg, dict) else {}

    # 兼容文档中的扁平 prestige_boost: {national: 10, ...}
    flat_boost = rec_cfg.get("prestige_boost")
    if isinstance(flat_boost, dict) and flat_boost:
        settings["boost"].update({k: float(v) for k, v in flat_boost.items() if _is_number(v)})
        settings["enabled"] = True

    custom = rec_cfg.get("prestige", {})
    if isinstance(custom, dict):
        if "enabled" in custom:
            settings["enabled"] = bool(custom["enabled"])
        if custom.get("mode") in ("soft_add", "tie_break"):
            settings["mode"] = custom["mode"]
        boost = custom.get("boost", {})
        if isinstance(boost, dict):
            settings["boost"].update(
                {k: float(v) for k, v in boost.items() if _is_number(v)}
            )
    return settings


def _is_number(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _normalize_category_label(label: str) -> Optional[str]:
    text = (label or "").strip().lower()
    if not text or text in _GENERIC_CATEGORIES:
        return None
    # 先精确，再子串
    if text in _CATEGORY_NORMALIZE:
        return _CATEGORY_NORMALIZE[text]
    for raw, norm in _CATEGORY_NORMALIZE.items():
        if raw in text or text in raw:
            return norm
    return text


def category_key(item: dict) -> str:
    """提取用于多样性去重的分类键（归一后）。

    优先：非泛化 category → 可识别 tags → 标题关键词 → other。
    """
    reqs = item.get("requirements", {})
    if not isinstance(reqs, dict):
        reqs = {}

    category = (reqs.get("category") or "").strip()
    norm_cat = _normalize_category_label(category)
    if norm_cat:
        return norm_cat

    tags = reqs.get("tags") or []
    for tag in tags:
        norm = _normalize_category_label(str(tag).strip())
        if norm:
            return norm

    title = str(item.get("title") or "")
    for hint, mapped in _TITLE_CATEGORY_HINTS:
        if hint in title:
            return mapped

    if tags:
        return str(tags[0]).strip().lower() or "other"
    return "other"


def infer_prestige(item: dict) -> str:
    """从 title / organizer / tags / summary 推断赛事层级。

    Returns:
        national | provincial | association | city | unknown
    """
    reqs = item.get("requirements", {})
    tags = []
    if isinstance(reqs, dict):
        tags = [str(t) for t in (reqs.get("tags") or [])]

    parts = [
        str(item.get("title") or ""),
        str(item.get("organizer") or ""),
        str(item.get("summary") or ""),
        " ".join(tags),
    ]
    text = " ".join(parts)

    # 更具体的层级优先（城市联赛标题里也可能带「全国」字样）
    if any(k in text for k in ("城市联赛", "市级", "城市赛")):
        return "city"
    if any(k in text for k in ("校内", "校级选拔", "学院")):
        return "unknown"  # 校内赛不当作高含金量
    if any(k in text for k in ("全国", "国家级", "中国大学生", "教育部", "高教社")):
        return "national"
    if any(k in text for k in ("省级", "全省", "自治区", "省一", "省赛")):
        return "provincial"
    if any(k in text for k in ("协会", "学会", "促进会", "联合会")):
        return "association"
    return "unknown"


def prestige_boost_value(tier: str, prestige_settings: dict) -> float:
    """按层级返回软加分值；关闭时返回 0。"""
    if not prestige_settings.get("enabled", True):
        return 0.0
    boost_map = prestige_settings.get("boost") or {}
    try:
        return float(boost_map.get(tier, boost_map.get("unknown", 0)))
    except (TypeError, ValueError):
        return 0.0


def annotate_prestige_and_category(
    scored: List[dict],
    prestige_settings: Optional[dict] = None,
) -> List[dict]:
    """为 scored 条目补充 category_key / prestige_tier / prestige_boost，并算排序分。

    每条 entry 需含 item, total, scores。
    写入：
      - category_key
      - prestige_tier
      - prestige_boost
      - base_total  （原六维加权分）
      - total       （排序用：soft_add 时 = base + boost，否则仍为 base）
    """
    prestige_settings = prestige_settings or load_prestige_settings()
    mode = prestige_settings.get("mode", "soft_add")
    out = []
    for entry in scored:
        item = entry["item"]
        base = float(entry["total"])
        tier = infer_prestige(item)
        boost = prestige_boost_value(tier, prestige_settings)
        if mode == "soft_add":
            rank_total = round(base + boost, 1)
        else:
            rank_total = base

        scores = dict(entry.get("scores") or {})
        scores["prestige_score"] = boost
        scores["prestige_tier"] = tier

        out.append({
            **entry,
            "base_total": base,
            "total": rank_total,
            "category_key": category_key(item),
            "prestige_tier": tier,
            "prestige_boost": boost,
            "scores": scores,
        })
    return out


def sort_scored(scored: List[dict], prestige_settings: Optional[dict] = None) -> List[dict]:
    """按排序分降序；tie_break 模式下同级用 prestige_boost 再排。"""
    prestige_settings = prestige_settings or load_prestige_settings()
    mode = prestige_settings.get("mode", "soft_add")

    if mode == "tie_break":
        return sorted(
            scored,
            key=lambda x: (x.get("total", 0), x.get("prestige_boost", 0)),
            reverse=True,
        )
    return sorted(scored, key=lambda x: x.get("total", 0), reverse=True)


def select_diverse_top_n(
    scored: List[dict],
    top_n: int,
    diversity_settings: Optional[dict] = None,
) -> List[dict]:
    """同一 category_key 最多保留 max_per_category 条；不足时再放宽补齐。

    scored 应已按分数降序。
    """
    settings = diversity_settings or load_diversity_settings()
    top_n = max(1, int(top_n))

    if not settings.get("enabled", True):
        return scored[:top_n]

    try:
        max_per = max(1, int(settings.get("max_per_category", 1)))
    except (TypeError, ValueError):
        max_per = 1

    selected: List[dict] = []
    counts: Dict[str, int] = {}

    for entry in scored:
        key = entry.get("category_key") or category_key(entry.get("item") or {})
        if counts.get(key, 0) >= max_per:
            continue
        selected.append(entry)
        counts[key] = counts.get(key, 0) + 1
        if len(selected) >= top_n:
            return selected

    selected_ids = {id(e) for e in selected}

    # 第二轮：优先补「尚未出现」的分类，避免同质赛填满
    if len(selected) < top_n:
        for entry in scored:
            if id(entry) in selected_ids:
                continue
            key = entry.get("category_key") or category_key(entry.get("item") or {})
            if key in counts:
                continue
            selected.append(entry)
            selected_ids.add(id(entry))
            counts[key] = counts.get(key, 0) + 1
            if len(selected) >= top_n:
                return selected

    # 第三轮：仍不足则放宽（允许同分类），避免推荐过少
    if len(selected) < top_n:
        for entry in scored:
            if id(entry) in selected_ids:
                continue
            selected.append(entry)
            if len(selected) >= top_n:
                break

    return selected


def force_fill_recommendations(
    recommendations: List[dict],
    scored: List[dict],
    top_n: int,
    build_rec,
) -> List[dict]:
    """最终强制凑满 top_n：在多样性/质量门槛之后执行，优先级最高。

    - 已有条目保持原顺序与 is_backup 标记
    - 不足时按 scored（已降序）补入尚未出现的竞赛，一律标 is_backup=True
    - 候选不足 top_n 时有多少返回多少
    """
    top_n = max(1, int(top_n))
    if len(recommendations) >= top_n:
        return recommendations[:top_n]

    filled = list(recommendations)
    seen = {
        str(r.get("title") or "").strip()
        for r in filled
        if str(r.get("title") or "").strip()
    }

    for entry in scored:
        if len(filled) >= top_n:
            break
        item = entry.get("item") or {}
        title = str(item.get("title") or "").strip()
        if not title or title in seen:
            continue
        rec = build_rec(entry)
        rec["is_backup"] = True
        filled.append(rec)
        seen.add(title)

    return filled[:top_n]
