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
    _expand_recommendations_from_cache,
    _next_chat_question,
    _profile_edit_followup_answer,
    _result_downloads,
    _semantic_followup_answer,
    _should_hold_after_profile_edit,
    _update_chat_state,
    load_config,
    new_chat_state,
)


st.set_page_config(
    page_title="赛智通 · 科研竞赛智能助手",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)


GPT_STYLE = """
<style>
:root {
  --szt-bg: #f7f7f8;
  --szt-sidebar: #171717;
  --szt-ink: #1f2937;
  --szt-muted: #6b7280;
  --szt-line: #e5e7eb;
  --szt-accent: #10a37f;
}

[data-testid="stAppViewContainer"] {
  background: var(--szt-bg);
  color: var(--szt-ink);
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { right: 1rem; }
#MainMenu, footer { visibility: hidden; }

[data-testid="stSidebar"] {
  background: var(--szt-sidebar);
  border-right: 1px solid #2b2b2b;
}
[data-testid="stSidebar"] * { color: #ececec; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
  color: #c5c5c5;
}
[data-testid="stSidebar"] .stButton > button {
  min-height: 44px;
  border-radius: 10px;
  border: 1px solid #424242;
  background: transparent;
  color: #f5f5f5;
  font-weight: 600;
}
[data-testid="stSidebar"] .stButton > button:hover {
  border-color: #6b6b6b;
  background: #2a2a2a;
}

.block-container {
  max-width: 920px;
  padding-top: 2.6rem;
  padding-bottom: 7.5rem;
}
.szt-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 2px 2px 18px;
  border-bottom: 1px solid var(--szt-line);
  margin-bottom: 22px;
}
.szt-title { font-size: 17px; font-weight: 700; color: #111827; }
.szt-subtitle { margin-top: 3px; font-size: 12px; color: var(--szt-muted); }
.szt-online {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 6px 10px; border: 1px solid #d1fae5; border-radius: 999px;
  background: #ecfdf5; color: #047857; font-size: 12px; font-weight: 650;
}
.szt-online::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: #10b981; }
.szt-brand { display:flex; align-items:center; gap:10px; margin: 2px 0 18px; }
.szt-brand-mark {
  display:grid; place-items:center; width:34px; height:34px; border-radius:9px;
  background: var(--szt-accent); color:white !important; font-weight:800;
}
.szt-brand-copy strong { display:block; color:#fff; font-size:15px; }
.szt-brand-copy span { color:#8e8e8e; font-size:11px; }
.szt-side-label { margin: 18px 0 8px; color:#8e8e8e !important; font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }
.szt-state-row { padding: 7px 0; border-bottom: 1px solid #292929; font-size:12px; }
.szt-state-row b { color:#8e8e8e; font-weight:500; }
.szt-state-row span { float:right; max-width:62%; color:#f0f0f0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.szt-status-card { padding:10px 12px; border-radius:10px; background:#242424; color:#ddd; font-size:12px; line-height:1.5; }

[data-testid="stChatMessage"] {
  padding: 1.05rem 1.15rem;
  margin-bottom: .7rem;
  border-radius: 16px;
  border: 1px solid transparent;
}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
  background: #ffffff;
  border-color: var(--szt-line);
}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
  background: transparent;
}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
  font-size: 15px;
  line-height: 1.78;
}
[data-testid="stChatMessage"] h3 { font-size: 20px; margin: .3rem 0 .8rem; }
[data-testid="stChatMessage"] a { color: #087f6a; font-weight: 600; text-decoration: none; }
[data-testid="stChatMessage"] a:hover { text-decoration: underline; }

.szt-welcome { text-align:center; padding: 3.5rem 1rem 1.6rem; }
.szt-welcome-icon {
  display:grid; place-items:center; width:48px; height:48px; margin:0 auto 14px;
  border-radius:14px; background:#111827; color:white; font-weight:800; font-size:19px;
}
.szt-welcome h1 { margin:0; font-size:28px; color:#111827; }
.szt-welcome p { margin:9px auto 0; max-width:560px; color:var(--szt-muted); font-size:14px; }
.szt-quick-label { text-align:center; color:#9ca3af; font-size:12px; margin: 2px 0 10px; }
div[data-testid="stHorizontalBlock"] .stButton > button {
  min-height: 76px; padding: 12px 14px; text-align:left;
  border:1px solid var(--szt-line); border-radius:14px; background:#fff;
  color:#374151; font-size:13px; font-weight:600;
}
div[data-testid="stHorizontalBlock"] .stButton > button:hover {
  border-color:#a7f3d0; background:#f0fdf9; color:#047857;
}

[data-testid="stChatInput"] {
  border: 1px solid #d1d5db;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 10px 35px rgba(0,0,0,.09);
}
[data-testid="stChatInput"]:focus-within { border-color:#9ca3af; }
.stDownloadButton > button {
  border-radius:10px; border:1px solid #3f3f3f; background:#262626; color:#fff;
}

@media (max-width: 768px) {
  .block-container { padding: .8rem .8rem 6.5rem; }
  .szt-topbar { padding-right: 2.4rem; }
  .szt-subtitle, .szt-online { display:none; }
  [data-testid="stChatMessage"] { padding: .85rem .8rem; }
  .szt-welcome { padding-top: 2rem; }
  div[data-testid="stHorizontalBlock"] { flex-direction:column; }
}
</style>
"""


