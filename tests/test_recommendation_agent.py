"""ReAgent_New RecommendationAgent 测试（Step 8）。

运行方式（在项目根目录）:
    python -m tests.test_recommendation_agent
    或
    python tests/test_recommendation_agent.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.ReAgent_New import (  # noqa: E402
    ALLOWED_STATUS,
    RECOMMENDATION_REQUIRED_KEYS,
    RESPONSE_KEYS,
    RecommendationAgent,
)
from agents.ReAgent_New.utils import (  # noqa: E402
    build_sample_input,
    enrollment_to_grade,
    load_config,
)
from agents.ReAgent_New.weights import normalize_weights  # noqa: E402
from agents.main_agent import MainAgent  # noqa: E402


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _agent(config: dict | None = None) -> RecommendationAgent:
    """单测默认关闭 LLM 润色/精排，避免外网依赖与不稳定耗时。"""
    cfg = dict(config or load_config())
    rec = dict(cfg.get("recommendation") or {})
    copy_cfg = dict(rec.get("llm_copywriting") or {})
    copy_cfg["enabled"] = False
    rec["llm_copywriting"] = copy_cfg
    rerank_cfg = dict(rec.get("semantic_rerank") or {})
    rerank_cfg["enabled"] = False
    rec["semantic_rerank"] = rerank_cfg
    cfg["recommendation"] = rec
    return RecommendationAgent(cfg)


def _base_input(**overrides) -> dict:
    payload = {
        "task_id": "task_unit_001",
        "user_input": "帮我推荐竞赛",
        "task_type": "recommendation",
        "user_profile": {
            "major": "计算机科学与技术",
            "enrollment_year": 2024,
            "education_level": "本科",
            "skills": ["Python"],
            "interests": ["人工智能"],
            "competition_experience": ["全国大学生数学建模 省一等奖"],
            "available_time": "2026年7月-9月",
            "team_status": "寻找队友",
        },
        "context": {},
        "input_data": {
            "structured_items": [
                {
                    "title": "组队数学建模赛",
                    "deadline": "2026-08-20",
                    "requirements": {
                        "target_majors": [],
                        "target_grades": [],
                        "target_education": ["本科"],
                        "required_skills": ["数学建模"],
                        "team_requirement": "组队",
                        "tags": ["数学建模"],
                        "category": "数学建模",
                    },
                }
            ],
            "recommendation_rules": {"top_n": 3},
        },
        "history": [],
        "required_output": "markdown",
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def test_output_schema_and_sample() -> None:
    config = load_config()
    agent = _agent(config)
    sample = build_sample_input(
        config,
        str(ROOT / "tests" / "fixtures" / "recommendation_input_sample.json"),
    )

    result = agent.run(sample)

    missing = RESPONSE_KEYS - set(result.keys())
    _assert(not missing, f"输出缺少统一字段: {missing}")
    _assert(result["agent_name"] == "recommendation_agent", "agent_name 不正确")
    _assert(result["status"] in ALLOWED_STATUS, f"非法 status: {result['status']}")
    _assert(result["task_id"] == sample.get("task_id", ""), "task_id 未与输入保持一致")
    _assert(isinstance(result["data"], dict), "data 必须是 dict")
    _assert(
        result["status"] == "success",
        f"样例应成功，实际: {result['status']} / {result.get('error')}",
    )

    recommendations = result["data"].get("recommendations", [])
    _assert(isinstance(recommendations, list), "recommendations 必须是 list")
    _assert(
        1 <= len(recommendations) <= 3,
        f"默认 Top3，实际条数: {len(recommendations)}",
    )
    _assert("filtered_out" in result["data"], "应返回 filtered_out")

    for item in recommendations:
        missing_item = RECOMMENDATION_REQUIRED_KEYS - set(item.keys())
        _assert(not missing_item, f"推荐项缺少字段: {missing_item}")
        _assert(item["reason"], "reason 不应为空字符串")
        _assert("matched_signals" in item, "应含 matched_signals")
        _assert("rank" in item and "id" in item, "应含 rank/id")


def test_need_input_when_profile_missing() -> None:
    agent = _agent()
    result = agent.run(
        {
            "task_id": "task_need_input_001",
            "user_input": "帮我推荐竞赛",
            "task_type": "recommendation",
            "user_profile": {},
            "context": {},
            "input_data": {
                "structured_items": [
                    {
                        "title": "示例竞赛",
                        "deadline": "2099-12-31",
                        "requirements": {},
                    }
                ],
            },
            "history": [],
            "required_output": "markdown",
            "metadata": {},
        }
    )
    _assert(
        result["status"] == "need_input",
        f"缺少画像时应 need_input，实际: {result['status']}",
    )
    _assert(result["next_action"] == "ask_user", "need_input 时应建议 ask_user")
    _assert(result["error"] is None, "need_input 时 error 应为 null")


def test_failed_when_items_type_invalid() -> None:
    agent = _agent()
    result = agent.run(
        {
            "task_id": "task_failed_001",
            "user_input": "",
            "task_type": "recommendation",
            "user_profile": {"major": "计算机科学与技术", "enrollment_year": 2024},
            "context": {},
            "input_data": {"structured_items": "not-a-list"},
            "history": [],
            "required_output": "markdown",
            "metadata": {},
        }
    )
    _assert(
        result["status"] == "failed",
        f"非法 structured_items 应 failed，实际: {result['status']}",
    )
    _assert(isinstance(result["error"], dict), "failed 时 error 应为 dict")
    for key in ("error_type", "error_message", "suggestion"):
        _assert(key in result["error"], f"error 缺少字段: {key}")


def test_hard_filter_expired_deadline() -> None:
    agent = _agent()
    payload = _base_input()
    payload["input_data"]["structured_items"] = [
        {
            "title": "已过期竞赛",
            "deadline": "2020-01-01",
            "requirements": {
                "target_education": ["本科"],
                "tags": ["数学建模"],
                "category": "数学建模",
                "team_requirement": "不限",
            },
        },
        {
            "title": "有效竞赛",
            "deadline": "2026-09-01",
            "requirements": {
                "target_education": ["本科"],
                "tags": ["数学建模"],
                "category": "数学建模",
                "team_requirement": "组队",
                "required_skills": ["数学建模"],
            },
        },
    ]
    result = agent.run(payload)
    _assert(result["status"] == "success", f"应成功，实际: {result['status']}")
    titles = [r["title"] for r in result["data"]["recommendations"]]
    _assert("已过期竞赛" not in titles, "过期赛不应进入推荐")
    filtered = result["data"]["filtered_out"]
    _assert(any("截止" in f.get("reason", "") for f in filtered), filtered)
    _assert(result["data"]["hard_filtered_count"] >= 1, "应统计硬过滤数量")


def test_force_top_n_after_prefer_fewer() -> None:
    """prefer_fewer 砍掉 B/C 后，force_top_n 仍应补回至 3（标 is_backup）。"""
    agent = _agent(
        {
            "recommendation": {
                "diversity": {"enabled": False},
                "prestige": {"enabled": False},
                "llm_copywriting": {"enabled": False},
                "force_top_n": True,
                "quality_gate": {
                    "enabled": True,
                    "min_primary_level": "A",
                    "prefer_fewer": True,
                    "allow_backup": True,
                },
                "level_thresholds": {"S": 80, "A": 65, "B": 50, "C": 0},
                "weights": {
                    "interest_score": 1,
                    "ability_score": 0,
                    "deadline_score": 0,
                    "team_score": 0,
                    "grade_score": 0,
                    "major_score": 0,
                },
            }
        }
    )
    payload = _base_input()
    payload["user_profile"]["interests"] = ["人工智能"]
    payload["input_data"]["recommendation_rules"] = {
        "top_n": 3,
        "force_top_n": True,
        "diversity": {"enabled": False},
        "quality_gate": {
            "enabled": True,
            "min_primary_level": "A",
            "prefer_fewer": True,
        },
    }
    # 一条强兴趣命中（偏 A），两条弱相关（偏 B/C）
    payload["input_data"]["structured_items"] = [
        {
            "title": "强匹配人工智能赛",
            "deadline": "2026-09-01",
            "requirements": {
                "tags": ["人工智能"],
                "category": "人工智能",
                "team_requirement": "不限",
                "target_education": ["本科"],
            },
        },
        {
            "title": "弱相关英语赛",
            "deadline": "2026-09-10",
            "requirements": {
                "tags": ["英语"],
                "category": "英语",
                "team_requirement": "不限",
                "target_education": ["本科"],
            },
        },
        {
            "title": "弱相关创业赛",
            "deadline": "2026-09-15",
            "requirements": {
                "tags": ["创新创业"],
                "category": "创新创业",
                "team_requirement": "不限",
                "target_education": ["本科"],
            },
        },
    ]
    result = agent.run(payload)
    _assert(result["status"] == "success", f"应成功: {result.get('status')}")
    recs = result["data"]["recommendations"]
    _assert(len(recs) == 3, f"强制 Top3，实际 {len(recs)}: {[r['title'] for r in recs]}")
    _assert(recs[0]["title"] == "强匹配人工智能赛", recs[0]["title"])
    _assert(
        any(r.get("is_backup") for r in recs[1:]),
        "补齐项应标 is_backup",
    )


def test_diversity_not_all_same_category() -> None:
    agent = _agent(
        {
            "recommendation": {
                "diversity": {"enabled": True, "max_per_category": 1},
                "quality_gate": {"enabled": False},
                "prestige": {"enabled": False},
                "llm_copywriting": {"enabled": False},
            }
        }
    )
    payload = _base_input()
    payload["user_profile"]["interests"] = ["数学建模", "算法竞赛", "英语"]
    payload["input_data"]["recommendation_rules"] = {
        "top_n": 3,
        "diversity": {"enabled": True, "max_per_category": 1},
        "quality_gate": {"enabled": False},
    }
    payload["input_data"]["structured_items"] = [
        {
            "title": f"数模赛{i}",
            "deadline": "2026-09-01",
            "requirements": {
                "tags": ["数学建模"],
                "category": "数学建模",
                "team_requirement": "组队",
                "target_education": ["本科"],
            },
        }
        for i in range(3)
    ] + [
        {
            "title": "算法编程赛",
            "deadline": "2026-09-10",
            "requirements": {
                "tags": ["算法编程"],
                "category": "计算机",
                "team_requirement": "组队",
                "target_education": ["本科"],
            },
        },
        {
            "title": "英语阅读赛",
            "deadline": "2026-09-15",
            "requirements": {
                "tags": ["英语"],
                "category": "英语",
                "team_requirement": "单人",
                "target_education": ["本科"],
            },
        },
    ]
    result = agent.run(payload)
    recs = result["data"]["recommendations"]
    keys = [r.get("category_key") for r in recs]
    _assert(len(recs) >= 2, f"应至少返回 2 条，实际 {len(recs)}")
    _assert(len(set(keys)) >= 2, f"Top-N 不应全是同一分类: {keys}")


def test_looking_for_teammate_matches_team_contest() -> None:
    agent = _agent()
    result = agent.run(_base_input())
    _assert(result["status"] == "success", f"应成功，实际: {result['status']}")
    detail = result["data"]["recommendations"][0]["detail"]
    _assert(
        detail["team_score"] >= 85,
        f"寻找队友+组队应高分，实际 {detail['team_score']}",
    )
    _assert(
        detail["ability_score"] >= 45,
        f"有数学建模经历应提升能力分，实际 {detail['ability_score']}",
    )


def test_ai_interest_not_auto_match_all_cs_tags() -> None:
    agent = _agent(
        {
            "recommendation": {
                "quality_gate": {"enabled": False},
                "prestige": {"enabled": False},
                "llm_copywriting": {"enabled": False},
            }
        }
    )
    payload = _base_input()
    payload["user_profile"]["interests"] = ["人工智能"]
    payload["user_profile"]["competition_experience"] = []
    payload["input_data"]["structured_items"] = [
        {
            "title": "纯计算机素养赛",
            "deadline": "2026-08-20",
            "requirements": {
                "required_skills": [],
                "team_requirement": "不限",
                "tags": ["计算机", "计算机能力"],
                "category": "计算机",
            },
        }
    ]
    result = agent.run(payload)
    interest = result["data"]["recommendations"][0]["detail"]["interest_score"]
    _assert(
        interest < 70,
        f"AI 兴趣不应因「计算机」同义词拿高分，实际 {interest}",
    )


def test_enrollment_grade_around_september() -> None:
    _assert(enrollment_to_grade(2024, date(2026, 7, 20)) == "大二", "2026-07 应为大二")
    _assert(enrollment_to_grade(2024, date(2026, 10, 1)) == "大三", "2026-10 应为大三")
    _assert(enrollment_to_grade(2024, date(2025, 8, 31)) == "大一", "2025-08 仍为大一")


def test_semantic_rerank_disabled_passthrough() -> None:
    from agents.ReAgent_New.semantic_rerank import apply_semantic_rerank

    scored = [
        {
            "item": {"title": "A"},
            "total": 80.0,
            "scores": {"interest_score": 70.0, "ability_score": 60.0},
            "matched_signals": [],
            "unmatched_signals": [],
        }
    ]
    out, meta = apply_semantic_rerank(
        scored,
        {"major": "CS"},
        {"interest_score": 0.5, "ability_score": 0.5},
        settings={"enabled": False},
    )
    _assert(out is scored or out == scored, "关闭精排时应原样返回")
    _assert(meta.get("used") is False, "关闭时不应标记 used")


def test_semantic_rerank_blend_with_mock() -> None:
    from agents.ReAgent_New import semantic_rerank as sr

    scored = [
        {
            "item": {"title": "算法竞赛", "requirements": {"tags": ["编程"]}},
            "total": 50.0,
            "scores": {
                "interest_score": 40.0,
                "ability_score": 50.0,
                "timeline_score": 0,
                "prestige_score": 0,
                "freshness_score": 0,
            },
            "matched_signals": [],
            "unmatched_signals": [],
        }
    ]
    weights = {k: 0.2 for k in ("interest_score", "ability_score", "timeline_score", "prestige_score", "freshness_score")}

    original_creds = sr._resolve_llm_credentials
    original_call = sr._call_chat_completions
    sr._resolve_llm_credentials = lambda _cfg: {
        "enabled": True,
        "api_key": "x",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "timeout": 30,
    }
    sr._call_chat_completions = lambda **_kw: {
        "ok": True,
        "content": '{"items":[{"id":0,"interest_score":100,"ability_score":80,"matched":["编程"],"unmatched":[]}]}',
    }
    try:
        out, meta = sr.apply_semantic_rerank(
            scored,
            {"major": "计算机", "skills": ["Python"], "interests": ["算法"]},
            weights,
            settings={"enabled": True, "blend": 0.7, "pool_size": 8},
        )
    finally:
        sr._resolve_llm_credentials = original_creds
        sr._call_chat_completions = original_call

    _assert(meta.get("used") is True, "mock 成功时应 used")
    scores = out[0]["scores"]
    # blend 0.7: interest = 0.7*100 + 0.3*40 = 82
    _assert(abs(scores["interest_score"] - 82.0) < 0.2, f"interest blend 异常: {scores}")
    _assert(scores.get("interest_score_llm") == 100.0, "应保留 LLM 分")
    _assert(out[0].get("semantic_reranked") is True, "应标记 semantic_reranked")


def test_weights_normalized() -> None:
    agent = _agent(
        {
            "recommendation": {
                "weights": {
                    "interest_score": 2,
                    "ability_score": 2,
                    "deadline_score": 2,
                    "team_score": 2,
                    "grade_score": 1,
                    "major_score": 1,
                },
                "llm_copywriting": {"enabled": False},
            }
        }
    )
    total = sum(agent.weights.values())
    _assert(abs(total - 1.0) < 1e-9, f"权重应归一化为 1，实际 {total}")

    raw = normalize_weights(
        {
            "interest_score": -1,
            "ability_score": 0,
            "deadline_score": 0,
            "team_score": 0,
            "grade_score": 0,
            "major_score": 0,
        }
    )
    _assert(abs(sum(raw.values()) - 1.0) < 1e-9, "非法权重应回退并可归一化")


def test_prefs_exclude_tags() -> None:
    agent = _agent()
    payload = _base_input()
    payload["user_profile"]["interests"] = ["数学建模", "英语"]
    payload["input_data"]["recommendation_rules"] = {
        "top_n": 3,
        "prefs": {"exclude_tags": ["英语"]},
        "quality_gate": {"enabled": False},
    }
    payload["input_data"]["structured_items"] = [
        {
            "title": "数学建模全国赛",
            "deadline": "2026-09-01",
            "requirements": {
                "tags": ["数学建模"],
                "category": "数学建模",
                "team_requirement": "组队",
                "target_education": ["本科"],
            },
        },
        {
            "title": "全国英语阅读大赛",
            "deadline": "2026-09-01",
            "requirements": {
                "tags": ["英语"],
                "category": "英语",
                "team_requirement": "单人",
                "target_education": ["本科"],
            },
        },
    ]
    result = agent.run(payload)
    titles = " ".join(r["title"] for r in result["data"]["recommendations"])
    _assert("英语" not in titles, f"应排除英语赛，实际: {titles}")
    _assert(
        any("排除" in f.get("reason", "") for f in result["data"]["filtered_out"]),
        "filtered_out 应记录偏好过滤原因",
    )


def test_eval_cases_hit_and_avoid() -> None:
    """小标注集：期望命中 / 不应出现。"""
    cases_path = ROOT / "tests" / "fixtures" / "rec_eval_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    agent = _agent()

    for case in cases:
        # 标注集也不走 LLM，保证确定性
        case_input = case["input"]
        rules = dict(case_input.get("input_data", {}).get("recommendation_rules") or {})
        rules["llm_copywriting"] = {"enabled": False}
        rules["semantic_rerank"] = {"enabled": False}
        case_input.setdefault("input_data", {})["recommendation_rules"] = rules
        result = agent.run(case_input)
        titles = [r["title"] for r in result["data"].get("recommendations", [])]
        for expected in case.get("expect_in_top", []):
            _assert(
                any(expected in t for t in titles),
                f"[{case['id']}] 期望命中「{expected}」，实际 Top: {titles}",
            )
        for banned in case.get("expect_not_in_top", []):
            _assert(
                all(banned not in t for t in titles),
                f"[{case['id']}] 不应出现「{banned}」，实际 Top: {titles}",
            )


def test_main_agent_uses_extract_result() -> None:
    main_agent = MainAgent(config={})
    items = _base_input()["input_data"]["structured_items"]
    adapted = main_agent._adapt_recommendation_input(
        _base_input(input_data={}),
        {"info_extract_result": {"structured_items": items}},
    )
    _assert(adapted["structured_items"] == items, "未传递抽取结果")


def test_main_agent_runs_structured_recommendation() -> None:
    cfg = load_config()
    rec = dict(cfg.get("recommendation") or {})
    rec["llm_copywriting"] = {"enabled": False}
    rec["semantic_rerank"] = {"enabled": False}
    cfg["recommendation"] = rec
    main_agent = MainAgent(config=cfg)
    result = main_agent.run(_base_input())

    _assert(result["status"] == "success", f"MainAgent 推荐失败: {result}")
    agent_results = result["data"]["agent_results"]
    _assert(len(agent_results) == 1, "已有结构化数据时应只调用推荐 Agent")
    _assert(agent_results[0]["agent_name"] == "recommendation_agent", "调度错误")
    _assert(agent_results[0]["status"] == "success", "推荐 Agent 执行失败")
    # 确认推荐入口已转发到 ReAgent_New（main_agent 路径不变）
    from agents.recommendation_agent import RecommendationAgent as EntryAgent
    from agents.ReAgent_New import RecommendationAgent as NewAgent

    _assert(
        EntryAgent is NewAgent,
        "agents.recommendation_agent 应转发至 ReAgent_New.RecommendationAgent",
    )
    _assert(
        main_agent.sub_agent_specs["recommendation"][0]
        == "agents.recommendation_agent",
        f"MainAgent 调度路径应保持不变: {main_agent.sub_agent_specs['recommendation']}",
    )


def test_raw_recommendation_schedule_includes_extraction() -> None:
    main_agent = MainAgent(config={})
    request = _base_input(input_data={"data_source": "web"})
    selected = main_agent.select_agents(request)
    _assert(
        selected == ["info_collect", "info_extract", "recommendation"],
        f"原始数据推荐调度顺序错误: {selected}",
    )


def _previous_recommendation_result() -> dict:
    return {
        "task_id": "followup-test",
        "data": {
            "agent_results": [
                {
                    "data": {
                        "recommendations": [
                            {
                                "title": "华青杯大学生人工智能大赛",
                                "summary": "面向大学生的人工智能实践竞赛。",
                                "organizer": "华青杯组委会",
                                "deadline": "2026-09-30",
                                "reason": "方向与人工智能兴趣匹配。",
                                "source_url": "https://example.com/huaqing",
                            },
                            {
                                "title": "大学生算法挑战赛",
                                "summary": "考察算法设计与编程能力。",
                                "source_url": "https://example.com/algorithm",
                            },
                        ]
                    }
                }
            ]
        },
    }


def test_main_agent_handles_named_detail_followup() -> None:
    import os

    os.environ.pop("DEEPSEEK_API_KEY", None)
    result = MainAgent(config={}).handle_followup(
        "我想详细了解华青杯", _previous_recommendation_result()
    )
    _assert(result is not None, "详情追问应由 MainAgent 处理")
    _assert(result["status"] == "success", f"详情追问失败: {result}")
    _assert(
        result["data"]["selected_competition"]["title"].startswith("华青杯"),
        "未按名称选中竞赛",
    )
    _assert(
        "https://example.com/huaqing" in result["data"]["final_answer"],
        "详情缺少原始网页",
    )
    _assert(
        result["metadata"]["generation_source"] == "fallback",
        "无密钥时应使用稳定回退",
    )


def test_main_agent_handles_ordinal_detail_followup() -> None:
    import os

    os.environ.pop("DEEPSEEK_API_KEY", None)
    result = MainAgent(config={}).handle_followup(
        "请详细介绍第二个", _previous_recommendation_result()
    )
    _assert(result is not None, "序号详情追问应由 MainAgent 处理")
    _assert(
        result["data"]["selected_competition"]["title"] == "大学生算法挑战赛",
        "未按序号选中竞赛",
    )


def test_main_agent_ignores_non_detail_followup() -> None:
    result = MainAgent(config={}).handle_followup(
        "我想参加国家级竞赛", _previous_recommendation_result()
    )
    _assert(result is None, "普通补充信息应继续进入正常推荐流程")


def main() -> int:
    tests = [
        test_output_schema_and_sample,
        test_need_input_when_profile_missing,
        test_failed_when_items_type_invalid,
        test_hard_filter_expired_deadline,
        test_force_top_n_after_prefer_fewer,
        test_diversity_not_all_same_category,
        test_looking_for_teammate_matches_team_contest,
        test_ai_interest_not_auto_match_all_cs_tags,
        test_enrollment_grade_around_september,
        test_semantic_rerank_disabled_passthrough,
        test_semantic_rerank_blend_with_mock,
        test_weights_normalized,
        test_prefs_exclude_tags,
        test_eval_cases_hit_and_avoid,
        test_main_agent_uses_extract_result,
        test_main_agent_runs_structured_recommendation,
        test_raw_recommendation_schedule_includes_extraction,
        test_main_agent_handles_named_detail_followup,
        test_main_agent_handles_ordinal_detail_followup,
        test_main_agent_ignores_non_detail_followup,
    ]
    passed = 0
    for fn in tests:
        fn()
        passed += 1
        print(f"[PASS] {fn.__name__}")

    print(f"\nAll {passed} tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
