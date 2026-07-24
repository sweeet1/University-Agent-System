from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app import (
    _apply_turn_understanding,
    _build_conversation_summary,
    _chat_standard_input,
    _expand_recommendations_from_cache,
    _next_chat_question,
    _profile_edit_followup_answer,
    _recommendations_from_chat_state,
    _should_hold_after_profile_edit,
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
    question = _next_chat_question(state)
    assert "方向" in question

    state = _update_chat_state(state, "我更喜欢算法，也会Python")
    assert state["competition_type"] == "算法与程序设计"
    assert state["skills"] == ["Python"]
    assert "校级、省级、国家级还是国际级" in _next_chat_question(state)

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


def test_pasted_notice_cannot_overwrite_profile_or_material_intent():
    state = {
        **new_chat_state(),
        "intent": "material",
        "major": "人工智能",
        "grade": "大三",
        "skills": ["Python"],
        "material_type": "generic_application_form",
    }
    notice = (
        "关于举办2026年挑战杯校内选拔赛的通知。主办单位：学校创新创业学院。"
        "参赛对象为全日制在校本科生和研究生。新一代信息技术赛道包括人工智能、"
        "基础软件、网络安全等领域。报名截止时间：2026年5月20日。"
        "申报材料包括项目申报书、团队信息表和证明材料。"
    )
    state = _update_chat_state(state, notice, understanding={
        "input_role": "competition_notice",
        "intent": "recommendation",
        "dialogue_action": "profile_change",
        "major": "软件工程",
        "grade": "研究生",
        "skills_add": ["网络安全"],
        "corrected_fields": ["major", "grade"],
        "acknowledgement": "明白了，按软件工程专业重新梳理。",
    })

    assert state["input_role"] == "competition_notice"
    assert state["intent"] == "material"
    assert state["major"] == "人工智能"
    assert state["grade"] == "大三"
    assert state["skills"] == ["Python"]
    assert state["notification_text"] == notice
    assert state["dialogue_action"] == "continue"
    assert "竞赛通知处理" in state["last_acknowledgement"]

    request = _chat_standard_input(state, notice)
    assert request["task_type"] == "material"
    assert MainAgent(config={}).select_agents(request) == ["info_extract", "material"]


def test_project_application_request_sets_generic_application_form():
    state = _update_chat_state(
        new_chat_state(),
        "帮我生成mike的项目申报书",
        understanding={
            "input_role": "command",
            "intent": "material",
            "dialogue_action": "generate_material",
        },
    )

    assert state["intent"] == "material"
    assert state["material_type"] == "generic_application_form"
    question = _next_chat_question(state)
    assert "专业" in question
    assert "大几" in question


def test_material_request_does_not_run_after_only_profile_details():
    state = _update_chat_state(
        new_chat_state(),
        "帮我生成小桃的项目申报书",
        understanding={
            "input_role": "command",
            "intent": "material",
            "dialogue_action": "generate_material",
        },
    )
    state = _update_chat_state(
        state,
        "人工智能专业，大三",
        understanding={
            "input_role": "user_profile",
            "major": "人工智能",
            "grade": "大三",
            "dialogue_action": "continue",
        },
    )

    assert state["intent"] == "material"
    assert state["major"] == "人工智能"
    assert state["grade"] == "大三"
    assert not state["notification_text"]
    question = _next_chat_question(state)
    assert "完整通知" in question or "申报要求" in question


def test_material_request_runs_only_after_complete_notice_is_pasted():
    state = _update_chat_state(
        new_chat_state(),
        "帮我生成小桃的项目申报书",
        understanding={
            "input_role": "command",
            "intent": "material",
            "dialogue_action": "generate_material",
        },
    )
    state = _update_chat_state(
        state,
        "人工智能专业，大三",
        understanding={
            "input_role": "user_profile",
            "major": "人工智能",
            "grade": "大三",
            "dialogue_action": "continue",
        },
    )
    notice = (
        "关于举办2026年“小桃杯”大学生创业计划竞赛的通知。"
        "主办单位：创新创业学院。参赛对象：全日制在校本科生及研究生。"
        "竞赛设新一代信息技术、文化创意和现代服务等赛道。"
        "申报材料包括项目申报书、团队信息表及证明材料。"
        "报名截止时间：2026年5月20日，具体要求以附件申报指南为准。"
    )
    state = _update_chat_state(
        state,
        notice,
        understanding={
            "input_role": "competition_notice",
            "intent": "material",
            "dialogue_action": "continue",
        },
    )

    assert state["intent"] == "material"
    assert state["notification_text"] == notice
    assert _next_chat_question(state) is None
    request = _chat_standard_input(state, notice)
    assert MainAgent(config={}).select_agents(request) == ["info_extract", "material"]


def test_structured_notice_below_old_length_threshold_is_still_accepted():
    state = {
        **new_chat_state(),
        "intent": "material",
        "major": "人工智能",
        "grade": "大三",
        "material_type": "generic_application_form",
    }
    notice = (
        "竞赛通知：主办单位为创新学院；参赛对象为本科生；"
        "申报材料包括项目申报书；报名截止时间为2026年5月20日。"
    )

    state = _update_chat_state(state, notice)

    assert state["notification_text"] == notice
    assert state["intent"] == "material"
    assert _next_chat_question(state) is None


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


def test_field_edit_holds_agent_and_asks_next_action():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "计算机科学与技术",
        "grade": "大三",
        "competition_type": "人工智能",
        "competition_type_confirmed": True,
        "competition_level": "省级",
        "competition_level_confirmed": True,
        "skills_skipped": True,
        "last_result": {"status": "success"},
    }
    state = _update_chat_state(state, "级别改成国家级")

    assert state["competition_level"] == "国家级"
    assert state.get("_edited_fields") == ["竞赛级别"]
    assert _next_chat_question(state) is None
    edited = _should_hold_after_profile_edit(state, {"dialogue_action": "change_preferences"})
    assert edited == ["竞赛级别"]
    answer = _profile_edit_followup_answer(edited)
    assert "修改完成" in answer
    assert "不会立刻重新筛选" in answer
    assert "接下来想做什么" in answer