def load_cloud_secrets() -> None:
    """Expose Streamlit secrets through the environment expected by agents."""
    try:
        api_key = str(st.secrets.get("DEEPSEEK_API_KEY", "")).strip()
    except Exception:
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
    if "pending_turn" not in st.session_state:
        st.session_state.pending_turn = None


def reset_conversation() -> None:
    st.session_state.chat_state = new_chat_state()
    st.session_state.messages = [{"role": "assistant", "content": CHAT_WELCOME}]
    st.session_state.last_status = "等待输入"
    st.session_state.downloads = []
    st.session_state.pending_turn = None


def _dialogue_memory_snapshot(state: dict) -> dict:
    """Fields shown in the sidebar '对话记忆' panel."""
    return {
        "intent": state.get("intent") or "",
        "major": state.get("major") or "",
        "grade": state.get("grade") or "",
        "competition_type": state.get("competition_type") or "",
        "competition_type_confirmed": bool(state.get("competition_type_confirmed")),
        "competition_level": state.get("competition_level") or "",
        "competition_level_confirmed": bool(state.get("competition_level_confirmed")),
        "skills": list(state.get("skills") or []),
        "skills_skipped": bool(state.get("skills_skipped")),
    }


def _sidebar_profile_value(
    value: str | None,
    *,
    confirmed: bool = False,
    skipped: bool = False,
    open_label: str = "不限",
) -> str:
    """Render sidebar memory text.

    - has value → show value
    - confirmed/skipped empty → open_label（级别/方向用「不限」，技能用「暂无」）
    - not yet answered → 待补充
    """
    text = str(value or "").strip()
    if text:
        return text
    if confirmed or skipped:
        return open_label
    return "待补充"


def _finish_conversation_turn(
    prompt: str,
    understanding: dict | None,
    *,
    allow_dispatch: bool = False,
) -> None:
    """Ask follow-up or dispatch agents after dialogue memory has been written."""
    state = st.session_state.chat_state
    semantic_answer = _semantic_followup_answer(state, understanding)
    if semantic_answer:
        st.session_state.messages.append({"role": "assistant", "content": semantic_answer})
        st.session_state.last_status = "已结合上一轮结果回答"
        return

    expanded_answer = _expand_recommendations_from_cache(state, understanding)
    if expanded_answer:
        st.session_state.messages.append({"role": "assistant", "content": expanded_answer})
        st.session_state.last_status = "已补充更多推荐"
        return

    question = _next_chat_question(state)
    if question:
        acknowledgement = str(state.get("last_acknowledgement", "")).strip()
        if acknowledgement:
            question = f"{acknowledgement}\n\n{question}"
        st.session_state.messages.append({"role": "assistant", "content": question})
        st.session_state.last_status = "正在补充信息"
        return

    edited_labels = _should_hold_after_profile_edit(state, understanding)
    if edited_labels:
        answer = _profile_edit_followup_answer(edited_labels)
        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.session_state.last_status = "已更新对话记忆"
        return

    # 调度 Agent 前再刷一次侧边栏，确保「不限」等状态先可见
    if not allow_dispatch:
        st.session_state.last_status = "信息已齐全，准备为你推荐"
        st.session_state.pending_turn = {
            "prompt": prompt,
            "understanding": understanding,
            "stage": "dispatch_agent",
        }
        st.rerun()

    main_agent = MainAgent(config=load_config())
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


def continue_pending_turn() -> bool:
    """Resume a turn after the sidebar has refreshed with updated dialogue memory.

    Returns True when a pending turn was processed (caller should rerun).
    """
    pending = st.session_state.get("pending_turn")
    if not pending:
        return False
    st.session_state.pending_turn = None
    stage = str(pending.get("stage") or "respond")
    _finish_conversation_turn(
        pending["prompt"],
        pending.get("understanding"),
        allow_dispatch=(stage == "dispatch_agent"),
    )
    return True


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
            followup = main_agent.handle_followup(
                prompt, previous_result, st.session_state.chat_state
            )
    if followup:
        answer = followup.get("data", {}).get("final_answer", followup.get("message", ""))
        st.session_state.chat_state["turns"] = [
            *st.session_state.chat_state.get("turns", []), prompt
        ]
        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.session_state.last_status = followup.get("status", "success")
        return

    before_memory = _dialogue_memory_snapshot(st.session_state.chat_state)
    with st.spinner("正在理解你的需求……"):
        understanding = main_agent.understand_conversation_turn(
            prompt, st.session_state.chat_state
        )
    state = _update_chat_state(
        st.session_state.chat_state,
        prompt,
        understanding=understanding,
    )
    st.session_state.chat_state = state
    after_memory = _dialogue_memory_snapshot(state)

    # 对话记忆有变化时先刷新侧边栏，再追问或调度 Agent
    if before_memory != after_memory:
        st.session_state.last_status = "已更新对话记忆"
        st.session_state.pending_turn = {
            "prompt": prompt,
            "understanding": understanding,
            "stage": "respond",
        }
        st.rerun()

    _finish_conversation_turn(prompt, understanding, allow_dispatch=False)


