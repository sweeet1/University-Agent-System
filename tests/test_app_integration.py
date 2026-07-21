from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app import (
    _chat_standard_input,
    _next_chat_question,
    _update_chat_state,
    build_academic_profile,
    build_standard_input,
    load_demo,
    new_chat_state,
    validate_form,
)
from agents.main_agent import MainAgent


def test_demo_supplies_a_runnable_pasted_notice_flow():
    demo = load_demo()

    assert demo[1] == "full_process"
    assert demo[2] == "upload"
    assert "挑战杯" in demo[8]
    assert demo[10] == "challenge_cup_grand_checklist"
    assert validate_form(
        demo[0], demo[1], demo[2], demo[7], demo[8], demo[9], demo[10]
    ) is None

    standard_input = build_standard_input(*demo)
    selected = MainAgent(config={})._select_full_process_agents(standard_input["input_data"])
    assert selected == ["info_extract", "recommendation", "material"]


def test_local_full_process_requires_project_data():
    error = validate_form(
        "推荐项目并生成材料", "full_process", "local", "", "", "", ""
    )

    assert error is not None
    assert "项目数据 JSON" in error


def test_ui_grade_is_mapped_to_recommendation_profile_contract():
    profile = build_academic_profile("大三", date(2026, 7, 20))

    assert profile == {
        "grade": "大三",
        "education_level": "本科",
        "enrollment_year": 2023,
    }


def test_project_json_accepts_one_object_and_normalizes_to_list():
    project = {"title": "挑战杯大学生课外学术科技作品竞赛", "deadline": "2026-09-30"}
    standard_input = build_standard_input(
        "推荐这个项目",
        "full_process",
        "local",
        "计算机科学与技术",
        "大三",
        "人工智能",
        "Python",
        "",
        "",
        json.dumps(project, ensure_ascii=False),
        "generic_schedule",
    )

    assert standard_input["input_data"]["projects"] == [project]
    selected = MainAgent(config={})._select_full_process_agents(standard_input["input_data"])
    assert selected == ["recommendation", "material"]


def test_invalid_project_json_is_rejected_before_dispatch():
    error = validate_form(
        "推荐项目", "recommendation", "local", "", "", "[{bad json]", ""
    )

    assert error is not None
    assert "JSON 格式不正确" in error


def test_explicit_ui_task_does_not_get_replaced_by_llm_plan(monkeypatch):
    demo = load_demo()
    standard_input = build_standard_input(*demo)
    agent = MainAgent(config={"llm": {"enabled": True}})

    def fail_if_called(_input):
        raise AssertionError("explicit UI task must use the input-aware rule plan")

    monkeypatch.setattr(agent, "_call_llm_planner", fail_if_called)
    plan = agent.plan_task(standard_input)

    assert plan["planning_source"] == "rule"
    assert plan["selected_agents"] == ["info_extract", "recommendation", "material"]


def test_pasted_notice_recommendation_skips_collection():
    standard_input = build_standard_input(*load_demo())
    standard_input["task_type"] = "recommendation"

    assert MainAgent(config={}).select_agents(standard_input) == [
        "info_extract", "recommendation"
    ]


def test_pasted_notice_material_runs_extraction_first():
    standard_input = build_standard_input(*load_demo())
    standard_input["task_type"] = "material"

    assert MainAgent(config={}).select_agents(standard_input) == [
        "info_extract", "material"
    ]


def test_demo_runs_through_extract_recommendation_and_material(tmp_path: Path):
    config = {
        "llm": {
            "enabled": False,
            "api_key_env": "APP_DEMO_TEST_NO_KEY",
        },
        "agent": {
            "info_extract": {"prompt_file": "./config/extraction_prompt.yaml"},
            "material_agent": {
                "prompt_config_path": "./config/material_prompts.yaml",
            },
        },
        "storage": {
            "output_path": str(tmp_path / "output"),
            "temp_path": str(tmp_path / "temp"),
        },
    }

    result = MainAgent(config=config).run(build_standard_input(*load_demo()))

    assert result["status"] == "success"
    assert result["metadata"]["selected_agents"] == [
        "info_extract", "recommendation", "material"
    ]
    assert [item["status"] for item in result["data"]["agent_results"]] == [
        "success", "success", "success"
    ]


def test_chat_collects_context_across_multiple_turns():
    state = _update_chat_state(new_chat_state(), "我是计算机专业大三学生，需要竞赛推荐")
    assert state["major"] == "计算机科学与技术"
    assert state["grade"] == "大三"
    assert _next_chat_question(state) == "你更想参加哪类竞赛？例如人工智能、算法、数学建模或创新创业。"

    state = _update_chat_state(state, "我更喜欢算法，也会Python")
    assert state["competition_type"] == "算法与程序设计"
    assert state["skills"] == ["Python"]
    assert _next_chat_question(state) == "你倾向校级、省级、国家级还是国际级竞赛？"

    state = _update_chat_state(state, "国家级")
    assert _next_chat_question(state) is None
    standard_input = _chat_standard_input(state, "国家级")
    assert standard_input["task_type"] == "recommendation"
    assert standard_input["user_profile"]["education_level"] == "本科"
    assert standard_input["input_data"]["keywords"] == ["算法与程序设计", "国家级"]