def test_field_edit_llm_primary_over_lexicon():
    """Natural phrasing that lexicon misses should still update via LLM."""
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "计算机科学与技术",
        "grade": "大三",
        "competition_type": "人工智能",
        "competition_type_confirmed": True,
        "competition_level": "省级",
        "competition_level_confirmed": True,
        "skills_skipped": True,
        "last_result": {"status": "success"},
    }
    # Lexicon alone does not map「国赛」→国家级
    offline = _update_chat_state(dict(state), "级别想冲一冲国赛")
    assert offline["competition_level"] == "省级"
    assert not offline.get("_edited_fields")

    updated = _update_chat_state(
        state,
        "级别想冲一冲国赛",
        understanding={
            "intent": "recommendation",
            "dialogue_action": "change_preferences",
            "competition_level": "国家级",
            "corrected_fields": ["competition_level"],
            "acknowledgement": "明白了，级别按国家级来。",
        },
    )
    assert updated["competition_level"] == "国家级"
    assert updated.get("_edited_fields") == ["竞赛级别"]
    assert _should_hold_after_profile_edit(
        updated, {"dialogue_action": "change_preferences"}
    ) == ["竞赛级别"]


def test_field_edit_llm_overrides_conflicting_lexicon_draft():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "计算机科学与技术",
        "grade": "大三",
        "competition_type": "人工智能",
        "competition_type_confirmed": True,
        "competition_level": "省级",
        "competition_level_confirmed": True,
        "skills_skipped": True,
    }
    # Lexicon may latch onto「省级」first; non-empty LLM value must win.
    updated = _update_chat_state(
        state,
        "请改成校级，不是省级",
        understanding={
            "intent": "recommendation",
            "dialogue_action": "change_preferences",
            "competition_level": "校级",
            "corrected_fields": ["competition_level"],
        },
    )
    assert updated["competition_level"] == "校级"