load_cloud_secrets()
initialize_session()
st.markdown(GPT_STYLE, unsafe_allow_html=True)

with st.sidebar:
    st.markdown(
        """
        <div class="szt-brand">
          <div class="szt-brand-mark">智</div>
          <div class="szt-brand-copy"><strong>赛智通</strong><span>科研竞赛智能助手</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.button("＋  新建对话", on_click=reset_conversation, use_container_width=True)
    st.markdown('<div class="szt-side-label">当前状态</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="szt-status-card">{st.session_state.last_status}</div>',
        unsafe_allow_html=True,
    )
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        st.warning(
            "未检测到 API Key，详情与材料内容将使用降级模式。"
        )

    state = st.session_state.chat_state
    profile = {
        "目标": state.get("intent") or "待确认",
        "专业": _sidebar_profile_value(state.get("major")),
        "年级": _sidebar_profile_value(state.get("grade")),
        "竞赛方向": _sidebar_profile_value(
            state.get("competition_type"),
            confirmed=bool(state.get("competition_type_confirmed")),
            open_label="不限",
        ),
        "竞赛级别": _sidebar_profile_value(
            state.get("competition_level"),
            confirmed=bool(state.get("competition_level_confirmed")),
            open_label="不限",
        ),
        "技能": _sidebar_profile_value(
            "、".join(state.get("skills", [])),
            skipped=bool(state.get("skills_skipped")),
            open_label="暂无",
        ),
    }
    st.markdown('<div class="szt-side-label">对话记忆</div>', unsafe_allow_html=True)
    for label, value in profile.items():
        st.markdown(
            f'<div class="szt-state-row"><b>{label}</b><span>{value}</span></div>',
            unsafe_allow_html=True,
        )

    if st.session_state.downloads:
        st.markdown('<div class="szt-side-label">生成文件</div>', unsafe_allow_html=True)
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

    with st.expander("调试信息"):
        safe_state = {key: value for key, value in state.items() if key != "last_result"}
        st.code(json.dumps(safe_state, ensure_ascii=False, indent=2), language="json")

st.markdown(
    """
    <div class="szt-topbar">
      <div><div class="szt-title">赛智通</div><div class="szt-subtitle">竞赛发现、匹配与申报材料生成</div></div>
      <div class="szt-online">智能体已就绪</div>
    </div>
    """,
    unsafe_allow_html=True,
)

if len(st.session_state.messages) == 1 and not st.session_state.get("pending_turn"):
    st.markdown(
        """
        <section class="szt-welcome">
          <div class="szt-welcome-icon">智</div>
          <h1>今天想完成什么？</h1>
          <p>告诉我你的专业、年级和目标，我会通过多轮对话为你推荐竞赛，或生成可编辑的 Word 申报材料。</p>
        </section>
        <div class="szt-quick-label">你可以从这些任务开始</div>
        """,
        unsafe_allow_html=True,
    )
    quick_prompts = [
        "我是计算机专业大三学生，想参加人工智能竞赛",
        "帮我提取一份竞赛通知里的报名要求",
        "根据刚才推荐的竞赛生成报名简历",
    ]
    quick_columns = st.columns(3, gap="small")
    for index, (column, quick_prompt) in enumerate(zip(quick_columns, quick_prompts)):
        with column:
            if st.button(quick_prompt, key=f"quick_prompt_{index}", use_container_width=True):
                st.session_state.messages.append({"role": "user", "content": quick_prompt})
                run_conversation_turn(quick_prompt)
                st.rerun()

for message in st.session_state.messages:
    if len(st.session_state.messages) == 1 and message["role"] == "assistant":
        continue
    avatar = "🧠" if message["role"] == "assistant" else "👤"
    with st.chat_message(message["role"], avatar=avatar):
        st.markdown(message["content"])

# 侧边栏与已有消息先展示后，再继续追问 / 调度 Agent
if continue_pending_turn():
    st.rerun()

if prompt := st.chat_input("向赛智通发送消息…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    run_conversation_turn(prompt)
    st.rerun()

st.caption("赛智通可能会出错。生成内容和竞赛信息请以主办方最新通知为准，提交前请人工复核。")