def test_chat_material_request_reuses_previous_recommendation():
    state = {
        **new_chat_state(),
        "major": "计算机科学与技术",
        "grade": "大三",
        "last_result": {
            "data": {
                "agent_results": [{
                    "data": {
                        "recommendations": [{
                            "title": "全国大学生人工智能竞赛",
                            "reason": "专业与技能匹配",
                        }]
                    }
                }]
            }
        },
    }
    state = _update_chat_state(state, "给刚才推荐的项目生成报名简历")

    assert state["intent"] == "material"
    assert state["material_type"] == "generic_personal_resume"
    assert _next_chat_question(state) is None
    standard_input = _chat_standard_input(state, "给刚才推荐的项目生成报名简历")
    assert standard_input["input_data"]["project_info"]["project_name"] == "全国大学生人工智能竞赛"


def test_chat_material_transition_requires_selection_when_multiple_recommendations():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "计算机科学与技术",
        "grade": "大三",
        "last_result": {
            "data": {"agent_results": [{"data": {"recommendations": [
                {"title": "人工智能创新赛", "summary": "AI 项目竞赛"},
                {"title": "算法程序设计赛", "summary": "算法个人赛", "deadline": "2026-09-30"},
            ]}}]}
        },
    }

    state = _update_chat_state(state, "我想要生成我自己的相关资料")
    assert state["intent"] == "material"
    assert state["project_name"] == ""
    assert "哪一个竞赛" in _next_chat_question(state)

    state = _update_chat_state(state, "第二个")
    assert state["project_name"] == "算法程序设计赛"
    assert "哪种材料" in _next_chat_question(state)

    state = _update_chat_state(state, "报名简历")
    assert _next_chat_question(state) is None
    assert state["material_type"] == "generic_personal_resume"
    standard_input = _chat_standard_input(state, "报名简历")
    assert standard_input["task_type"] == "material"
    assert standard_input["input_data"]["project_info"]["project_name"] == "算法程序设计赛"
    assert standard_input["input_data"]["competition_info"]["deadline"] == "2026-09-30"
    assert MainAgent(config={}).select_agents(standard_input) == ["material"]


def test_material_selection_ordinal_is_not_intercepted_as_detail_followup():
    state = {
        **new_chat_state(),
        "intent": "material",
        "major": "计算机科学与技术",
        "grade": "大三",
        "material_type": "generic_personal_resume",
        "last_result": {
            "task_id": "recommendation-result",
            "data": {"agent_results": [{"data": {"recommendations": [
                {"title": "人工智能创新赛"},
                {"title": "算法程序设计赛"},
            ]}}]},
        },
    }
    main_agent = MainAgent(config={})
    assert main_agent.handle_followup("第二个", state["last_result"], state) is None

    state = _update_chat_state(state, "第二个")
    assert state["project_name"] == "算法程序设计赛"
    assert _next_chat_question(state) is None
    request = _chat_standard_input(state, "第二个")
    assert request["task_type"] == "material"
    assert MainAgent(config={}).select_agents(request) == ["material"]


def test_chat_collection_routes_only_to_info_collect():
    state = _update_chat_state(new_chat_state(), "帮我查找人工智能竞赛信息")
    assert state["intent"] == "collect"
    assert _next_chat_question(state) is None
    standard_input = _chat_standard_input(state, "帮我查找人工智能竞赛信息")
    assert MainAgent(config={}).select_agents(standard_input) == ["info_collect"]


def test_chat_extraction_routes_only_to_info_extract_after_notice():
    state = _update_chat_state(new_chat_state(), "帮我提取这份竞赛通知的报名要求")
    assert state["intent"] == "extract"
    assert "粘贴" in _next_chat_question(state)

    notice = "关于举办人工智能竞赛的通知。" + "参赛对象为在校大学生，报名截止日期为2026年9月30日。" * 4
    state = _update_chat_state(state, notice)
    assert state["intent"] == "extract"
    assert _next_chat_question(state) is None
    standard_input = _chat_standard_input(state, notice)
    assert MainAgent(config={}).select_agents(standard_input) == ["info_extract"]


def test_main_agent_handles_unrelated_topic_without_dispatching_agents():
    result = MainAgent(config={}).handle_conversation_control(
        "帮我写一首关于天气的诗", {"intent": "recommendation"}
    )
    assert result is not None
    assert result["metadata"]["followup_type"] == "out_of_scope"
    assert result["metadata"]["agents_dispatched"] == []
    assert "大学生科研与竞赛" in result["data"]["final_answer"]


def test_contextual_short_answer_is_not_treated_as_unrelated():
    result = MainAgent(config={}).handle_conversation_control(
        "国家级", {"intent": "recommendation"}
    )
    assert result is None


def test_chat_correction_uses_replacement_value_only():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "计算机科学与技术",
        "grade": "大二",
        "competition_level": "省级",
    }
    state = _update_chat_state(state, "不是省级，是国家级")
    assert state["competition_level"] == "国家级"

    state = _update_chat_state(state, "专业改成软件工程")
    assert state["major"] == "软件工程"


def test_chat_correction_selects_replacement_project():
    state = {
        **new_chat_state(),
        "intent": "material",
        "major": "计算机科学与技术",
        "grade": "大三",
        "last_result": {
            "data": {"agent_results": [{"data": {"recommendations": [
                {"title": "人工智能创新赛"},
                {"title": "算法程序设计赛"},
            ]}}]}
        },
    }
    state = _update_chat_state(state, "不是第二个，是第一个")
    assert state["project_name"] == "人工智能创新赛"


def test_chat_asks_for_skills_before_recommendation():
    state = _update_chat_state(
        new_chat_state(),
        "我是计算机专业大三学生，想参加国家级人工智能竞赛",
    )

    assert _next_chat_question(state) == (
        "你目前掌握哪些技能？例如 Python、C++、算法、机器学习或团队协作。"
    )
