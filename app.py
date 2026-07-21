from __future__ import annotations

import argparse
import html
import json
import os
import threading
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# Gradio calls its own localhost startup endpoint during launch. Some system
# proxy configurations route that request through a proxy and return 502.
_no_proxy_entries = {"127.0.0.1", "localhost", "::1"}
for _env_name in ("NO_PROXY", "no_proxy"):
    _existing_entries = {
        item.strip() for item in os.environ.get(_env_name, "").split(",") if item.strip()
    }
    os.environ[_env_name] = ",".join(sorted(_existing_entries | _no_proxy_entries))

try:
    import gradio as gr
except ImportError:  # pragma: no cover
    gr = None

from agents.main_agent import MainAgent

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

TASK_TYPE_CHOICES = [
    ("全流程辅助", "full_process"),
    ("项目推荐", "recommendation"),
    ("通知信息抽取", "info_extract"),
    ("项目信息采集", "info_collect"),
    ("申报材料生成", "material"),
]

DATA_SOURCE_CHOICES = [
    ("本地项目库", "local"),
    ("公开网页", "web"),
    ("上传或粘贴文本", "upload"),
    ("混合来源", "mixed"),
]

MATERIAL_TYPE_CHOICES = [
    ("自动识别", ""),
    ("挑战杯（大挑）申报书", "challenge_cup_grand_application"),
    ("挑战杯（大挑）材料清单", "challenge_cup_grand_checklist"),
    ("挑战杯（大挑）答辩 PPT", "challenge_cup_grand_ppt"),
    ("挑战杯创业计划书", "challenge_cup_business_plan"),
    ("挑战杯创业材料清单", "challenge_cup_business_checklist"),
    ("互联网+ / 创新创业商业计划书", "innovation_contest_business_plan"),
    ("互联网+ / 创新创业申报表", "innovation_contest_application_form"),
    ("互联网+ / 创新创业材料清单", "innovation_contest_checklist"),
    ("通用申报表", "generic_application_form"),
    ("通用项目报告", "generic_project_report"),
    ("通用答辩 PPT", "generic_ppt"),
    ("通用准备进度表", "generic_schedule"),
]