def test_first_time_profile_fill_does_not_count_as_field_edit():
    state = _update_chat_state(
        new_chat_state(),
        "我是计算机专业大三学生，想参加国家级人工智能竞赛",
    )
    assert not state.get("_edited_fields")
    assert "比较熟悉的技能" in (_next_chat_question(state) or "")


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

    question = _next_chat_question(state)
    assert "比较熟悉的技能" in question
    assert "没什么擅长的也可以直接说" in question


def test_chat_allows_user_to_continue_without_declared_skills():
    state = _update_chat_state(
        new_chat_state(),
        "我是计算机专业大三学生，想参加国家级人工智能竞赛",
    )

    state = _update_chat_state(state, "暂时没有特别擅长的技能")

    assert state["skills_skipped"] is True
    assert state["skills"] == ["暂无"]
    assert _next_chat_question(state) is None


def test_skills_no_strength_phrase_fills_temporary_none():
    state = _update_chat_state(
        new_chat_state(),
        "我是计算机专业大三学生，想参加国家级人工智能竞赛",
    )
    state = _update_chat_state(state, "没什么擅长的")

    assert state["skills"] == ["暂无"]
    assert state["skills_skipped"] is True
    assert _next_chat_question(state) is None


def test_chat_groups_basic_profile_questions_naturally():
    state = _update_chat_state(new_chat_state(), "帮我推荐一些竞赛")

    question = _next_chat_question(state)

    assert "专业" in question
    assert "读大几" in question
    assert "请输入" not in question


def test_chat_accepts_explicit_no_level_preference_without_repeating_question():
    state = _update_chat_state(
        new_chat_state(),
        "我是计算机专业大三学生，想参加人工智能竞赛",
    )
    state = _update_chat_state(state, "没有硬性要求，什么级别都可以")

    assert state["competition_level_confirmed"] is True
    assert state["competition_level"] == ""
    assert state["competition_type"] == "人工智能"
    assert "级别" not in (_next_chat_question(state) or "")


def test_level_soft_preference_does_not_clear_competition_type():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "人工智能",
        "grade": "大四",
        "competition_type": "数学建模",
        "competition_type_confirmed": True,
        "skills_skipped": True,
    }
    state = _update_chat_state(state, "没什么硬性要求", understanding={
        "intent": "recommendation",
        "competition_level_status": "no_preference",
        # 模拟 LLM 误把「硬性要求」当成方向无偏好，并乱改专业
        "competition_type_status": "no_preference",
        "competition_type": "",
        "major": "计算机科学与技术",
        "skills_status": "no_preference",
        "acknowledgement": "明白了，级别没有硬性要求。",
    })

    assert state["major"] == "人工智能"
    assert state["competition_type"] == "数学建模"
    assert state["competition_type_confirmed"] is True
    assert state["competition_level"] == ""
    assert state["competition_level_confirmed"] is True
    assert state["skills_skipped"] is True
    assert _next_chat_question(state) is None


def test_direction_soft_preference_does_not_clear_level():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "计算机科学与技术",
        "grade": "大三",
        "competition_level": "国家级",
        "competition_level_confirmed": True,
    }
    state = _update_chat_state(state, "方向没有偏好，都可以", understanding={
        "intent": "recommendation",
        "competition_type_status": "no_preference",
        "competition_level_status": "no_preference",
        "competition_level": "",
    })

    assert state["competition_type"] == ""
    assert state["competition_type_confirmed"] is True
    assert state["competition_level"] == "国家级"
    assert state["competition_level_confirmed"] is True
    assert "方向" not in (_next_chat_question(state) or "")


