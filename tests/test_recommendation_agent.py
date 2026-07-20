"""RecommendationAgent 简单独立测试（成员 C）。

运行方式（在项目根目录）:
    python -m tests.test_recommendation_agent
    或
    python tests/test_recommendation_agent.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.recommendation_agent import (  # noqa: E402
    RecommendationAgent,
    _enrollment_to_grade,
    _load_config,
    build_sample_input,
)
from agents.main_agent import MainAgent  # noqa: E402


REQUIRED_OUTPUT_KEYS = {
    "task_id",
    "agent_name",
    "status",
    "data",
    "message",
    "error",
    "next_action",
    "metadata",
}

ALLOWED_STATUS = {"success", "failed", "partial", "need_input", "skipped"}


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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


def test_output_schema_and_top3() -> None:
    config = _load_config()
    agent = RecommendationAgent(config)
    sample = build_sample_input(
        config,
        str(ROOT / "tests" / "fixtures" / "recommendation_input_sample.json"),
    )

    result = agent.run(sample)

    missing = REQUIRED_OUTPUT_KEYS - set(result.keys())
    _assert(not missing, f"输出缺少统一字段: {missing}")
    _assert(result["agent_name"] == "recommendation_agent", "agent_name 不正确")
    _assert(result["status"] in ALLOWED_STATUS, f"非法 status: {result['status']}")
    _assert(result["task_id"] == sample.get("task_id", ""), "task_id 未与输入保持一致")
    _assert(isinstance(result["data"], dict), "data 必须是 dict")
    _assert(result["status"] == "success", f"样例应成功，实际: {result['status']} / {result.get('error')}")

    recommendations = result["data"].get("recommendations", [])
    _assert(isinstance(recommendations, list), "recommendations 必须是 list")
    _assert(1 <= len(recommendations) <= 3, f"默认 Top3，实际条数: {len(recommendations)}")

    for item in recommendations:
        for key in ("title", "match_score", "recommend_level", "reason", "risk", "suggested_action"):
            _assert(key in item, f"推荐项缺少字段: {key}")
        _assert(item["reason"], "reason 不应为空字符串")


def test_need_input_when_profile_missing() -> None:
    agent = RecommendationAgent(_load_config())
    result = agent.run(
        {
            "task_id": "task_need_input_001",
            "user_input": "帮我推荐竞赛",
            "task_type": "recommendation",
            "user_profile": {},
            "context": {},
            "input_data": {
                "structured_items": [{"title": "示例竞赛", "deadline": "2099-12-31", "requirements": {}}],
            },
            "history": [],
            "required_output": "markdown",
            "metadata": {},
        }
    )
    _assert(result["status"] == "need_input", f"缺少画像时应 need_input，实际: {result['status']}")
    _assert(result["next_action"] == "ask_user", "need_input 时应建议 ask_user")
    _assert(result["error"] is None, "need_input 时 error 应为 null")


def test_failed_when_items_type_invalid() -> None:
    agent = RecommendationAgent(_load_config())
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
    _assert(result["status"] == "failed", f"非法 structured_items 应 failed，实际: {result['status']}")
    _assert(isinstance(result["error"], dict), "failed 时 error 应为 dict")
    for key in ("error_type", "error_message", "suggestion"):
        _assert(key in result["error"], f"error 缺少字段: {key}")


def test_looking_for_teammate_matches_team_contest() -> None:
    agent = RecommendationAgent(_load_config())
    result = agent.run(_base_input())
    _assert(result["status"] == "success", f"应成功，实际: {result['status']}")
    detail = result["data"]["recommendations"][0]["detail"]
    _assert(detail["team_score"] >= 85, f"寻找队友+组队应高分，实际 {detail['team_score']}")
    _assert(detail["ability_score"] >= 45, f"有数学建模经历应提升能力分，实际 {detail['ability_score']}")


def test_ai_interest_not_auto_match_all_cs_tags() -> None:
    agent = RecommendationAgent(_load_config())
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
    _assert(interest < 70, f"AI 兴趣不应因「计算机」同义词拿高分，实际 {interest}")


def test_enrollment_grade_around_september() -> None:
    _assert(_enrollment_to_grade(2024, date(2026, 7, 20)) == "大二", "2026-07 应为大二")
    _assert(_enrollment_to_grade(2024, date(2026, 10, 1)) == "大三", "2026-10 应为大三")
    _assert(_enrollment_to_grade(2024, date(2025, 8, 31)) == "大一", "2025-08 仍为大一")


def test_weights_normalized() -> None:
    agent = RecommendationAgent({
        "recommendation": {
            "weights": {
                "interest_score": 2,
                "ability_score": 2,
                "deadline_score": 2,
                "team_score": 2,
                "grade_score": 1,
                "major_score": 1,
            }
        }
    })
    total = sum(agent.weights.values())
    _assert(abs(total - 1.0) < 1e-9, f"权重应归一化为 1，实际 {total}")


def test_main_agent_uses_extract_result() -> None:
    main_agent = MainAgent(config={})
    items = _base_input()["input_data"]["structured_items"]
    adapted = main_agent._adapt_recommendation_input(
        _base_input(input_data={}),
        {"info_extract_result": {"structured_items": items}},
    )
    _assert(adapted["structured_items"] == items, "未传递抽取结果")


def test_main_agent_runs_structured_recommendation() -> None:
    main_agent = MainAgent(config={})
    result = main_agent.run(_base_input())

    _assert(result["status"] == "success", f"MainAgent 推荐失败: {result}")
    agent_results = result["data"]["agent_results"]
    _assert(len(agent_results) == 1, "已有结构化数据时应只调用推荐 Agent")
    _assert(agent_results[0]["agent_name"] == "recommendation_agent", "调度错误")
    _assert(agent_results[0]["status"] == "success", "推荐 Agent 执行失败")


def test_raw_recommendation_schedule_includes_extraction() -> None:
    main_agent = MainAgent(config={})
    request = _base_input(input_data={"data_source": "web"})
    selected = main_agent.select_agents(request)
    _assert(
        selected == ["info_collect", "info_extract", "recommendation"],
        f"原始数据推荐调度顺序错误: {selected}",
    )


def main() -> int:
    tests = [
        test_output_schema_and_top3,
        test_need_input_when_profile_missing,
        test_failed_when_items_type_invalid,
        test_looking_for_teammate_matches_team_contest,
        test_ai_interest_not_auto_match_all_cs_tags,
        test_enrollment_grade_around_september,
        test_weights_normalized,
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
