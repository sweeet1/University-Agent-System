from __future__ import annotations

import argparse
import html
import json
import os
import re
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
    ("竞赛报名个人简历", "generic_personal_resume"),
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
    "你好，我是赛智通。无论你是想找合适的竞赛、看懂一份竞赛通知，"
    "还是准备报名材料，都可以直接用自己的话告诉我。\n\n"
    "比如你可以说：\n\n"
    "- 我是计算机专业大三学生，想找国家级人工智能竞赛\n"
    "- 帮我整理这份竞赛通知，看看我是否适合参加\n"
    "- 根据刚才推荐的第二个比赛生成报名材料\n\n"
    "如果还缺少关键信息，我会结合你已经说过的内容和你一起补充，不用按固定格式填写。"
)


def new_chat_state() -> dict[str, Any]:
    return {
        "intent": "",
        "major": "",
        "grade": "",
        "interests": [],
        "skills": [],
        "skills_skipped": False,
        "skill_gaps": [],
        "competition_type": "",
        "competition_type_confirmed": False,
        "competition_scope": "",
        "excluded_competition_types": [],
        "competition_level": "",
        "competition_level_confirmed": False,
        "preferred_levels": [],
        "acceptable_levels": [],
        "excluded_levels": [],
        "development_goals": [],
        "available_time_per_week": None,
        "team_preference": "",
        "last_acknowledgement": "",
        "input_role": "",
        "dialogue_action": "",
        "response_mode": "",
        "recommendation_options": {},
        "conversation_summary": "",
        "notification_text": "",
        "project_name": "",
        "material_type": "",
        "last_result": {},
        "turns": [],
    }


def initial_chat_messages() -> list[dict[str, str]]:
    return [{"role": "assistant", "content": CHAT_WELCOME}]


def _recommendations_from_chat_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    result = state.get("last_result", {})
    if not isinstance(result, dict):
        return []
    for agent_result in result.get("data", {}).get("agent_results", []):
        recommendations = agent_result.get("data", {}).get("recommendations", [])
        if isinstance(recommendations, list) and recommendations:
            return [item for item in recommendations if isinstance(item, dict)]
    return []


def _detect_chat_intent(text: str, current_intent: str = "") -> str:
    """Classify task intent with transition keywords taking precedence."""
    if len(text) >= 80 and current_intent in {
        "extract", "recommendation", "material", "full_process"
    }:
        # A long pasted notice is task input, not a request to switch agents.
        return current_intent
    strong_material_words = ["报名表", "简历", "计划书", "PPT", "材料清单"]
    general_material_words = ["材料", "资料", "文档", "申报书"]
    generation_words = ["生成", "制作", "撰写", "写一份", "准备", "帮我做", "想要"]
    recommendation_words = ["推荐", "匹配", "适合", "筛选", "重新找", "换一批"]
    extraction_words = ["提取", "抽取", "解析", "整理通知", "报名要求"]
    collection_words = ["收集", "搜集", "查找", "搜索", "查询竞赛", "有哪些竞赛"]

    cancels_material = any(
        phrase in text
        for phrase in ["不生成材料", "不要材料", "不做材料", "先不做材料", "取消材料"]
    )
    wants_material = not cancels_material and (
        any(word in text for word in strong_material_words)
        or (
            any(word in text for word in general_material_words)
            and any(word in text for word in generation_words)
        )
    )
    wants_recommendation = any(word in text for word in recommendation_words)
    requests_new_recommendation = wants_recommendation and not any(
        phrase in text for phrase in ["刚才推荐", "之前推荐", "上面推荐", "推荐的"]
    )
    if cancels_material and any(word in text for word in ["推荐", "竞赛", "比赛"]):
        return "recommendation"
    if "全流程" in text or (wants_material and requests_new_recommendation):
        return "full_process"
    if wants_material:
        return "material"
    if any(word in text for word in extraction_words):
        return "extract"
    if any(word in text for word in collection_words):
        return "collect"
    if requests_new_recommendation or any(word in text for word in ["竞赛", "比赛", "项目"]):
        return "recommendation"
    return current_intent