def test_skills_soft_preference_does_not_clear_type_or_level():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "计算机科学与技术",
        "grade": "大三",
        "competition_type": "算法与程序设计",
        "competition_type_confirmed": True,
        "competition_level": "省级",
        "competition_level_confirmed": True,
    }
    state = _update_chat_state(state, "暂时没有特别擅长的", understanding={
        "intent": "recommendation",
        "skills_status": "no_preference",
        "competition_type_status": "no_preference",
        "competition_level_status": "no_preference",
        "major": "软件工程",
    })

    assert state["major"] == "计算机科学与技术"
    assert state["competition_type"] == "算法与程序设计"
    assert state["competition_level"] == "省级"
    assert state["skills_skipped"] is True
    assert state["skills"] == ["暂无"]
    assert _next_chat_question(state) is None


def test_chat_accepts_direction_no_preference_without_repeating_question():
    state = _update_chat_state(
        new_chat_state(),
        "我是计算机专业大二学生，想找国家级竞赛",
    )
    state = _update_chat_state(state, "方向没有偏好，都可以")

    assert state["competition_type_confirmed"] is True
    assert state["competition_type"] == ""
    assert state["competition_level"] == "国家级"
    assert "方向" not in (_next_chat_question(state) or "")
    assert "比较熟悉的技能" in (_next_chat_question(state) or "")


def test_chat_does_not_treat_excluded_category_as_preference():
    state = _update_chat_state(
        new_chat_state(),
        "我是计算机大三，除了数学建模都可以，想要竞赛推荐",
    )

    assert state["competition_type"] != "数学建模"
    assert "数学建模" in state["excluded_competition_types"]


def test_chat_distinguishes_known_skills_from_skill_gaps():
    state = _update_chat_state(
        new_chat_state(),
        "我是计算机大三，想参加国家级算法竞赛，我不会Python但会Java",
    )

    assert state["skills"] == ["Java"]
    assert state["skill_gaps"] == ["Python"]


def test_chat_extracts_richer_profile_from_natural_sentence():
    state = _update_chat_state(
        new_chat_state(),
        "大三网络工程，平时会Go和Linux，想为保研积累项目，每周大概8小时，最好个人赛",
    )

    assert state["major"] == "网络工程"
    assert state["grade"] == "大三"
    assert state["skills"] == ["Go", "Linux"]
    assert state["development_goals"] == ["保研"]
    assert state["available_time_per_week"] == 8.0
    assert state["team_preference"] == "个人赛"


def test_chat_understands_research_grade_and_more_skill_aliases():
    state = _update_chat_state(
        new_chat_state(),
        "自动化研一，会MATLAB，想参加控制类竞赛",
    )

    assert state["major"] == "自动化"
    assert state["grade"] == "研究生"
    assert state["skills"] == ["MATLAB"]
    assert state["competition_type"] == "自动化与控制"


def test_chat_correction_ignores_rejected_major():
    state = _update_chat_state(
        new_chat_state(),
        "我是计算机大二，想参加国家级算法竞赛",
    )
    state = _update_chat_state(state, "不是计算机，专业是金融")

    assert state["major"] == "金融学"


def test_cancel_material_request_returns_to_recommendation():
    state = _update_chat_state(new_chat_state(), "帮我生成报名材料")
    state = _update_chat_state(state, "不生成材料了，重新推荐算法竞赛")

    assert state["intent"] == "recommendation"


def test_greeting_or_thanks_do_not_swallow_a_real_task():
    agent = MainAgent(config={})

    assert agent.handle_conversation_control("你好，推荐AI竞赛", new_chat_state()) is None
    assert agent.handle_conversation_control("谢谢，帮我生成报名材料", new_chat_state()) is None


def test_natural_followup_field_question_requests_reference_clarification():
    previous_result = {
        "task_id": "recommendation-result",
        "data": {"agent_results": [{"data": {"recommendations": [
            {"title": "人工智能创新赛", "deadline": "2026-09-01"},
            {"title": "算法程序设计赛", "deadline": "2026-10-01"},
        ]}}]},
    }

    result = MainAgent(config={}).handle_followup(
        "它什么时候截止报名？",
        previous_result,
        {**new_chat_state(), "intent": "recommendation"},
    )

    assert result is not None
    assert result["status"] == "need_input"
    assert "不能确定你指的是哪一个" in result["data"]["final_answer"]


