"""
RecommendationAgent 主类编排：run / validate_input / process。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from .constants import AGENT_NAME, WEIGHT_KEYS
from .constraints import (
    apply_quality_gate,
    check_hard_constraints,
    check_preference_filters,
    extract_deadline,
)
from .copywriting import (
    apply_level_cap,
    build_action,
    build_reason,
    build_risk,
    to_level,
)
from .diversity import (
    annotate_prestige_and_category,
    force_fill_recommendations,
    infer_prestige,
    select_diverse_top_n,
    sort_scored,
)
from .llm_copy import polish_recommendations
from .responses import error_response, partial_response, success_response
from .scoring import score_all_dimensions
from .semantic_rerank import apply_semantic_rerank
from .synonyms import user_ability_corpus
from .utils import load_config
from .validate import validate_input as validate_input_payload
from .weights import load_recommendation_settings, resolve_weights


class RecommendationAgent:
    """推荐匹配 Agent（ReAgent_New）。

    Step 1–4：配置 / 校验 / 六维打分 / 多样性与层级
    Step 5：外置词典 + 连续兴趣/能力分
    Step 6：matched/unmatched signals + 个性化解释
    Step 7：filtered_out + 偏好过滤 + 质量门槛
    """

    AGENT_NAME = AGENT_NAME

    def __init__(self, config: Optional[dict] = None):
        """初始化 Agent，加载 config.yaml 的 recommendation 段。"""
        if config is None:
            config = load_config()
        if not isinstance(config, dict):
            config = {}

        self.config = config
        settings = load_recommendation_settings(self.config)

        self.weights = settings["weights"]
        self.level_thresholds = settings["level_thresholds"]
        self.level_caps = settings["level_caps"]
        self.hard_constraints_enabled = settings["hard_constraints_enabled"]
        self.hard_major_min_score = settings["hard_major_min_score"]
        self.diversity_settings = settings["diversity"]
        self.prestige_settings = settings["prestige"]
        self.quality_gate = settings["quality_gate"]
        self.llm_copywriting = settings["llm_copywriting"]
        self.semantic_rerank = settings["semantic_rerank"]
        self.rec_cfg = settings["rec_cfg"]

        lexicon = settings["lexicon"]
        self.synonym_groups = lexicon["synonym_groups"]
        self.major_groups = lexicon["major_groups"]
        self.skill_normalize = lexicon["skill_normalize"]

    @staticmethod
    def _resolve_top_n(rules: dict, rec_cfg: Optional[dict] = None) -> int:
        """解析返回条数：rules.top_n > config.top_n > 默认 3。"""
        candidates = []
        if isinstance(rules, dict) and rules.get("top_n") is not None:
            candidates.append(rules.get("top_n"))
        cfg = rec_cfg if isinstance(rec_cfg, dict) else {}
        if cfg.get("top_n") is not None:
            candidates.append(cfg.get("top_n"))
        candidates.append(3)
        for raw in candidates:
            try:
                return max(1, int(raw))
            except (TypeError, ValueError):
                continue
        return 3

    @staticmethod
    def _resolve_pool_size(
        rules: dict, rec_cfg: Optional[dict] = None, top_n: int = 3
    ) -> int:
        """解析缓存池大小：至少覆盖 top_n，供后续「多推荐几条」复用，避免重跑打分。

        优先级：rules.pool_size > config.recommendation_pool_size > 默认 10。
        """
        top_n = max(1, int(top_n))
        candidates = []
        if isinstance(rules, dict) and rules.get("pool_size") is not None:
            candidates.append(rules.get("pool_size"))
        cfg = rec_cfg if isinstance(rec_cfg, dict) else {}
        if cfg.get("recommendation_pool_size") is not None:
            candidates.append(cfg.get("recommendation_pool_size"))
        candidates.append(10)
        for raw in candidates:
            try:
                return max(top_n, int(raw))
            except (TypeError, ValueError):
                continue
        return max(top_n, 10)

    # ------------------------------------------------------------------
    # 统一外部接口
    # ------------------------------------------------------------------

    def run(self, input_data: dict) -> dict:
        """推荐匹配统一入口。"""
        validation_error = self.validate_input(input_data)
        if validation_error:
            return validation_error

        try:
            return self.process(input_data)
        except Exception as exc:
            return error_response(
                input_data.get("task_id", "") if isinstance(input_data, dict) else "",
                error_type=type(exc).__name__,
                error_message=str(exc),
                suggestion="请检查输入数据格式是否正确，或联系开发者排查。",
            )

    def validate_input(self, input_data: dict):
        """校验输入；失败返回标准响应 dict，通过返回 None。"""
        return validate_input_payload(input_data)

    # ------------------------------------------------------------------
    # 核心推荐逻辑
    # ------------------------------------------------------------------

    def process(self, input_data: dict) -> dict:
        """执行推荐匹配（含词典、信号、过滤原因、偏好与质量门槛）。"""
        task_id = input_data.get("task_id", "")
        if "input_data" in input_data and isinstance(input_data.get("input_data"), dict):
            business = input_data["input_data"]
        else:
            business = input_data

        structured_items = business.get("structured_items", [])
        user_profile = (
            input_data.get("user_profile") or business.get("user_profile", {})
        )

        rules = business.get("recommendation_rules", {})
        if not isinstance(rules, dict):
            rules = {}
        top_n = self._resolve_top_n(rules, self.rec_cfg)
        selection_n = self._resolve_pool_size(rules, self.rec_cfg, top_n)

        weights = resolve_weights(self.weights, rules)
        caps = {
            **self.level_caps,
            **(rules.get("caps") if isinstance(rules.get("caps"), dict) else {}),
        }
        prefs = rules.get("prefs") if isinstance(rules.get("prefs"), dict) else {}

        diversity_settings = dict(self.diversity_settings)
        if isinstance(rules.get("diversity"), dict):
            diversity_settings.update(rules["diversity"])
        prestige_settings = {
            "enabled": self.prestige_settings.get("enabled", True),
            "mode": self.prestige_settings.get("mode", "soft_add"),
            "boost": dict(self.prestige_settings.get("boost") or {}),
        }
        if isinstance(rules.get("prestige"), dict):
            p = rules["prestige"]
            if "enabled" in p:
                prestige_settings["enabled"] = bool(p["enabled"])
            if p.get("mode") in ("soft_add", "tie_break"):
                prestige_settings["mode"] = p["mode"]
            if isinstance(p.get("boost"), dict):
                prestige_settings["boost"].update(p["boost"])

        quality_gate = dict(self.quality_gate)
        if isinstance(rules.get("quality_gate"), dict):
            quality_gate.update(rules["quality_gate"])

        llm_copy_settings = dict(self.llm_copywriting)
        if isinstance(rules.get("llm_copywriting"), dict):
            llm_copy_settings.update(rules["llm_copywriting"])

        semantic_settings = dict(self.semantic_rerank)
        if isinstance(rules.get("semantic_rerank"), dict):
            semantic_settings.update(rules["semantic_rerank"])

        scored = []
        filtered_out = []
        hard_filtered = 0
        now = date.today()
        ability_corpus = user_ability_corpus(user_profile)

        for item in structured_items:
            if not isinstance(item, dict):
                hard_filtered += 1
                filtered_out.append({
                    "title": str(item)[:40] if item is not None else "无效条目",
                    "reason": "项目数据不是 dict",
                })
                continue

            title = item.get("title", "未知项目")
            deadline = extract_deadline(item)

            if self.hard_constraints_enabled:
                ok, reason = check_hard_constraints(
                    user_profile,
                    item,
                    deadline,
                    now,
                    hard_major_min_score=self.hard_major_min_score,
                    major_groups=self.major_groups,
                )
                if not ok:
                    hard_filtered += 1
                    filtered_out.append({"title": title, "reason": reason})
                    continue

            # 偏好过滤（在打分前，节省计算；层级用推断）
            tier = infer_prestige(item)
            ok_pref, pref_reason = check_preference_filters(item, prefs, tier)
            if not ok_pref:
                hard_filtered += 1
                filtered_out.append({"title": title, "reason": pref_reason})
                continue

            scores, matched, unmatched = score_all_dimensions(
                user_profile,
                item,
                deadline,
                now,
                ability_corpus=ability_corpus,
                synonym_groups=self.synonym_groups,
                major_groups=self.major_groups,
                skill_normalize=self.skill_normalize,
            )
            total = round(
                sum(scores[k] * weights.get(k, 0.0) for k in WEIGHT_KEYS),
                1,
            )
            scored.append({
                "item": item,
                "total": total,
                "scores": scores,
                "matched_signals": matched,
                "unmatched_signals": unmatched,
            })

        scored = annotate_prestige_and_category(scored, prestige_settings)
        scored = sort_scored(scored, prestige_settings)
        # DeepSeek 精排兴趣/能力（失败自动回退关键词分）
        scored, semantic_meta = apply_semantic_rerank(
            scored,
            user_profile,
            weights,
            config=self.config,
            settings=semantic_settings,
        )
        if semantic_meta.get("used"):
            scored = annotate_prestige_and_category(scored, prestige_settings)
            scored = sort_scored(scored, prestige_settings)
        selected = select_diverse_top_n(scored, selection_n, diversity_settings)

        recommendations = []
        for entry in selected:
            item = entry["item"]
            total = entry["total"]
            detail = entry["scores"]
            matched = entry.get("matched_signals") or []
            unmatched = entry.get("unmatched_signals") or []

            level_code, _ = to_level(total, self.level_thresholds)
            level_code = apply_level_cap(level_code, detail, caps)
            recommendations.append({
                "title": item.get("title", "未知项目"),
                "match_score": total,
                "recommend_level": level_code,
                "reason": build_reason(
                    detail,
                    user=user_profile,
                    item=item,
                    matched_signals=matched,
                    unmatched_signals=unmatched,
                ),
                "risk": build_risk(detail, unmatched_signals=unmatched),
                "suggested_action": build_action(level_code, detail),
                "detail": detail,
                "matched_signals": matched,
                "unmatched_signals": unmatched,
                "category_key": entry.get("category_key", ""),
                "prestige_tier": entry.get("prestige_tier", "unknown"),
                "is_backup": False,
                "source_url": item.get("source_url", ""),
                "summary": item.get("summary", ""),
                "deadline": item.get("deadline", ""),
                "organizer": item.get("organizer", ""),
                "type": item.get("type", ""),
            })

        recommendations = apply_quality_gate(recommendations, quality_gate)
        # 质量门槛去掉备选后，再按分类去重（可少于 selection_n）
        max_per = 1
        try:
            max_per = max(1, int(diversity_settings.get("max_per_category", 1)))
        except (TypeError, ValueError):
            max_per = 1
        if diversity_settings.get("enabled", True):
            deduped = []
            cat_counts = {}
            for rec in recommendations:
                key = rec.get("category_key") or "other"
                if cat_counts.get(key, 0) >= max_per:
                    continue
                deduped.append(rec)
                cat_counts[key] = cat_counts.get(key, 0) + 1
                if len(deduped) >= selection_n:
                    break
            recommendations = deduped
        else:
            recommendations = recommendations[:selection_n]

        # 最高优先级：最终强制凑满 selection_n（可含备选 / 同类）
        force_top_n = True
        if isinstance(rules.get("force_top_n"), bool):
            force_top_n = rules["force_top_n"]
        elif isinstance(self.rec_cfg.get("force_top_n"), bool):
            force_top_n = self.rec_cfg["force_top_n"]

        def _build_rec(entry: dict) -> dict:
            item = entry["item"]
            total = entry["total"]
            detail = entry["scores"]
            matched = entry.get("matched_signals") or []
            unmatched = entry.get("unmatched_signals") or []
            level_code, _ = to_level(total, self.level_thresholds)
            level_code = apply_level_cap(level_code, detail, caps)
            return {
                "title": item.get("title", "未知项目"),
                "match_score": total,
                "recommend_level": level_code,
                "reason": build_reason(
                    detail,
                    user=user_profile,
                    item=item,
                    matched_signals=matched,
                    unmatched_signals=unmatched,
                ),
                "risk": build_risk(detail, unmatched_signals=unmatched),
                "suggested_action": build_action(level_code, detail, is_backup=True),
                "detail": detail,
                "matched_signals": matched,
                "unmatched_signals": unmatched,
                "category_key": entry.get("category_key", ""),
                "prestige_tier": entry.get("prestige_tier", "unknown"),
                "is_backup": True,
                "source_url": item.get("source_url", ""),
                "summary": item.get("summary", ""),
                "deadline": item.get("deadline", ""),
                "organizer": item.get("organizer", ""),
                "type": item.get("type", ""),
            }

        if force_top_n:
            recommendations = force_fill_recommendations(
                recommendations, scored, selection_n, _build_rec
            )
        else:
            recommendations = recommendations[:selection_n]

        for idx, rec in enumerate(recommendations, 1):
            rec["rank"] = idx
            rec["id"] = f"rec_{idx}"
            # 备选时刷新 action 文案
            if rec.get("is_backup"):
                rec["suggested_action"] = build_action(
                    rec["recommend_level"], rec["detail"], is_backup=True
                )

        # Top-N 文案润色（失败自动回退规则文案；不改排序）
        recommendations = polish_recommendations(
            recommendations,
            user_profile,
            config=self.config,
            llm_copy_settings=llm_copy_settings,
        )

        # 缓存完整候选池；对外只返回当前 top_n，扩容时直接切片复用
        recommendation_pool = recommendations
        recommendations = recommendation_pool[:top_n]

        data = {
            "recommendations": recommendations,
            "recommendation_pool": recommendation_pool,
            "filtered_out": filtered_out,
            "total_count": len(structured_items),
            "matched_count": len(scored),
            "hard_filtered_count": hard_filtered,
        }
        llm_used = any(r.get("copy_source") == "llm" for r in recommendations)
        message = (
            f"推荐完成：共 {len(structured_items)} 个候选，"
            f"硬性不符合 {hard_filtered} 个，"
            f"有效匹配 {len(scored)} 个，返回 Top-{len(recommendations)}。"
        )
        if semantic_meta.get("used"):
            message += "（兴趣/能力已由 DeepSeek 精排）"
        if llm_used:
            message += "（推荐理由已由大模型润色）"

        if not recommendations:
            message = (
                f"无可用推荐：共 {len(structured_items)} 个候选，"
                f"硬性不符合 {hard_filtered} 个。"
            )
            return partial_response(task_id, data=data, message=message)

        resp = success_response(task_id, data=data, message=message)
        resp["metadata"] = {
            "copy_source": "llm" if llm_used else "rule",
            "llm_copywriting_enabled": bool(llm_copy_settings.get("enabled", True)),
            "semantic_rerank_used": bool(semantic_meta.get("used")),
            "semantic_rerank": {
                "pool_size": semantic_meta.get("pool_size"),
                "blend": semantic_meta.get("blend"),
                "error": semantic_meta.get("error"),
            },
        }
        return resp