def _select_recommended_project(state: dict[str, Any], text: str) -> dict[str, Any] | None:
    recommendations = _recommendations_from_chat_state(state)
    if not recommendations:
        return None
    ordinal_markers = {
        "第一个": 0, "第一项": 0, "第1个": 0,
        "第二个": 1, "第二项": 1, "第2个": 1,
        "第三个": 2, "第三项": 2, "第3个": 2,
    }
    for marker, index in ordinal_markers.items():
        if marker in text and index < len(recommendations):
            return recommendations[index]
    for recommendation in recommendations:
        title = str(recommendation.get("title", ""))
        if title and (title in text or any(token in text for token in re.findall(r"[\u4e00-\u9fff]{3,}", title))):
            return recommendation
    if len(recommendations) == 1 and any(word in text for word in ["刚才", "这个", "该竞赛", "该项目"]):
        return recommendations[0]
    return None


def _correction_value_text(text: str) -> str:
    """Keep only the replacement clause when the user corrects prior information."""
    for marker in ["改成", "更正为", "应该是"]:
        if marker in text:
            return text.rsplit(marker, 1)[1].strip(" ，。！？：:") or text
    match = re.search(r"不是.+?[，,；;\s]+(?:专业)?(?:是|改成)(.+)$", text)
    if match:
        return match.group(1).strip(" ，。！？：:") or text
    return text


def _contains_negated_term(text: str, term: str) -> bool:
    escaped = re.escape(term)
    patterns = [
        rf"(?:不会|不擅长|不熟悉|不想|不要|不考虑|排除|避开)\s*{escaped}",
        rf"除了\s*{escaped}\s*(?:以外)?(?:都|之外)",
    ]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _append_unique(values: list[str], value: str) -> list[str]:
    return values if value in values else [*values, value]


def _looks_like_notification(text: str) -> bool:
    """Return True only when the text carries at least one structural signal that
    suggests it is a pasted competition notice, not just a long chat message
    listing skills or describing background."""
    notification_indicators = [
        # URL
        r"https?://",
        # date patterns
        r"\d{4}年\d{1,2}月\d{1,2}日",
        r"\d{4}-\d{1,2}-\d{1,2}",
        r"\d{4}/\d{1,2}/\d{1,2}",
        # competition structural keywords
        r"主办方", r"承办方", r"协办方", r"主办单位", r"承办单位",
        r"参赛对象", r"参赛资格", r"作品要求", r"申报材料",
        r"报名方式", r"报名截止", r"竞赛简介", r"奖项设置",
        r"关于举办", r"通知", r"公告",
    ]
    return any(re.search(indicator, text) for indicator in notification_indicators)


def _looks_like_complete_notification(text: str) -> bool:
    """Require enough notice structure to distinguish pasted input from a short request."""
    if not _looks_like_notification(text):
        return False
    structural_markers = [
        "主办单位", "主办方", "参赛对象", "参赛资格", "申报材料",
        "报名方式", "报名截止", "作品要求", "奖项设置",
    ]
    marker_count = sum(marker in text for marker in structural_markers)
    has_date = bool(
        re.search(
            r"\d{4}年\d{1,2}月\d{1,2}日|\d{4}[-/]\d{1,2}[-/]\d{1,2}",
            text,
        )
    )
    return len(text) >= 80 or (
        len(text) >= 50 and marker_count >= 2 and has_date
    )