def test_natural_followup_uses_selected_project_and_answers_known_deadline():
    previous_result = {
        "task_id": "recommendation-result",
        "data": {"agent_results": [{"data": {"recommendations": [
            {"title": "人工智能创新赛", "deadline": "2026-09-01"},
            {"title": "算法程序设计赛", "deadline": "2026-10-01"},
        ]}}]},
    }

    result = MainAgent(config={}).handle_followup(
        "它什么时候截止报名？",
        previous_result,
        {**new_chat_state(), "intent": "recommendation", "project_name": "算法程序设计赛"},
    )

    assert result is not None
    assert result["status"] == "success"
    assert "2026-10-01" in result["data"]["final_answer"]
    assert result["metadata"]["generation_source"] == "fallback"


def test_followup_can_compare_previous_recommendations_for_goal():
    previous_result = {
        "task_id": "recommendation-result",
        "data": {"agent_results": [{"data": {"recommendations": [
            {"title": "人工智能创新赛", "match_score": 82, "reason": "方向匹配"},
            {"title": "算法程序设计赛", "match_score": 76, "reason": "技能匹配"},
        ]}}]},
    }

    result = MainAgent(config={}).handle_followup(
        "哪个更适合保研？",
        previous_result,
        {**new_chat_state(), "intent": "recommendation", "development_goals": ["保研"]},
    )

    assert result is not None
    assert result["metadata"]["followup_type"] == "competition_comparison"
    assert "人工智能创新赛" in result["data"]["final_answer"]
    assert "算法程序设计赛" in result["data"]["final_answer"]
    assert "认定目录" in result["data"]["final_answer"]


def test_structured_turn_understanding_merges_without_losing_existing_state():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "网络工程",
        "grade": "大三",
    }

    state = _apply_turn_understanding(state, {
        "intent": "recommendation",
        "skills_add": ["Go", "Linux"],
        "skills_remove": ["Python"],
        "competition_level_status": "no_preference",
        "development_goals": ["保研"],
        "available_time_per_week": 8,
        "team_preference": "个人赛",
        "acknowledgement": "明白了，我会按保研目标和个人赛偏好来筛选。",
    })

    assert state["major"] == "网络工程"
    assert state["skills"] == ["Go", "Linux"]
    assert state["skill_gaps"] == ["Python"]
    assert state["competition_level_confirmed"] is True
    assert state["development_goals"] == ["保研"]
    assert state["available_time_per_week"] == 8.0
    assert state["last_acknowledgement"].startswith("明白了")


def test_llm_understanding_cannot_overwrite_a_known_intent_without_transition():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "competition_type": "人工智能",
        "competition_type_confirmed": True,
    }

    state = _apply_turn_understanding(state, {
        "intent": "extract",
        "competition_type": "算法竞赛",
        "competition_level_status": "no_preference",
    })

    # intent 仍不可随意切换；本轮显式给出的 competition_type 可覆盖
    assert state["intent"] == "recommendation"
    assert state["competition_type"] == "算法竞赛"
    assert state["competition_level_confirmed"] is True


def test_llm_empty_competition_type_does_not_wipe_prior_value():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "competition_type": "人工智能",
        "competition_type_confirmed": True,
    }

    state = _apply_turn_understanding(state, {
        "intent": "recommendation",
        "competition_type": "",
        "skills_add": ["Python"],
    })

    assert state["competition_type"] == "人工智能"
    assert state["skills"] == ["Python"]


def test_llm_overrides_rule_draft_for_major_and_competition_type():
    """规则可能把「人工智能专业」误写成方向；LLM 非空值应纠正。"""
    message = "我是人工智能专业大四学生，想参加数学建模方面的竞赛，省级的就可以"
    state = _update_chat_state(new_chat_state(), message, understanding={
        "intent": "recommendation",
        "major": "人工智能",
        "grade": "大四",
        "competition_type": "数学建模",
        "competition_level": "省级",
        "acknowledgement": "明白了，按数学建模方向帮你看省级竞赛。",
    })

    assert state["major"] == "人工智能"
    assert state["competition_type"] == "数学建模"
    assert state["grade"] == "大四"
    assert state["competition_level"] == "省级"