APP_CSS = r"""
:root {
  --szt-navy: #0b1739;
  --szt-blue: #1f5eff;
  --szt-cyan: #16c7b7;
  --szt-ink: #16223b;
  --szt-muted: #667085;
  --szt-line: #dfe5ef;
  --szt-surface: rgba(255,255,255,.92);
}

.gradio-container {
  width: min(96vw, 1880px) !important;
  max-width: none !important;
  margin: 0 auto !important;
  color: var(--szt-ink);
  background:
    radial-gradient(circle at 7% 0%, rgba(31,94,255,.11), transparent 30rem),
    radial-gradient(circle at 94% 5%, rgba(22,199,183,.10), transparent 27rem),
    #f5f7fb !important;
}

footer { display: none !important; }

.szt-shell { width: 100% !important; max-width: none !important; padding: 18px 8px 36px; }
.szt-main-grid {
  display: grid !important;
  grid-template-columns: minmax(520px, 1fr) minmax(620px, 1.16fr) !important;
  align-items: start !important;
  gap: 20px !important;
  width: 100% !important;
}

.szt-hero {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 26px;
  padding: 34px 38px;
  margin-bottom: 18px;
  color: #fff;
  background: linear-gradient(122deg, #0a1636 0%, #102d72 62%, #0b6f75 130%);
  box-shadow: 0 22px 55px rgba(13,35,81,.18);
}

.szt-hero::after {
  content: "";
  position: absolute;
  width: 340px;
  height: 340px;
  top: -220px;
  right: -60px;
  border: 52px solid rgba(83,224,211,.12);
  border-radius: 50%;
}

.szt-brand { display: flex; align-items: center; gap: 13px; margin-bottom: 20px; }
.szt-logo {
  position: relative; display: inline-grid; place-items: center;
  width: 48px; height: 48px; border-radius: 15px;
  font-size: 20px; font-weight: 850; letter-spacing: -.06em;
  color: #09244a; background: linear-gradient(145deg, #ffffff 0%, #82f1e6 100%);
  border: 1px solid rgba(255,255,255,.7);
  box-shadow: 0 9px 26px rgba(22,199,183,.28);
}
.szt-logo::before, .szt-logo::after { content: ""; position: absolute; width: 6px; height: 6px; border-radius: 50%; background: #1467d9; border: 2px solid #c9fff9; }
.szt-logo::before { top: 6px; right: 6px; }
.szt-logo::after { bottom: 6px; left: 6px; background: #08a99c; }
.szt-brand-name { color: #ffffff !important; font-size: 21px; font-weight: 760; letter-spacing: .06em; text-shadow: 0 1px 12px rgba(0,0,0,.15); }
.szt-hero h1 { margin: 0; max-width: none; color: #ffffff !important; font-size: clamp(30px, 3.15vw, 48px); font-weight: 800 !important; line-height: 1.18; letter-spacing: -.035em; white-space: nowrap; text-shadow: 0 3px 24px rgba(0,0,0,.22); }
.szt-hero p { margin: 16px 0 0; max-width: 850px; color: #e6eeff !important; font-size: 16px; font-weight: 500; line-height: 1.75; }

.szt-process { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 22px; }
.szt-process span { padding: 7px 11px; border-radius: 10px; color: #f5f8ff !important; background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.2); font-size: 12px; font-weight: 650; }
.szt-process b { color: #65e9dc; font-weight: 700; }

.szt-card {
  border: 1px solid rgba(211,219,233,.86) !important;
  border-radius: 20px !important;
  background: var(--szt-surface) !important;
  box-shadow: 0 10px 30px rgba(24,45,82,.065) !important;
}
.szt-panel { padding: 18px !important; }
.szt-input-panel,
.szt-workbench {
  min-width: 0 !important;
  width: 100% !important;
  max-width: 100% !important;
  margin: 0 !important;
  overflow: hidden !important;
}
.szt-section-title h3 { margin: 0 0 4px; color: #14213d; font-size: 17px; letter-spacing: -.01em; }
.szt-section-title p { margin: 0 0 12px; color: var(--szt-muted); font-size: 12px; }

.szt-card label span { color: #344054 !important; font-weight: 650 !important; }
.szt-card textarea, .szt-card input { border-radius: 12px !important; }
.szt-card .wrap { border-radius: 12px !important; border-color: #d9e0ec !important; }

.szt-primary { min-height: 48px !important; border: none !important; border-radius: 13px !important; font-weight: 720 !important; background: linear-gradient(105deg, #1f5eff, #1677dc 65%, #0daaa0) !important; box-shadow: 0 10px 25px rgba(31,94,255,.22) !important; }
.szt-primary:hover { transform: translateY(-1px); box-shadow: 0 13px 28px rgba(31,94,255,.28) !important; }
.szt-secondary { min-height: 48px !important; border-radius: 13px !important; color: #344054 !important; background: #fff !important; }

.szt-tip { padding: 13px 14px; border-radius: 13px; color: #476071; background: #eef8f7; border: 1px solid #d3eeeb; font-size: 12px; line-height: 1.65; }

.szt-status {
  display: flex; align-items: center; gap: 10px; min-height: 54px;
  padding: 12px 15px; border-radius: 14px; color: #475467;
  background: #f8fafc; border: 1px solid #e1e7f0;
}
.szt-status-dot { width: 9px; height: 9px; border-radius: 50%; background: #98a2b3; box-shadow: 0 0 0 5px rgba(152,162,179,.12); }
.szt-status.success { color: #067647; background: #ecfdf3; border-color: #abefc6; }
.szt-status.success .szt-status-dot { background: #12b76a; box-shadow: 0 0 0 5px rgba(18,183,106,.12); }
.szt-status.partial, .szt-status.need_input { color: #93370d; background: #fffaeb; border-color: #fedf89; }
.szt-status.partial .szt-status-dot, .szt-status.need_input .szt-status-dot { background: #f79009; box-shadow: 0 0 0 5px rgba(247,144,9,.12); }
.szt-status.failed { color: #b42318; background: #fef3f2; border-color: #fecdca; }
.szt-status.failed .szt-status-dot { background: #f04438; box-shadow: 0 0 0 5px rgba(240,68,56,.12); }

.szt-result { min-height: 300px; padding: 4px 8px 14px !important; }
.szt-result h1, .szt-result h2, .szt-result h3 { color: #14213d; }
.szt-result code { border-radius: 7px; background: #edf2ff; color: #244fc7; }
.szt-result-placeholder { display:grid; place-items:center; min-height:250px; text-align:center; color:#98a2b3; }

.szt-agent-table { min-height: 265px; }
.szt-workbench .tabs {
  display: block !important;
  width: 100% !important;
  min-width: 0 !important;
  max-width: 100% !important;
  overflow: hidden !important;
}
.szt-workbench .tab-nav,
.szt-workbench [role="tablist"] { width: 100% !important; min-width: 0 !important; }
.szt-workbench .tabitem,
.szt-workbench [role="tabpanel"] {
  box-sizing: border-box !important;
  width: 100% !important;
  min-width: 0 !important;
  max-width: 100% !important;
  height: 560px !important;
  min-height: 560px !important;
  max-height: 560px !important;
  overflow: auto !important;
}
.szt-workbench .szt-result,
.szt-workbench .szt-agent-table,
.szt-workbench .json-holder {
  box-sizing: border-box !important;
  width: 100% !important;
  min-width: 0 !important;
  max-width: 100% !important;
  min-height: 500px !important;
}
.szt-source-box { padding: 14px !important; border-radius: 14px !important; background: #f8fafc !important; border: 1px solid #e2e8f0 !important; }
.szt-footer { margin-top: 18px; padding: 8px; text-align: center; color: #98a2b3; font-size: 12px; }

@media (max-width: 900px) {
  .gradio-container { width: 100% !important; }
  .szt-shell { padding: 8px 2px 24px; }
  .szt-hero { padding: 25px 22px; border-radius: 20px; }
  .szt-panel { padding: 13px !important; }
  .szt-hero h1 { white-space: normal; font-size: clamp(28px, 8vw, 42px); }
  .szt-main-grid { display: flex !important; flex-direction: column !important; }
  .szt-workbench .tabitem,
  .szt-workbench [role="tabpanel"] { height: 480px !important; min-height: 480px !important; max-height: 480px !important; }
}
"""