def _update_chat_state(
    state: dict[str, Any],
    message: str,
    understanding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = {**new_chat_state(), **(state or {})}
    previous_major = str(state.get("major") or "").strip()
    previous_intent = str(state.get("intent") or "").strip()
    text = clean_text(message)
    is_notification = _looks_like_complete_notification(text)
    protected_profile = {
        key: state.get(key)
        for key in [
            "major", "grade", "interests", "skills", "skills_skipped", "skill_gaps",
            "competition_type", "competition_type_confirmed", "competition_scope",
            "excluded_competition_types", "competition_level",
            "competition_level_confirmed", "preferred_levels", "acceptable_levels",
            "excluded_levels", "development_goals", "available_time_per_week",
            "team_preference", "last_result", "recommendation_options",
        ]
    }
    fact_text = _correction_value_text(text)
    state["turns"] = [*state.get("turns", []), text][-8:]
    state["last_acknowledgement"] = ""

    state["intent"] = _detect_chat_intent(fact_text, state.get("intent", ""))

    selected_project = _select_recommended_project(state, fact_text)
    if selected_project:
        state["project_name"] = str(selected_project.get("title", ""))

    major_aliases = {
        "计算机科学与技术": "计算机科学与技术", "计科": "计算机科学与技术", "计算机": "计算机科学与技术",
        "软件工程": "软件工程", "软工": "软件工程", "软件": "软件工程", "人工智能": "人工智能",
        "数据科学": "数据科学与大数据技术", "电子信息": "电子信息工程",
        "自动化": "自动化", "金融": "金融学", "工商管理": "工商管理",
        "网络工程": "网络工程", "电子商务": "电子商务", "市场营销": "市场营销",
        "通信工程": "通信工程", "机械工程": "机械工程", "数学": "数学类",
    }
    for keyword, normalized in major_aliases.items():
        short_major_answer = fact_text.strip() in {keyword, f"{keyword}专业"}
        grade_near_major = re.search(
            rf"(?:大[一二三四]|研[一二三]|研究生)\s*{re.escape(keyword)}|"
            rf"{re.escape(keyword)}\s*(?:专业|大[一二三四]|研[一二三]|研究生|20\d{{2}}级)",
            fact_text,
        )
        if keyword in fact_text and (
            any(marker in fact_text for marker in ["专业", "学生", "我是", "学的"])
            or grade_near_major
            or short_major_answer
        ):
            state["major"] = normalized
            break

    research_grade_map = {
        "研一": "研究生", "研二": "研究生", "研三": "研究生",
        "硕士": "研究生", "博士": "研究生",
    }
    for marker, normalized in research_grade_map.items():
        if marker in fact_text:
            state["grade"] = normalized
            break
    for grade in ["大一", "大二", "大三", "大四", "研究生"]:
        if grade in fact_text:
            state["grade"] = grade
            break

    enrollment_match = re.search(r"(20\d{2})\s*级", fact_text)
    if enrollment_match and not state.get("grade"):
        year_index = max(1, date.today().year - int(enrollment_match.group(1)))
        state["grade"] = {1: "大一", 2: "大二", 3: "大三"}.get(year_index, "大四")

    for level in ["国际级", "国家级", "省级", "校级"]:
        if level in fact_text:
            state["competition_level"] = level
            state["competition_level_confirmed"] = True
            state["preferred_levels"] = _append_unique(state.get("preferred_levels", []), level)
            break

    for level in ["国际级", "国家级", "省级", "校级"]:
        if _contains_negated_term(fact_text, level):
            state["excluded_levels"] = _append_unique(state.get("excluded_levels", []), level)
            state["preferred_levels"] = [item for item in state.get("preferred_levels", []) if item != level]
    if any(phrase in fact_text for phrase in [
        "没有硬性要求", "级别都可以", "不限级别", "级别不限", "什么级别都行", "级别无所谓",
    ]):
        state["competition_level"] = ""
        state["competition_level_confirmed"] = True

    type_aliases = {
        "人工智能": "人工智能", "AI": "人工智能", "算法": "算法与程序设计",
        "程序设计": "算法与程序设计", "创新创业": "创新创业", "创业": "创新创业",
        "科研": "科研学术", "数据分析": "数据分析", "数据挖掘": "数据分析",
        "机器学习": "人工智能", "深度学习": "人工智能", "数学建模": "数学建模",
        "营销策划": "商业与营销", "市场营销": "商业与营销", "控制类": "自动化与控制",
        "电子设计": "电子设计", "机器人": "机器人", "后端开发": "软件开发",
    }
    # Only set competition_type from type_aliases when it hasn't been set yet,
    # or when the user is explicitly correcting it.  This prevents a skill
    # keyword like "数据分析" or "算法" from overwriting the competition
    # direction the user stated earlier (e.g. "人工智能").
    if not state.get("competition_type") or any(
        marker in fact_text for marker in ["不是", "改成", "更正", "应该是", "换成", "改为"]
    ):
        for keyword, normalized in type_aliases.items():
            if keyword in fact_text:
                if _contains_negated_term(fact_text, keyword):
                    state["excluded_competition_types"] = _append_unique(
                        state.get("excluded_competition_types", []), normalized
                    )
                    continue
                state["competition_type"] = normalized
                state["competition_type_confirmed"] = True
                if normalized not in state["interests"]:
                    state["interests"] = [*state["interests"], normalized]
                break

    if any(phrase in fact_text for phrase in [
        "方向没有偏好", "方向都可以", "不限方向", "方向不限", "什么方向都行",
    ]):
        state["competition_type"] = ""
        state["competition_type_confirmed"] = True

    known_skills = [
        "Python", "Java", "C++", "PyTorch", "SQL", "MATLAB", "Go", "Linux",
        "机器学习", "深度学习", "数据分析", "文案写作", "团队协作",
    ]
    for skill in known_skills:
        if skill.lower() not in fact_text.lower():
            continue
        if _contains_negated_term(fact_text, skill):
            state["skill_gaps"] = _append_unique(state.get("skill_gaps", []), skill)
            state["skills"] = [item for item in state["skills"] if item != skill]
        elif skill not in state["skills"]:
            state["skills"] = [*state["skills"], skill]

    if state.get("intent") in {"recommendation", "full_process"} and any(
        phrase in fact_text
        for phrase in [
            "暂时没有技能", "没有特别擅长", "还不清楚擅长", "不知道擅长", "没什么技能",
            "不清楚自己擅长", "暂时不清楚", "还不知道自己会什么",
        ]
    ):
        state["skills_skipped"] = True

    goal_aliases = {
        "保研": "保研", "推免": "保研", "考研": "考研", "留学": "留学",
        "就业": "就业", "找工作": "就业", "创业": "创业", "兴趣": "兴趣提升",
    }
    for keyword, normalized in goal_aliases.items():
        if keyword in fact_text:
            state["development_goals"] = _append_unique(state.get("development_goals", []), normalized)

    time_match = re.search(r"每周(?:大概|大约|能|可以|可)?\s*(\d+(?:\.\d+)?)\s*(?:个)?小时", fact_text)
    if time_match:
        state["available_time_per_week"] = float(time_match.group(1))

    if any(phrase in fact_text for phrase in ["最好个人赛", "偏好个人赛", "想参加个人赛", "不要组队", "不想组队"]):
        state["team_preference"] = "个人赛"
    elif any(phrase in fact_text for phrase in ["团队赛", "组队参加", "想组队", "有团队"]):
        state["team_preference"] = "团队赛"

    if is_notification:
        state["notification_text"] = text

    if "项目名称" in fact_text or "竞赛名称" in fact_text:
        separator = "：" if "：" in fact_text else ":"
        if separator in fact_text:
            state["project_name"] = fact_text.split(separator, 1)[1].strip()

    material_map = {
        "报名简历": "generic_personal_resume", "个人简历": "generic_personal_resume",
        "简历": "generic_personal_resume", "报名表": "generic_application_form",
        "项目申报书": "generic_application_form", "申报书": "generic_application_form",
        "申报表": "generic_application_form",
        "计划书": "innovation_contest_business_plan",
        "PPT": "generic_ppt", "进度表": "generic_schedule", "清单": "challenge_cup_grand_checklist",
    }
    for keyword, material_type in material_map.items():
        if keyword in fact_text:
            state["material_type"] = material_type
            break
    if understanding:
        state = _apply_turn_understanding(state, understanding)
    if is_notification:
        state.update(protected_profile)
        state["input_role"] = "competition_notice"
        state["notification_text"] = text
        if previous_intent:
            state["intent"] = previous_intent
        state["dialogue_action"] = "continue"
        state["response_mode"] = "run_agent"
        state["last_acknowledgement"] = "明白了，我会把这段内容作为竞赛通知处理，不会用它改动你的个人信息。"
    current_major = str(state.get("major") or "").strip()
    if previous_major and current_major and previous_major != current_major:
        state = _reset_profile_dependent_state(state, current_major)
    state["conversation_summary"] = _build_conversation_summary(state)
    return state


def _apply_turn_understanding(state: dict[str, Any], understanding: dict[str, Any]) -> dict[str, Any]:
    """Merge a validated LLM turn interpretation without replacing deterministic safeguards."""
    input_role = str(understanding.get("input_role") or "").strip()
    if input_role in {
        "user_profile", "competition_notice", "project_description",
        "command", "followup", "chat",
    }:
        state["input_role"] = input_role

    allowed_intents = {"collect", "extract", "recommendation", "material", "full_process"}
    intent = str(understanding.get("intent") or "").strip()
    if intent in allowed_intents and not state.get("intent"):
        state["intent"] = intent

    allowed_actions = {
        "continue", "profile_change", "new_recommendation", "expand_recommendations",
        "explain_recommendation_count", "compare_recommendations",
        "competition_detail", "change_preferences", "generate_material", "chat",
    }
    dialogue_action = str(understanding.get("dialogue_action") or "").strip()
    if dialogue_action in allowed_actions:
        state["dialogue_action"] = dialogue_action
    response_mode = str(understanding.get("response_mode") or "").strip()
    if response_mode in {"run_agent", "answer_from_context", "ask_clarification"}:
        state["response_mode"] = response_mode
    options = understanding.get("recommendation_options")
    if isinstance(options, dict):
        clean_options = dict(state.get("recommendation_options") or {})
        top_n = options.get("top_n")
        if isinstance(top_n, int) and 1 <= top_n <= 10:
            clean_options["top_n"] = top_n
        for key in ["include_backup", "relax_quality_gate", "explanation_requested"]:
            if isinstance(options.get(key), bool):
                clean_options[key] = options[key]
        state["recommendation_options"] = clean_options
    if dialogue_action == "expand_recommendations":
        expanded = dict(state.get("recommendation_options") or {})
        expanded.setdefault("top_n", 5)
        expanded.setdefault("include_backup", True)
        expanded.setdefault("relax_quality_gate", True)
        state["recommendation_options"] = expanded
        state["intent"] = "recommendation"

    corrected_fields = understanding.get("corrected_fields", [])
    corrected_fields = corrected_fields if isinstance(corrected_fields, list) else []
    for key in ["major", "grade", "competition_type", "competition_level", "team_preference"]:
        value = str(understanding.get(key) or "").strip()
        if value and (
            not state.get(key)
            or key in corrected_fields
            or (key == "major" and dialogue_action == "profile_change")
        ):
            state[key] = value

    scope = str(understanding.get("competition_scope") or "").strip()
    if scope in {"major_aligned", "cross_disciplinary", "both"}:
        state["competition_scope"] = scope

    type_status = str(understanding.get("competition_type_status") or "").strip()
    if type_status == "no_preference":
        state["competition_type"] = ""
        state["competition_type_confirmed"] = True
    elif state.get("competition_type"):
        state["competition_type_confirmed"] = True

    level_status = str(understanding.get("competition_level_status") or "").strip()
    if level_status == "no_preference":
        state["competition_level"] = ""
        state["competition_level_confirmed"] = True
    elif state.get("competition_level"):
        state["competition_level_confirmed"] = True

    list_merges = {
        "skills_add": "skills",
        "skills_remove": "skill_gaps",
        "excluded_competition_types": "excluded_competition_types",
        "preferred_levels": "preferred_levels",
        "acceptable_levels": "acceptable_levels",
        "excluded_levels": "excluded_levels",
        "development_goals": "development_goals",
    }
    for source_key, state_key in list_merges.items():
        values = understanding.get(source_key, [])
        if not isinstance(values, list):
            continue
        for value in values:
            clean_value = str(value or "").strip()
            if clean_value:
                state[state_key] = _append_unique(state.get(state_key, []), clean_value)

    for skill in understanding.get("skills_remove", []) if isinstance(understanding.get("skills_remove"), list) else []:
        state["skills"] = [item for item in state.get("skills", []) if item.lower() != str(skill).lower()]

    if understanding.get("skills_status") == "no_preference":
        state["skills_skipped"] = True

    time_value = understanding.get("available_time_per_week")
    if isinstance(time_value, (int, float)) and time_value >= 0:
        state["available_time_per_week"] = float(time_value)

    acknowledgement = str(understanding.get("acknowledgement") or "").strip()
    if acknowledgement:
        state["last_acknowledgement"] = acknowledgement[:180]
    return state


def _reset_profile_dependent_state(state: dict[str, Any], major: str) -> dict[str, Any]:
    """Start a fresh recommendation context when the user's academic identity changes."""
    reset_values = {
        "interests": [], "skills": [], "skills_skipped": False, "skill_gaps": [],
        "competition_type": "", "competition_type_confirmed": False,
        "competition_scope": "",
        "excluded_competition_types": [], "competition_level": "",
        "competition_level_confirmed": False, "preferred_levels": [],
        "acceptable_levels": [], "excluded_levels": [], "notification_text": "",
        "project_name": "", "material_type": "", "last_result": {},
        "recommendation_options": {}, "intent": "recommendation",
        "dialogue_action": "profile_change", "response_mode": "ask_clarification",
        "last_acknowledgement": f"明白了，我们按{major}专业重新梳理，这次不沿用之前的方向和技能。",
    }
    return {**state, **reset_values}


def _build_conversation_summary(state: dict[str, Any]) -> str:
    """Build a compact factual memory for agents instead of replaying full chat history."""
    facts = []
    labels = [
        ("major", "专业"), ("grade", "年级"), ("competition_type", "方向"),
        ("competition_scope", "方向范围"),
        ("competition_level", "级别"), ("team_preference", "参赛形式"),
        ("project_name", "当前竞赛"), ("material_type", "材料类型"),
    ]
    for key, label in labels:
        value = state.get(key)
        if value:
            facts.append(f"{label}：{value}")
    list_labels = [
        ("skills", "技能"), ("skill_gaps", "不擅长"),
        ("development_goals", "发展目标"), ("excluded_levels", "排除级别"),
        ("excluded_competition_types", "排除方向"),
    ]
    for key, label in list_labels:
        values = state.get(key)
        if isinstance(values, list) and values:
            facts.append(f"{label}：{'、'.join(str(value) for value in values[:8])}")
    if state.get("available_time_per_week") is not None:
        facts.append(f"每周可投入：{state['available_time_per_week']}小时")
    return "；".join(facts)


def _semantic_followup_answer(
    state: dict[str, Any], understanding: dict[str, Any] | None
) -> str | None:
    """Answer context-only meta questions without rerunning a sub-agent."""
    if not understanding or not state.get("last_result"):
        return None
    if understanding.get("dialogue_action") != "explain_recommendation_count":
        return None
    recommendations = _recommendations_from_chat_state(state)
    count = len(recommendations)
    return (
        f"这轮一共展示了 {count} 个结果。当前推荐会优先保留匹配度较高的主推荐，"
        "较低分或同类型的候选可能被质量门槛和去重规则收进备选。"
        "如果你愿意，我可以放宽门槛，把较合适的备选也一起列出来供你比较。"
    )


def _next_chat_question(state: dict[str, Any]) -> str | None:
    if not state.get("intent"):
        return (
            "当然可以。你现在更想先找适合自己的竞赛、整理一份竞赛通知，"
            "还是为已经选好的项目准备材料？"
        )
    if state["intent"] in {"recommendation", "material", "full_process"}:
        if not state.get("major") and not state.get("grade"):
            return (
                "没问题，我先了解一下你的基本情况：你现在是什么专业、读大几？"
                "这两项会直接影响参赛资格和推荐方向。"
            )
        if not state.get("major"):
            return "我记住你的年级了。再告诉我所学专业就可以，例如计算机、软件工程或工商管理。"
        if not state.get("grade"):
            return "专业方向了解了。你目前读大几，或者是在研究生阶段？我会据此判断参赛资格。"
    if state["intent"] == "material":
        recommendations = _recommendations_from_chat_state(state)
        if (
            not state.get("notification_text")
            and not state.get("project_name")
            and not recommendations
        ):
            return (
                "基本情况已经记下了。接下来请把这次项目申报的完整通知或申报要求粘贴给我，"
                "内容较长也没关系。我会先提取申报对象、赛道、时间和材料要求，再根据通知生成申报书。"
            )
    if state["intent"] in {"recommendation", "full_process"}:
        if state.get("competition_scope") and not state.get("competition_type_confirmed"):
            return (
                "范围我已经清楚了。你具体更想尝试什么主题？"
                "例如人工智能、算法、数学建模、金融科技或创新创业；如果主题不限，也可以直接告诉我。"
            )
        if not state.get("competition_type_confirmed") and not state.get("competition_level_confirmed"):
            major = state.get("major") or "你目前的专业"
            return (
                f"我们按{major}重新看。你对哪个方向更感兴趣，希望比赛贴近本专业，还是也接受跨学科方向？"
                "感兴趣的主题和期望的竞赛级别都可以用自己的话告诉我；暂时没偏好也没关系。"
            )
        if not state.get("competition_type_confirmed"):
            return "竞赛级别我记下了。你更想尝试什么主题或方向？直接用自己的话描述就可以。"
        if not state.get("competition_level_confirmed"):
            return "方向已经清楚了。你更倾向校级、省级、国家级还是国际级？如果没有硬性要求，也可以告诉我。"
        if not state.get("skills") and not state.get("skills_skipped"):
            return (
                "为了把结果排得更贴合，你目前有哪些比较熟悉的技能、知识、工具、项目经历或其他优势？"
                "不一定是编程技能，按真实情况简单说就行；暂时没有特别擅长的也没关系。"
            )
    if state["intent"] in {"material", "full_process"}:
        recommendations = _recommendations_from_chat_state(state)
        if not state.get("project_name") and len(recommendations) > 1:
            choices = "；".join(
                f"{index}. {item.get('title', '未命名竞赛')}"
                for index, item in enumerate(recommendations, 1)
            )
            return f"刚才的推荐里，你想为哪一个竞赛准备材料？回复序号或名称都可以：{choices}"
        if not state.get("project_name") and len(recommendations) == 1:
            state["project_name"] = str(recommendations[0].get("title", ""))
        if not state.get("material_type"):
            return "目标竞赛确定了。接下来想准备哪种材料？报名表、报名简历、计划书、PPT 或材料清单都可以。"
    if state["intent"] == "extract" and not state.get("notification_text"):
        return "好的，把竞赛通知全文粘贴过来就行，我会帮你整理关键信息和报名要求。"
    if state["intent"] == "collect" and not state.get("competition_type"):
        return "可以，你想先找哪个方向的竞赛？比如人工智能、算法、数学建模或创新创业。"
    return None


def _chat_standard_input(state: dict[str, Any], message: str) -> dict:
    profile = {
        "major": state.get("major", ""),
        **build_academic_profile(state.get("grade", "")),
        "interests": state.get("interests", []),
        "skills": state.get("skills", []),
        "competition_level": state.get("competition_level", ""),
        "development_goals": state.get("development_goals", []),
        "available_time_per_week": state.get("available_time_per_week"),
        "team_preference": state.get("team_preference", ""),
        "skill_gaps": state.get("skill_gaps", []),
    }
    payload: dict[str, Any] = {}
    task_type = state.get("intent") or "recommendation"
    notification = state.get("notification_text", "")
    if notification:
        payload.update({"data_source": "upload", "notification_text": notification})
    else:
        payload.update({"data_source": "web", "source_url": "https://www.saikr.com/"})
    # 从用户消息中提取数量（"11条"、"5个比赛"等），未指定时走 config 默认值
    import re
    count_match = re.search(r"(\d+)\s*(?:条|个|场|项|份)", message)
    if count_match:
        payload["max_results"] = int(count_match.group(1))

    if state.get("competition_type"):
        payload["keywords"] = [state["competition_type"], state.get("competition_level", "")]
    payload["preferences"] = {
        "preferred_levels": state.get("preferred_levels", []),
        "acceptable_levels": state.get("acceptable_levels", []),
        "excluded_levels": state.get("excluded_levels", []),
        "excluded_competition_types": state.get("excluded_competition_types", []),
        "competition_scope": state.get("competition_scope", ""),
    }
    options = state.get("recommendation_options") or {}
    if task_type in {"recommendation", "full_process"} and options:
        rules: dict[str, Any] = {}
        if isinstance(options.get("top_n"), int):
            rules["top_n"] = options["top_n"]
        if options.get("include_backup") or options.get("relax_quality_gate"):
            rules["quality_gate"] = {
                "allow_backup": True,
                "prefer_fewer": False,
            }
        if options.get("relax_quality_gate"):
            rules["diversity"] = {"max_per_category": 2}
        if rules:
            payload["recommendation_rules"] = rules
    if state.get("material_type"):
        payload["material_type"] = state["material_type"]
    if state.get("project_name"):
        payload["project_info"] = {
            "project_name": state["project_name"],
            "background": "根据对话收集的信息生成申报材料初稿。",
        }

    last_result = state.get("last_result", {})
    if task_type in {"material", "full_process"} and payload.get("project_info"):
        selected_name = payload["project_info"]["project_name"]
        for recommendation in _recommendations_from_chat_state(state):
            if recommendation.get("title") == selected_name:
                payload["project_info"] = {
                    **recommendation,
                    "project_name": selected_name,
                    "background": recommendation.get("summary") or recommendation.get("reason", "根据上一轮推荐结果生成。"),
                }
                payload["competition_info"] = {
                    **recommendation,
                    "competition_name": selected_name,
                }
                break

    return {
        "task_id": f"chat_task_{uuid4().hex[:8]}",
        "user_input": message,
        "task_type": task_type,
        "user_profile": profile,
        "context": {
            "conversation_summary": state.get("conversation_summary", ""),
            "recent_turns": state.get("turns", [])[-4:],
        },
        "input_data": payload,
        "history": [],
        "required_output": "markdown",
        "metadata": {"source": "streamlit_chat", "ui_version": "3.0"},
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
            top_title = str(recommendations[0].get("title", "排名最靠前的竞赛"))
            lines.append(
                f"我结合你提供的背景和偏好做了筛选。**{top_title}** 目前最值得优先了解，"
                "其他候选也一并列在下面，方便你比较。"
            )
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
            lines.append(
                f"### 材料已经准备好\n{data['material_name']} 已生成。下载后建议再核对个人经历、"
                "项目数据和报名要求，确认无误后再提交。"
            )
    if lines:
        return "\n\n".join(lines)
    fallback = str(result.get("data", {}).get("final_answer", "")).strip()
    if fallback:
        return fallback
    if result.get("status") in {"failed", "partial"}:
        return "这次处理没有完整完成。你可以稍后重试，或者换一组更宽泛的条件，我再帮你查找。"
    return "这一步已经处理好了。你可以继续问我结果中的具体项目，或者接着准备报名材料。"


def chat_submit(message, history, state):
    message = clean_text(message)
    history = list(history or initial_chat_messages())
    state = state or new_chat_state()
    if not message:
        return "", history, state, build_status_html("ready"), EMPTY_RESULT, [], {}, []

    history.append({"role": "user", "content": message})
    main_agent = MainAgent(config=load_config())
    control = main_agent.handle_conversation_control(message, state)
    if control:
        answer = control.get("data", {}).get("final_answer", control.get("message", ""))
        history.append({"role": "assistant", "content": answer})
        return "", history, state, build_status_html("success", control.get("message")), answer, [], control, _result_downloads(state.get("last_result", {}))
    followup = (
        main_agent.handle_followup(message, state["last_result"], state)
        if state.get("last_result")
        else None
    )
    if followup:
        answer = followup.get("data", {}).get("final_answer", followup.get("message", ""))
        state["turns"] = [*state.get("turns", []), message]
        history.append({"role": "assistant", "content": answer})
        return "", history, state, build_status_html(followup.get("status", "success"), followup.get("message")), answer, [], followup, _result_downloads(state["last_result"])
    understanding = main_agent.understand_conversation_turn(message, state)
    state = _update_chat_state(state, message, understanding=understanding)
    semantic_answer = _semantic_followup_answer(state, understanding)
    if semantic_answer:
        history.append({"role": "assistant", "content": semantic_answer})
        return "", history, state, build_status_html("success"), semantic_answer, [], {}, _result_downloads(state.get("last_result", {}))
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