def test_known_skills_lexicon_skipped_when_understanding_present():
    state = _update_chat_state(
        new_chat_state(),
        "计算机专业大三，想参加算法竞赛，也会一点机器学习",
        understanding={
            "intent": "recommendation",
            "major": "计算机科学与技术",
            "grade": "大三",
            "competition_type": "算法与程序设计",
            "skills_add": ["Python"],
        },
    )

    assert state["skills"] == ["Python"]
    assert "机器学习" not in state["skills"]


def test_turn_understanding_falls_back_cleanly_when_llm_is_disabled(monkeypatch):
    agent = MainAgent(config={})
    monkeypatch.setattr(agent, "_is_llm_enabled", lambda: False)

    assert agent.understand_conversation_turn("没有硬性要求", new_chat_state()) is None


def test_llm_action_expands_recommendations_without_phrase_rules():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "计算机科学与技术",
        "grade": "大三",
    }
    state = _update_chat_state(state, "结果显得有些单薄", understanding={
        "intent": "recommendation",
        "dialogue_action": "expand_recommendations",
        "response_mode": "run_agent",
        "recommendation_options": {"top_n": 6, "include_backup": True},
    })

    request = _chat_standard_input(state, "结果显得有些单薄")
    rules = request["input_data"]["recommendation_rules"]
    assert rules["top_n"] == 6
    assert rules["quality_gate"]["prefer_fewer"] is False
    assert request["user_input"] == "结果显得有些单薄"


def test_expand_recommendations_uses_cached_pool_without_rerun():
    pool = [
        {"title": f"竞赛{index}", "match_score": 90 - index, "summary": f"简介{index}", "reason": "匹配"}
        for index in range(1, 8)
    ]
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "计算机科学与技术",
        "grade": "大三",
        "recommendation_options": {"top_n": 6, "include_backup": True},
        "dialogue_action": "expand_recommendations",
        "last_result": {
            "status": "success",
            "data": {
                "agent_results": [
                    {
                        "agent_name": "recommendation_agent",
                        "status": "success",
                        "data": {
                            "recommendations": pool[:3],
                            "recommendation_pool": pool,
                        },
                    }
                ]
            },
        },
    }
    understanding = {
        "intent": "recommendation",
        "dialogue_action": "expand_recommendations",
        "response_mode": "answer_from_context",
        "recommendation_options": {"top_n": 6},
    }

    answer = _expand_recommendations_from_cache(state, understanding)

    assert answer is not None
    assert "现在一共给你看 6 条" in answer
    assert "又多找了几条" in answer
    shown = _recommendations_from_chat_state(state)
    assert len(shown) == 6
    assert shown[0]["title"] == "竞赛1"
    assert shown[5]["title"] == "竞赛6"
    assert shown[3]["rank"] == 4


def test_expand_recommendations_without_pool_falls_through():
    state = {
        **new_chat_state(),
        "last_result": {
            "status": "success",
            "data": {
                "agent_results": [
                    {
                        "data": {
                            "recommendations": [{"title": "仅三条之一", "match_score": 80}],
                        }
                    }
                ]
            },
        },
    }
    assert _expand_recommendations_from_cache(state, {
        "dialogue_action": "expand_recommendations",
        "recommendation_options": {"top_n": 6},
    }) is None


def test_conversation_context_is_compacted_for_agent_input():
    state = new_chat_state()
    for index in range(12):
        state = _update_chat_state(state, f"第{index}轮普通补充")
    state["major"] = "计算机科学与技术"
    state["grade"] = "大三"
    state["conversation_summary"] = _build_conversation_summary(state)

    request = _chat_standard_input(state, "继续")
    assert len(state["turns"]) == 8
    assert len(request["context"]["recent_turns"]) == 4
    assert "专业：计算机科学与技术" in request["context"]["conversation_summary"]
    assert "；".join(state["turns"]) not in request["user_input"]