HERO_HTML = """
<section class="szt-hero">
  <div class="szt-brand">
    <span class="szt-logo">智</span>
    <span class="szt-brand-name">赛智通</span>
  </div>
  <h1>让科研竞赛申报，从信息焦虑变成清晰行动</h1>
  <p>基于多智能体协作的大学生科研竞赛辅助工作台，统一完成信息采集、通知抽取、项目匹配与申报材料准备。</p>
  <div class="szt-process">
    <span>01 信息采集</span><b>→</b><span>02 结构化抽取</span><b>→</b><span>03 智能匹配</span><b>→</b><span>04 材料辅助</span>
  </div>
</section>
"""

EMPTY_RESULT = """
<div class="szt-result-placeholder">
  <div><div style="font-size:32px;margin-bottom:8px">✦</div><strong>暂无分析结果</strong><br><span>填写左侧信息并启动智能分析</span></div>
</div>
"""


def clean_text(value: str | None) -> str:
    return "" if value is None else str(value).strip()


def split_tags(value: str | None) -> list[str]:
    normalized = clean_text(value)
    for separator in [";", "；", "，", "|", "/", " "]:
        normalized = normalized.replace(separator, ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def build_academic_profile(grade: str | None, today: date | None = None) -> dict:
    """Translate the UI grade label to RecommendationAgent profile fields."""
    grade = clean_text(grade)
    profile = {"grade": grade}
    if grade in {"大一", "大二", "大三", "大四"}:
        profile["education_level"] = "本科"
        grade_index = {"大一": 1, "大二": 2, "大三": 3, "大四": 4}[grade]
        current = today or date.today()
        academic_year_start = current.year if current.month >= 9 else current.year - 1
        profile["enrollment_year"] = academic_year_start - (grade_index - 1)
    elif "研究生" in grade:
        profile["education_level"] = "研究生"
    return profile


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return data if isinstance(data, dict) else {}


def build_standard_input(
    user_input: str | None,
    task_type: str | None,
    data_source: str | None,
    major: str | None,
    grade: str | None,
    interests: str | None,
    skills: str | None,
    source_url: str | None,
    notification_text: str | None,
    project_json: str | None,
    material_type: str | None,
) -> dict:
    user_input = clean_text(user_input)
    task_type = clean_text(task_type) or "full_process"
    data_source = clean_text(data_source) or "local"
    notification_text = clean_text(notification_text)
    source_url = clean_text(source_url)
    project_json = clean_text(project_json)
    material_type = clean_text(material_type)
    payload: dict = {"data_source": data_source}

    if source_url:
        payload["source_url"] = source_url
    if notification_text:
        payload["notification_text"] = notification_text
    if material_type:
        payload["material_type"] = material_type
    if project_json:
        try:
            parsed_projects = json.loads(project_json)
            if isinstance(parsed_projects, dict):
                parsed_projects = [parsed_projects]
            payload["projects"] = parsed_projects
        except json.JSONDecodeError:
            payload["raw_project_text"] = project_json

    return {
        "task_id": f"web_task_{uuid4().hex[:8]}",
        "user_input": user_input,
        "task_type": task_type,
        "user_profile": {
            "major": clean_text(major),
            **build_academic_profile(grade),
            "interests": split_tags(interests),
            "skills": split_tags(skills),
        },
        "context": {},
        "input_data": payload,
        "history": [],
        "required_output": "markdown",
        "metadata": {"source": "gradio_app", "ui_version": "2.0"},
    }


def validate_form(
    user_input: str | None,
    task_type: str | None,
    data_source: str | None,
    source_url: str | None,
    notification_text: str | None,
    project_json: str | None,
    material_type: str | None,
) -> str | None:
    task = clean_text(task_type) or "full_process"
    source = clean_text(data_source) or "local"
    source_url = clean_text(source_url)
    notification_text = clean_text(notification_text)
    project_json = clean_text(project_json)
    material_type = clean_text(material_type)

    if not clean_text(user_input):
        return "请先输入你希望赛智通完成的任务。"
    if project_json:
        try:
            parsed_projects = json.loads(project_json)
        except json.JSONDecodeError as exc:
            return f"项目数据 JSON 格式不正确：第 {exc.lineno} 行第 {exc.colno} 列。"
        if not isinstance(parsed_projects, (dict, list)):
            return "项目数据 JSON 必须是一个项目对象，或由项目对象组成的列表。"
        if isinstance(parsed_projects, list) and not parsed_projects:
            return "项目数据 JSON 列表不能为空。"
        if isinstance(parsed_projects, list) and not all(isinstance(item, dict) for item in parsed_projects):
            return "项目数据 JSON 列表中的每一项都必须是项目对象。"

    if task == "info_extract" and not notification_text:
        return "信息抽取任务需要在“通知原文”中粘贴待抽取内容。"
    if source in {"web", "mixed"} and not source_url:
        return "选择“公开网页”后，请填写需要采集的网页 URL。"
    if source in {"upload", "mixed"} and not notification_text:
        return "选择“上传或粘贴文本”后，请粘贴需要处理的原始文本。"
    if source == "local" and task in {"full_process", "recommendation", "material"} and not project_json:
        return "本地项目库尚未配置自动读取；请在“高级输入”中填写项目数据 JSON，或改用“上传或粘贴文本”。"
    if task == "info_collect" and source == "upload":
        return "粘贴的通知文本已经是原始信息，请将任务类型改为“通知信息抽取”或“全流程辅助”。"
    if task == "material" and not material_type:
        return "材料生成任务请在“高级输入”中选择材料类型；全流程任务也可选择“自动识别”。"
    return None


def update_source_inputs(data_source: str | None):
    """Show only the source-specific inputs needed by the selected mode."""
    source = clean_text(data_source) or "local"
    return (
        gr.update(visible=source in {"web", "mixed"}),
        gr.update(visible=source in {"upload", "mixed"}),
    )


def build_status_html(status: str, message: str | None = None) -> str:
    labels = {
        "ready": "等待启动",
        "success": "分析完成",
        "partial": "部分完成",
        "need_input": "需要补充信息",
        "failed": "执行失败",
    }
    safe_status = status if status in labels else "ready"
    detail = html.escape(message or labels[safe_status])
    return (
        f'<div class="szt-status {safe_status}"><span class="szt-status-dot"></span>'
        f'<div><strong>{labels[safe_status]}</strong><br><small>{detail}</small></div></div>'
    )


def build_status_rows(agent_results: list[dict]) -> list[list[str]]:
    status_labels = {
        "success": "已完成",
        "partial": "部分完成",
        "need_input": "待补充",
        "failed": "失败",
        "skipped": "未执行",
    }
    return [
        [
            item.get("agent_name", ""),
            status_labels.get(item.get("status"), item.get("status", "")),
            item.get("message", ""),
        ]
        for item in agent_results or []
    ]


CHAT_WELCOME = (
    "你好，我是赛智通。你可以直接告诉我目标，例如：\n\n"
    "- 我是计算机专业大三学生，想参加国家级人工智能竞赛\n"
    "- 帮我从这份竞赛通知中提取要求并推荐\n"
    "- 根据刚才推荐的项目生成报名材料\n\n"
    "信息不完整时，我会一次追问一项，并在本次对话中持续记住。"
)


def new_chat_state() -> dict[str, Any]:
    return {
        "intent": "",
        "major": "",
        "grade": "",
        "interests": [],
        "skills": [],
        "competition_type": "",
        "competition_level": "",
        "notification_text": "",
        "project_name": "",
        "material_type": "",
        "last_result": {},
        "turns": [],
    }


def initial_chat_messages() -> list[dict[str, str]]:
    return [{"role": "assistant", "content": CHAT_WELCOME}]


def _update_chat_state(state: dict[str, Any], message: str) -> dict[str, Any]:
    state = {**new_chat_state(), **(state or {})}
    text = clean_text(message)
    state["turns"] = [*state.get("turns", []), text]

    if any(word in text for word in ["材料", "申报", "报名表", "简历", "计划书", "PPT"]):
        state["intent"] = "material"
    elif any(word in text for word in ["竞赛", "比赛", "推荐", "项目"]):
        state["intent"] = state.get("intent") or "recommendation"

    major_aliases = {
        "计算机": "计算机科学与技术", "软件": "软件工程", "人工智能": "人工智能",
        "数据科学": "数据科学与大数据技术", "电子信息": "电子信息工程",
        "自动化": "自动化", "金融": "金融学", "工商管理": "工商管理",
    }
    for keyword, normalized in major_aliases.items():
        if keyword in text and (
            any(marker in text for marker in ["专业", "学生", "我是", "学的"])
            or len(text) <= 30
        ):
            state["major"] = normalized
            break

    for grade in ["大一", "大二", "大三", "大四", "研究生"]:
        if grade in text:
            state["grade"] = grade
            break

    for level in ["国际级", "国家级", "省级", "校级"]:
        if level in text:
            state["competition_level"] = level
            break

    type_aliases = {
        "人工智能": "人工智能", "AI": "人工智能", "算法": "算法与程序设计",
        "程序设计": "算法与程序设计", "创新创业": "创新创业", "创业": "创新创业",
        "科研": "科研学术", "数据分析": "数据分析", "数学建模": "数学建模",
    }
    for keyword, normalized in type_aliases.items():
        if keyword in text:
            state["competition_type"] = normalized
            if normalized not in state["interests"]:
                state["interests"] = [*state["interests"], normalized]
            break

    known_skills = ["Python", "Java", "C++", "机器学习", "深度学习", "数据分析", "文案写作", "团队协作"]
    for skill in known_skills:
        if skill.lower() in text.lower() and skill not in state["skills"]:
            state["skills"] = [*state["skills"], skill]

    if len(text) >= 80 or ("通知" in text and any(word in text for word in ["截止", "报名", "参赛"])):
        state["notification_text"] = text

    if "项目名称" in text or "竞赛名称" in text:
        separator = "：" if "：" in text else ":"
        if separator in text:
            state["project_name"] = text.split(separator, 1)[1].strip()

    material_map = {
        "报名表": "generic_application_form", "报名简历": "generic_application_form",
        "简历": "generic_application_form", "计划书": "innovation_contest_business_plan",
        "PPT": "generic_ppt", "进度表": "generic_schedule", "清单": "challenge_cup_grand_checklist",
    }
    for keyword, material_type in material_map.items():
        if keyword in text:
            state["material_type"] = material_type
            break
    return state


def _next_chat_question(state: dict[str, Any]) -> str | None:
    if not state.get("intent"):
        return "你希望我帮你推荐竞赛，还是为已有项目生成申报材料？"
    if not state.get("major"):
        return "先告诉我你的专业是什么？例如：计算机科学与技术。"
    if not state.get("grade"):
        return "你目前是大几或研究生阶段？这会影响参赛资格判断。"
    if state["intent"] == "recommendation":
        if not state.get("competition_type"):
            return "你更想参加哪类竞赛？例如人工智能、算法、数学建模或创新创业。"
        if not state.get("competition_level"):
            return "你倾向校级、省级、国家级还是国际级竞赛？"
        if not state.get("skills"):
            return "你目前掌握哪些技能？例如 Python、C++、算法、机器学习或团队协作。"
        if not state.get("skills"):
            return "你目前掌握哪些技能？例如 Python、C++、算法、机器学习或团队协作。"
    if state["intent"] == "material":
        has_previous = bool(state.get("last_result"))
        if not state.get("notification_text") and not state.get("project_name") and not has_previous:
            return "请粘贴竞赛通知全文，或按“项目名称：XXX”告诉我具体项目。"
        if not state.get("material_type"):
            return "你想生成哪种材料？例如报名表、报名简历、计划书、PPT 或材料清单。"
    return None


def _chat_standard_input(state: dict[str, Any], message: str) -> dict:
    profile = {
        "major": state.get("major", ""),
        **build_academic_profile(state.get("grade", "")),
        "interests": state.get("interests", []),
        "skills": state.get("skills", []),
        "competition_level": state.get("competition_level", ""),
    }
    payload: dict[str, Any] = {}
    task_type = state.get("intent") or "recommendation"
    notification = state.get("notification_text", "")
    if notification:
        payload.update({"data_source": "upload", "notification_text": notification})
    else:
        payload.update({"data_source": "web", "source_url": "https://www.saikr.com/"})

    if state.get("competition_type"):
        payload["keywords"] = [state["competition_type"], state.get("competition_level", "")]
    if state.get("material_type"):
        payload["material_type"] = state["material_type"]
    if state.get("project_name"):
        payload["project_info"] = {
            "project_name": state["project_name"],
            "background": "根据对话收集的信息生成申报材料初稿。",
        }

    last_result = state.get("last_result", {})
    if task_type == "material" and not payload.get("project_info") and isinstance(last_result, dict):
        for agent_result in last_result.get("data", {}).get("agent_results", []):
            recommendations = agent_result.get("data", {}).get("recommendations", [])
            if recommendations:
                payload["project_info"] = {
                    "project_name": recommendations[0].get("title", "推荐项目"),
                    "background": recommendations[0].get("reason", "根据上一轮推荐结果生成。"),
                }
                break

    return {
        "task_id": f"chat_task_{uuid4().hex[:8]}",
        "user_input": "；".join(state.get("turns", [])) or message,
        "task_type": task_type,
        "user_profile": profile,
        "context": {"conversation_turns": state.get("turns", [])},
        "input_data": payload,
        "history": [],
        "required_output": "markdown",
        "metadata": {"source": "gradio_chat", "ui_version": "3.0"},
    }


def _result_downloads(result: dict) -> list[str]:
    downloads = []
    for agent_result in result.get("data", {}).get("agent_results", []):
        for path in agent_result.get("data", {}).get("_saved_files", []) or []:
            if Path(path).is_file():
                downloads.append(str(Path(path).resolve()))
    return downloads


def _chat_result_text(result: dict) -> str:
    lines = []
    for item in result.get("data", {}).get("agent_results", []):
        data = item.get("data", {})
        recommendations = data.get("recommendations", [])
        if recommendations:
            lines.append("### 推荐结果")
            for index, recommendation in enumerate(recommendations, 1):
                title = recommendation.get("title", "未命名项目")
                url = recommendation.get("source_url", "")
                title_display = f"[{title}]({url})" if url else f"**{title}**"
                summary = str(recommendation.get("summary", "")).strip()
                metadata = []
                if recommendation.get("deadline") not in {None, "", "unknown"}:
                    metadata.append(f"截止日期：{recommendation['deadline']}")
                if recommendation.get("organizer") not in {None, "", "unknown"}:
                    metadata.append(f"主办方：{recommendation['organizer']}")
                lines.append(
                    f"{index}. {title_display} "
                    f"（匹配分 {recommendation.get('match_score', '-')}）\n"
                    f"   {summary or recommendation.get('reason', '暂无简介')}"
                    + (f"\n   {'；'.join(metadata)}" if metadata else "")
                    + (f"\n   推荐理由：{recommendation.get('reason', '')}" if summary else "")
                )
        if data.get("material_name"):
            lines.append(f"### 材料已生成\n{data['material_name']} 已生成，可在下方下载并人工复核。")
    return "\n\n".join(lines) or result.get("data", {}).get("final_answer", "任务已完成。")


def chat_submit(message, history, state):
    message = clean_text(message)
    history = list(history or initial_chat_messages())
    state = state or new_chat_state()
    if not message:
        return "", history, state, build_status_html("ready"), EMPTY_RESULT, [], {}, []

    history.append({"role": "user", "content": message})
    followup = (
        MainAgent(config=load_config()).handle_followup(message, state["last_result"])
        if state.get("last_result")
        else None
    )
    if followup:
        answer = followup.get("data", {}).get("final_answer", followup.get("message", ""))
        state["turns"] = [*state.get("turns", []), message]
        history.append({"role": "assistant", "content": answer})
        return "", history, state, build_status_html(followup.get("status", "success"), followup.get("message")), answer, [], followup, _result_downloads(state["last_result"])
    state = _update_chat_state(state, message)
    question = _next_chat_question(state)
    if question:
        history.append({"role": "assistant", "content": question})
        snapshot = {key: value for key, value in state.items() if key not in {"last_result", "turns"}}
        return "", history, state, build_status_html("need_input", question), f"**已记录信息**\n\n```json\n{json.dumps(snapshot, ensure_ascii=False, indent=2)}\n```", [], snapshot, []

    standard_input = _chat_standard_input(state, message)
    result = MainAgent(config=load_config()).run(standard_input)
    state["last_result"] = result
    answer = _chat_result_text(result)
    downloads = _result_downloads(result)
    if downloads:
        answer += "\n\n文件已经生成，可在右侧下载。提交前请人工核对个人信息和竞赛要求。"
    history.append({"role": "assistant", "content": answer})
    rows = build_status_rows(result.get("data", {}).get("agent_results", []))
    return "", history, state, build_status_html(result.get("status", "failed"), result.get("message")), answer, rows, result, downloads


def clear_chat():
    return initial_chat_messages(), new_chat_state(), build_status_html("ready", "开始描述你的目标"), EMPTY_RESULT, [], {}, []


def run_main_agent(
    user_input: str | None,
    task_type: str | None,
    data_source: str | None,
    major: str | None,
    grade: str | None,
    interests: str | None,
    skills: str | None,
    source_url: str | None,
    notification_text: str | None,
    project_json: str | None,
    material_type: str | None,
) -> tuple[str, str, list[list[str]], dict]:
    validation_error = validate_form(
        user_input, task_type, data_source, source_url, notification_text, project_json, material_type
    )
    if validation_error:
        result = {"status": "need_input", "message": validation_error}
        return build_status_html("need_input", validation_error), f">提示：{validation_error}", [], result

    try:
        standard_input = build_standard_input(
            user_input, task_type, data_source, major, grade, interests, skills,
            source_url, notification_text, project_json, material_type,
        )
        result = MainAgent(config=load_config()).run(standard_input)
        data = result.get("data", {})
        rows = build_status_rows(data.get("agent_results", []))
        final_answer = data.get("final_answer") or "任务已执行，但暂无可展示的结果。"
        status = result.get("status", "failed")
        message = result.get("message", "")
        return build_status_html(status, message), final_answer, rows, result
    except Exception as exc:
        error_result = {
            "task_id": "ui_error",
            "agent_name": "GradioApp",
            "status": "failed",
            "data": {},
            "message": "页面回调执行失败。",
            "error": {"type": exc.__class__.__name__, "message": str(exc)},
            "next_action": "检查输入或后端日志后重试。",
            "metadata": {},
        }
        return build_status_html("failed", str(exc)), f"执行失败：{exc}", [], error_result


def run_main_agent_with_downloads(*args):
    status, answer, rows, result = run_main_agent(*args)
    return status, answer, rows, result, _result_downloads(result)


def load_demo() -> tuple[str, str, str, str, str, str, str, str, str, str, str]:
    return (
        "请根据我的专业、兴趣和技能，推荐适合的科研或竞赛项目，并生成申报准备清单。",
        "full_process", "upload", "计算机科学与技术", "大三",
        "人工智能，数据分析，创新创业", "Python，机器学习，团队协作", "",
        (
            "关于举办2026年“挑战杯”大学生课外学术科技作品竞赛的通知。\n"
            "参赛对象：全日制在校大学生，可组成3至5人团队。\n"
            "作品方向：人工智能、数据分析、社会治理与科技创新。\n"
            "报名截止时间：2026年9月30日。\n"
            "申报要求：提交项目申报书、研究报告、团队介绍及相关证明材料。"
        ),
        "", "challenge_cup_grand_checklist",
    )


def create_interface():
    if gr is None:
        raise RuntimeError("未安装 Gradio，请先运行 pip install -r requirements.txt")

    theme = gr.themes.Soft(
        primary_hue="blue",
        secondary_hue="teal",
        neutral_hue="slate",
        radius_size="lg",
        spacing_size="md",
    )

    gradio_major = int(str(getattr(gr, "__version__", "4")).split(".")[0])
    blocks_kwargs = {"title": "赛智通 · 科研竞赛智能辅助平台"}
    if gradio_major < 6:
        blocks_kwargs.update({"theme": theme, "css": APP_CSS})

    with gr.Blocks(**blocks_kwargs) as demo:
        with gr.Column(elem_classes=["szt-shell"]):
            gr.HTML(HERO_HTML)

            gr.HTML('<div class="szt-section-title"><h3>对话式竞赛助手</h3><p>像聊天一样补充信息，系统会记住上下文并在信息齐全后自动执行</p></div>')
            chat_state = gr.State(new_chat_state())
            with gr.Row(equal_height=False, elem_classes=["szt-main-grid"]):
                with gr.Column(scale=7, min_width=560, elem_classes=["szt-card", "szt-panel"]):
                    chatbot = gr.Chatbot(
                        value=initial_chat_messages(),
                        height=560,
                        layout="bubble",
                        label="赛智通对话",
                        placeholder="告诉我你的专业、年级和想参加的竞赛，我会逐步追问。",
                    )
                    with gr.Row():
                        chat_input = gr.Textbox(
                            placeholder="例如：我是计算机专业，想找国家级人工智能竞赛",
                            show_label=False,
                            scale=8,
                        )
                        chat_send = gr.Button("发送", variant="primary", scale=1)
                    chat_clear = gr.Button("开始新对话", elem_classes=["szt-secondary"])
                with gr.Column(scale=5, min_width=460, elem_classes=["szt-card", "szt-panel"]):
                    chat_status = gr.HTML(build_status_html("ready", "开始描述你的目标"))
                    chat_answer = gr.Markdown(EMPTY_RESULT, elem_classes=["szt-result"])
                    chat_downloads = gr.File(
                        label="生成材料下载",
                        file_count="multiple",
                        interactive=False,
                    )
                    with gr.Accordion("执行详情", open=False):
                        chat_agent_statuses = gr.Dataframe(
                            headers=["Agent", "执行状态", "执行说明"],
                            datatype=["str", "str", "str"],
                            value=[], interactive=False, wrap=True,
                        )
                        chat_raw_output = gr.JSON(value={}, label="完整运行数据")

            gr.HTML('<div class="szt-section-title" style="margin-top:24px"><h3>高级表单模式</h3><p>需要精确指定数据源、材料模板或调试 Agent 时使用</p></div>')

            with gr.Row(equal_height=False, elem_classes=["szt-main-grid"]):
                with gr.Column(scale=6, min_width=460, elem_classes=["szt-card", "szt-panel", "szt-input-panel"]):
                    gr.HTML('<div class="szt-section-title"><h3>创建任务</h3><p>描述你的目标，系统将自动调度合适的 Agent</p></div>')
                    user_input = gr.Textbox(
                        label="你希望完成什么？",
                        placeholder="例如：请根据我的背景推荐 3 个适合的竞赛，并给出申报准备清单……",
                        lines=5,
                    )
                    with gr.Row():
                        task_type = gr.Dropdown(TASK_TYPE_CHOICES, value="full_process", label="任务类型")
                        data_source = gr.Dropdown(DATA_SOURCE_CHOICES, value="local", label="数据来源")

                    with gr.Column(visible=False, elem_classes=["szt-source-box"]) as web_source_group:
                        gr.HTML('<div class="szt-section-title"><h3>公开网页地址</h3><p>填写竞赛官网、学校通知或公开政策页面的完整 URL</p></div>')
                        source_url = gr.Textbox(
                            label="网页 URL",
                            placeholder="https://example.edu.cn/notice/competition",
                        )

                    with gr.Column(visible=False, elem_classes=["szt-source-box"]) as text_source_group:
                        gr.HTML('<div class="szt-section-title"><h3>原始文本内容</h3><p>粘贴通知、竞赛简章或其他需要处理的正文</p></div>')
                        notification_text = gr.Textbox(
                            label="粘贴文本",
                            placeholder="请在这里粘贴完整的通知正文……",
                            lines=8,
                        )

                    gr.HTML('<div class="szt-section-title" style="margin-top:8px"><h3>用户画像</h3><p>信息越完整，项目匹配和材料建议越准确</p></div>')
                    with gr.Row():
                        major = gr.Textbox(label="专业", placeholder="例如：计算机科学与技术")
                        grade = gr.Dropdown(["大一", "大二", "大三", "大四", "研究生"], value="大三", label="年级", allow_custom_value=True)
                    interests = gr.Textbox(label="兴趣方向", placeholder="多个方向用逗号分隔，如：AI，数据分析")
                    skills = gr.Textbox(label="能力与技能", placeholder="如：Python，机器学习，文案写作")

                    with gr.Accordion("高级输入 · 结构化项目数据", open=False):
                        project_json = gr.Textbox(label="项目数据 JSON", placeholder='[{"name": "项目名称", "deadline": "2026-09-30"}]', lines=5)
                        material_type = gr.Dropdown(
                            MATERIAL_TYPE_CHOICES,
                            value="",
                            label="材料类型",
                            info="全流程可自动识别；单独生成材料时建议明确选择。",
                        )

                    gr.HTML('<div class="szt-tip"><strong>隐私提示</strong>：请勿输入身份证号、密码等敏感信息。申报材料仅作为辅助初稿，提交前请人工复核。</div>')
                    with gr.Row():
                        demo_button = gr.Button("填入演示案例", elem_classes=["szt-secondary"])
                        clear_button = gr.ClearButton(value="清空重填", elem_classes=["szt-secondary"])
                    run_button = gr.Button("启动智能分析  →", variant="primary", elem_classes=["szt-primary"])

                with gr.Column(scale=7, min_width=560, elem_classes=["szt-card", "szt-panel", "szt-workbench"]):
                    gr.HTML('<div class="szt-section-title"><h3>智能体工作台</h3><p>实时查看调度状态、整合结果与完整执行数据</p></div>')
                    status = gr.HTML(build_status_html("ready", "完善左侧信息后启动分析"))
                    with gr.Tabs():
                        with gr.Tab("综合结果"):
                            final_answer = gr.Markdown(EMPTY_RESULT, elem_classes=["szt-result"])
                        with gr.Tab("Agent 执行轨迹"):
                            agent_statuses = gr.Dataframe(
                                headers=["Agent", "执行状态", "执行说明"],
                                datatype=["str", "str", "str"],
                                value=[], interactive=False, wrap=True,
                                elem_classes=["szt-agent-table"],
                            )
                        with gr.Tab("完整运行数据"):
                            raw_output = gr.JSON(value={}, label="JSON 调试输出", elem_classes=["json-holder"])
                        with gr.Tab("材料下载"):
                            form_downloads = gr.File(
                                label="生成文件",
                                file_count="multiple",
                                interactive=False,
                            )

            gr.HTML('<div class="szt-footer">赛智通 SaiZhiTong · 大学生科研竞赛多智能体辅助系统</div>')

        form_components = [user_input, task_type, data_source, major, grade, interests, skills, source_url, notification_text, project_json, material_type]
        run_button.click(fn=run_main_agent_with_downloads, inputs=form_components, outputs=[status, final_answer, agent_statuses, raw_output, form_downloads])
        demo_button.click(fn=load_demo, outputs=form_components)
        data_source.change(
            fn=update_source_inputs,
            inputs=[data_source],
            outputs=[web_source_group, text_source_group],
        )
        clear_button.add(form_components + [status, final_answer, agent_statuses, raw_output, form_downloads])

        chat_outputs = [chat_input, chatbot, chat_state, chat_status, chat_answer, chat_agent_statuses, chat_raw_output, chat_downloads]
        chat_send.click(
            fn=chat_submit,
            inputs=[chat_input, chatbot, chat_state],
            outputs=chat_outputs,
        )
        chat_input.submit(
            fn=chat_submit,
            inputs=[chat_input, chatbot, chat_state],
            outputs=chat_outputs,
        )
        chat_clear.click(
            fn=clear_chat,
            outputs=[chatbot, chat_state, chat_status, chat_answer, chat_agent_statuses, chat_raw_output, chat_downloads],
        )

    return demo, theme, gradio_major


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行赛智通 Gradio 演示系统。")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "7860")))
    parser.add_argument("--share", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    demo, theme, gradio_major = create_interface()
    launch_kwargs = {
        "server_name": args.host,
        "server_port": args.port,
        "share": args.share,
        "prevent_thread_lock": True,
    }
    if gradio_major >= 6:
        launch_kwargs.update({"theme": theme, "css": APP_CSS})
    demo.launch(**launch_kwargs)
    # Keep the process alive consistently in terminals and hidden/background
    # launches. Gradio 6 may otherwise return immediately in a detached process.
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        demo.close()


if __name__ == "__main__":
    main()
