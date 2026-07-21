from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from agents.main_agent import MainAgent
from app import (
    CHAT_WELCOME,
    _chat_result_text,
    _chat_standard_input,
    _next_chat_question,
    _result_downloads,
    _update_chat_state,
    load_config,
    new_chat_state,
)


st.set_page_config(
    page_title="赛智通 · 科研竞赛智能助手",
    page_icon="🎓",
    layout="wide",
)


def load_cloud_secrets() -> None:
    """Expose Streamlit secrets through the environment expected by agents."""
    try:
        api_key = str(st.secrets.get("DEEPSEEK_API_KEY", "")).strip()
    except FileNotFoundError:
        api_key = ""
    if api_key:
        os.environ["DEEPSEEK_API_KEY"] = api_key


def initialize_session() -> None:
    if "chat_state" not in st.session_state:
        st.session_state.chat_state = new_chat_state()
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": CHAT_WELCOME}
        ]
    if "last_status" not in st.session_state:
        st.session_state.last_status = "等待输入"
    if "downloads" not in st.session_state:
        st.session_state.downloads = []


def reset_conversation() -> None:
    st.session_state.chat_state = new_chat_state()
    st.session_state.messages = [{"role": "assistant", "content": CHAT_WELCOME}]
    st.session_state.last_status = "等待输入"
    st.session_state.downloads = []


def run_conversation_turn(prompt: str) -> None:
    main_agent = MainAgent(config=load_config())
    control = main_agent.handle_conversation_control(
        prompt, st.session_state.chat_state
    )
    if control:
        answer = control.get("data", {}).get("final_answer", control.get("message", ""))
        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.session_state.last_status = "等待竞赛相关问题"
        return

    previous_result = st.session_state.chat_state.get("last_result")
    followup = None
    if previous_result:
        with st.spinner("正在读取竞赛信息并生成简介……"):
            followup = main_agent.handle_followup(prompt, previous_result)
    if followup:
        answer = followup.get("data", {}).get("final_answer", followup.get("message", ""))
        st.session_state.chat_state["turns"] = [
            *st.session_state.chat_state.get("turns", []), prompt
        ]
        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.session_state.last_status = followup.get("status", "success")
        return

    state = _update_chat_state(st.session_state.chat_state, prompt)
    st.session_state.chat_state = state
    question = _next_chat_question(state)
    if question:
        st.session_state.messages.append({"role": "assistant", "content": question})
        st.session_state.last_status = "正在补充信息"
        return

    standard_input = _chat_standard_input(state, prompt)
    with st.spinner("正在调度智能体，请稍候……"):
        result = main_agent.run(standard_input)
    state["last_result"] = result
    st.session_state.chat_state = state
    st.session_state.last_status = result.get("status", "failed")
    st.session_state.downloads = _result_downloads(result)
    answer = _chat_result_text(result)
    if st.session_state.downloads:
        answer += "\n\n材料文件已生成，可在右侧下载。提交前请人工复核。"
    st.session_state.messages.append({"role": "assistant", "content": answer})


load_cloud_secrets()
initialize_session()

st.title("🎓 赛智通 · 科研竞赛智能助手")
st.caption("通过多轮对话收集背景、推荐竞赛，并生成可下载的申报材料初稿")

chat_column, side_column = st.columns([2, 1], gap="large")

with chat_column:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("告诉我你的专业、年级和参赛目标……"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        run_conversation_turn(prompt)
        st.rerun()

with side_column:
    st.subheader("当前进度")
    st.info(st.session_state.last_status)
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        st.warning(
            "尚未检测到 DEEPSEEK_API_KEY。系统会保留采集到的基础字段，"
            "但通知理解和材料内容将使用降级模式。请在 App settings → Secrets 中配置密钥。"
        )

    state = st.session_state.chat_state
    profile = {
        "目标": state.get("intent") or "待确认",
        "专业": state.get("major") or "待补充",
        "年级": state.get("grade") or "待补充",
        "竞赛方向": state.get("competition_type") or "待补充",
        "竞赛级别": state.get("competition_level") or "待补充",
        "技能": "、".join(state.get("skills", [])) or "待补充",
    }
    st.markdown("#### 已记录信息")
    for label, value in profile.items():
        st.markdown(f"**{label}：** {value}")

    if st.session_state.downloads:
        st.markdown("#### 材料下载")
        for index, file_path in enumerate(st.session_state.downloads):
            path = Path(file_path)
            if path.is_file():
                st.download_button(
                    label=f"下载 {path.name}",
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime=(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        if path.suffix.lower() == ".docx"
                        else "application/octet-stream"
                    ),
                    key=f"download_{index}_{path.name}",
                    use_container_width=True,
                )

    st.button("开始新对话", on_click=reset_conversation, use_container_width=True)

    with st.expander("完整会话状态（调试）"):
        safe_state = {key: value for key, value in state.items() if key != "last_result"}
        st.code(json.dumps(safe_state, ensure_ascii=False, indent=2), language="json")

st.divider()
st.caption("提示：生成内容为辅助初稿，请勿输入身份证号、密码等敏感信息，正式提交前请人工复核。")
