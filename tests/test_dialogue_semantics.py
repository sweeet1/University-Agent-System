from __future__ import annotations

import pytest

from app import _next_chat_question, _update_chat_state, new_chat_state


def _run_turns(messages: list[str]) -> dict:
    state = new_chat_state()
    for message in messages:
        state = _update_chat_state(state, message)
    return state


@pytest.mark.parametrize(
    ("name", "messages", "expected", "next_question_must_not_contain"),
    [
        (
            "no hard level requirement",
            ["我是计算机专业大三学生，想参加人工智能竞赛", "没有硬性要求"],
            {"competition_level_confirmed": True, "competition_level": ""},
            "校级、省级、国家级还是国际级",
        ),
        (
            "all levels accepted",
            ["我是计算机专业大三学生，想参加人工智能竞赛", "级别都可以"],
            {"competition_level_confirmed": True, "competition_level": ""},
            "校级、省级、国家级还是国际级",
        ),
        (
            "unlimited level",
            ["我是计算机专业大三学生，想参加人工智能竞赛", "不限级别"],
            {"competition_level_confirmed": True, "competition_level": ""},
            "校级、省级、国家级还是国际级",
        ),
        (
            "no category preference",
            ["我是计算机大二，想找国家级竞赛", "方向没有偏好，都可以"],
            {"competition_type_confirmed": True, "competition_type": ""},
            "哪个方向",
        ),
        (
            "data mining and modern skills",
            ["计算机专业大二，会PyTorch和SQL，想找数据挖掘比赛"],
            {"major": "计算机科学与技术", "grade": "大二", "competition_type": "数据分析", "skills": ["PyTorch", "SQL"]},
            "",
        ),
        (
            "ecommerce and marketing",
            ["我是电子商务大一，想参加营销策划比赛"],
            {"major": "电子商务", "grade": "大一", "competition_type": "商业与营销"},
            "",
        ),
        (
            "graduate shorthand and matlab",
            ["自动化研一，会MATLAB，想参加控制类竞赛"],
            {"major": "自动化", "grade": "研究生", "competition_type": "自动化与控制", "skills": ["MATLAB"]},
            "",
        ),
        (
            "enrollment year",
            ["软件工程2024级，想参加算法竞赛"],
            {"major": "软件工程", "grade": "大二", "competition_type": "算法与程序设计"},
            "",
        ),
        (
            "explicit category exclusion",
            ["我是计算机大三，除了数学建模都可以，想要竞赛推荐"],
            {"excluded_competition_types": ["数学建模"]},
            "",
        ),
        (
            "negated and known skills",
            ["我是计算机大三，想参加国家级算法竞赛，我不会Python但会Java"],
            {"skills": ["Java"], "skill_gaps": ["Python"]},
            "",
        ),
        (
            "major correction",
            ["我是计算机大二，想参加国家级算法竞赛", "不是计算机，专业是金融"],
            {"major": "金融学"},
            "",
        ),
        (
            "goal time and team preference",
            ["大三网络工程，平时会Go和Linux，想为保研积累项目，每周大概8小时，最好个人赛"],
            {
                "major": "网络工程",
                "grade": "大三",
                "skills": ["Go", "Linux"],
                "development_goals": ["保研"],
                "available_time_per_week": 8.0,
                "team_preference": "个人赛",
            },
            "",
        ),
        (
            "goal first request",
            ["我想为保研找一些有含金量的竞赛"],
            {"intent": "recommendation", "development_goals": ["保研"]},
            "",
        ),
        (
            "competition direction is not automatically a major",
            ["我大三，想参加人工智能竞赛"],
            {"major": "", "grade": "大三", "competition_type": "人工智能"},
            "",
        ),
        (
            "machine learning category",
            ["帮我看看最近有什么机器学习相关的比赛"],
            {"intent": "recommendation", "competition_type": "人工智能", "skills": ["机器学习"]},
            "",
        ),
        (
            "compound profile",
            ["我是计算机科学与技术专业的大三本科生，Python、Java都能写，但更偏后端开发，想参加国家级比赛"],
            {
                "major": "计算机科学与技术",
                "grade": "大三",
                "skills": ["Python", "Java"],
                "competition_type": "软件开发",
                "competition_level": "国家级",
            },
            "",
        ),
        (
            "unknown skills accepted",
            ["我是工商管理大二，想参加国家级创新创业竞赛", "我暂时不清楚自己擅长什么"],
            {"skills_skipped": True},
            "比较熟悉的技能",
        ),
        (
            "cancel material and recommend again",
            ["帮我生成报名材料", "不生成材料了，重新推荐算法竞赛"],
            {"intent": "recommendation", "competition_type": "算法与程序设计"},
            "",
        ),
    ],
)
def test_natural_language_state_semantics(
    name: str,
    messages: list[str],
    expected: dict,
    next_question_must_not_contain: str,
) -> None:
    state = _run_turns(messages)

    for key, value in expected.items():
        assert state[key] == value, name
    if next_question_must_not_contain:
        assert next_question_must_not_contain not in (_next_chat_question(state) or ""), name
