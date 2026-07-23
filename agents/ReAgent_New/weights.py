"""
权重归一化与等级阈值加载（无打分业务）。
"""

from __future__ import annotations

from typing import Optional

from .constants import (
    DEFAULT_LEVEL_CAPS,
    DEFAULT_WEIGHTS,
    HARD_MAJOR_MIN_SCORE,
    LEVEL_LABELS,
    LEVEL_THRESHOLDS,
    WEIGHT_KEYS,
)
from .diversity import load_diversity_settings, load_prestige_settings
from .constraints import load_quality_gate
from .llm_copy import load_llm_copy_settings
from .semantic_rerank import load_semantic_rerank_settings
from .synonyms import load_lexicon


def normalize_weights(weights: dict) -> dict:
    """归一化权重，避免总和不为 1 时综合分整体偏高/偏低。"""
    cleaned = {}
    for key in WEIGHT_KEYS:
        try:
            cleaned[key] = float(weights.get(key, DEFAULT_WEIGHTS[key]))
        except (TypeError, ValueError):
            cleaned[key] = float(DEFAULT_WEIGHTS[key])
        if cleaned[key] < 0:
            cleaned[key] = 0.0
    total = sum(cleaned.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in cleaned.items()}


def load_base_weights(config: Optional[dict] = None) -> dict:
    """从默认权重 + config.yaml recommendation.weights 加载并归一化。"""
    weights = dict(DEFAULT_WEIGHTS)
    cfg = config or {}
    rec_cfg = cfg.get("recommendation", {})
    if isinstance(rec_cfg, dict):
        custom = rec_cfg.get("weights", {})
        if isinstance(custom, dict):
            weights.update(custom)
    return normalize_weights(weights)


def resolve_weights(base_weights: dict, rules: Optional[dict] = None) -> dict:
    """合并单次请求中的权重覆盖并归一化，不修改 base_weights。"""
    weights = dict(base_weights)
    rules = rules if isinstance(rules, dict) else {}
    custom = rules.get("weights", {})
    if isinstance(custom, dict):
        weights.update(custom)
    return normalize_weights(weights)


def load_level_thresholds(config: Optional[dict] = None) -> list:
    """从默认阈值 + config.yaml 加载等级划分（按分数从高到低排序）。

    Returns:
        [(threshold, code, label), ...]
    """
    thresholds = list(LEVEL_THRESHOLDS)
    cfg = config or {}
    rec_cfg = cfg.get("recommendation", {})
    if not isinstance(rec_cfg, dict):
        return sorted(thresholds, key=lambda x: x[0], reverse=True)

    custom = rec_cfg.get("level_thresholds", {})
    if not isinstance(custom, dict):
        return sorted(thresholds, key=lambda x: x[0], reverse=True)

    order = ["S", "A", "B", "C"]
    if all(k in custom for k in order):
        thresholds = [
            (float(custom[code]), code, LEVEL_LABELS[code]) for code in order
        ]
    return sorted(thresholds, key=lambda x: x[0], reverse=True)


def load_level_caps(config: Optional[dict] = None) -> dict:
    """加载等级封顶规则（默认 + config.recommendation.caps）。"""
    caps = dict(DEFAULT_LEVEL_CAPS)
    cfg = config or {}
    rec_cfg = cfg.get("recommendation", {})
    if isinstance(rec_cfg, dict):
        custom = rec_cfg.get("caps", {})
        if isinstance(custom, dict):
            caps.update(custom)
    return caps


def load_recommendation_settings(config: Optional[dict] = None) -> dict:
    """汇总 recommendation 段常用设置，供 Agent.__init__ 使用。"""
    cfg = config or {}
    rec_cfg = cfg.get("recommendation", {})
    if not isinstance(rec_cfg, dict):
        rec_cfg = {}
    return {
        "weights": load_base_weights(cfg),
        "level_thresholds": load_level_thresholds(cfg),
        "level_caps": load_level_caps(cfg),
        "hard_constraints_enabled": bool(rec_cfg.get("hard_constraints", True)),
        "hard_major_min_score": float(
            rec_cfg.get("hard_major_min_score", HARD_MAJOR_MIN_SCORE)
        ),
        "diversity": load_diversity_settings(rec_cfg),
        "prestige": load_prestige_settings(rec_cfg),
        "quality_gate": load_quality_gate(rec_cfg),
        "llm_copywriting": load_llm_copy_settings(rec_cfg),
        "semantic_rerank": load_semantic_rerank_settings(rec_cfg),
        "lexicon": load_lexicon(rec_cfg),
        "rec_cfg": rec_cfg,
    }