def test_major_change_starts_fresh_recommendation_context():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "计算机科学与技术",
        "grade": "大三",
        "skills": ["Python", "C++"],
        "competition_type": "人工智能",
        "competition_type_confirmed": True,
        "competition_level": "国家级",
        "competition_level_confirmed": True,
        "last_result": {"status": "success"},
        "project_name": "人工智能竞赛",
    }

    state = _update_chat_state(state, "我现在是金融专业的，想看看新的比赛", understanding={
        "intent": "recommendation",
        "dialogue_action": "profile_change",
        "major": "金融学",
        "corrected_fields": ["major"],
    })

    assert state["major"] == "金融学"
    assert state["skills"] == []
    assert state["competition_type"] == ""
    assert state["competition_level"] == ""
    assert state["last_result"] == {}
    assert state["project_name"] == ""
    assert "金融学专业重新梳理" in state["last_acknowledgement"]
    assert _next_chat_question(state) is not None


def test_cross_disciplinary_scope_accepts_open_direction():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "计算机科学与技术",
        "grade": "大一",
    }
    state = _update_chat_state(state, "可以接受跨学科，计算机相关也行", understanding={
        "intent": "recommendation",
        "dialogue_action": "change_preferences",
        "competition_scope": "both",
        "competition_type_status": "no_preference",
        "competition_level_status": "unknown",
        "acknowledgement": "明白了，本专业相关和跨学科方向都可以考虑。",
    })

    assert state["competition_scope"] == "both"
    assert state["competition_type_confirmed"] is True
    assert state["competition_type"] == ""
    question = _next_chat_question(state)
    assert "校级、省级、国家级还是国际级" in (question or "")
    assert "跨学科方向" not in (question or "")


def test_recommendation_does_not_run_when_scope_level_and_skills_lack_topic():
    state = {
        **new_chat_state(),
        "intent": "recommendation",
        "major": "计算机科学与技术",
        "grade": "大三",
        "competition_scope": "cross_disciplinary",
        "competition_level": "国家级",
        "competition_level_confirmed": True,
        "skills": ["Python", "C++"],
    }

    question = _next_chat_question(state)

    assert question is not None
    assert "主题" in question
    assert state["competition_type_confirmed"] is False


def test_main_agent_explains_structured_candidate_data_is_missing():
    result = MainAgent(config={}).integrate_results(
        {"task_type": "recommendation", "user_input": "没有特别擅长"},
        [{
            "agent_name": "recommendation_agent",
            "status": "need_input",
            "data": {},
            "message": "structured_items 为空，请先补充可推荐的项目数据。",
            "error": None,
        }],
    )

    answer = result["final_answer"]
    assert "个人信息已经足够" in answer
    assert "竞赛候选数据" in answer
    assert "补充一点信息" not in answer


def test_main_agent_explains_supabase_rls_failure():
    result = MainAgent(config={}).integrate_results(
        {"task_type": "recommendation", "user_input": "没有特别擅长"},
        [{
            "agent_name": "info_collect_agent",
            "status": "failed",
            "data": {},
            "message": "InfoCollectAgent execution failed.",
            "error": {
                "error_type": "APIError",
                "error_message": "new row violates row-level security policy; code 42501",
            },
        }],
    )

    answer = result["final_answer"]
    assert "不需要继续补充个人信息" in answer
    assert "Supabase RLS" in answer


def test_what_information_followup_explains_previous_need_input():
    previous = {
        "task_id": "task-need-input",
        "data": {
            "agent_results": [{
                "agent_name": "recommendation_agent",
                "status": "need_input",
                "data": {},
                "message": "缺少结构化项目数据（structured_items）。",
                "error": None,
            }]
        },
    }

    result = MainAgent(config={}).handle_followup(
        "什么信息",
        previous,
        {"intent": "recommendation"},
    )

    assert result is not None
    assert "竞赛候选数据" in result["data"]["final_answer"]
