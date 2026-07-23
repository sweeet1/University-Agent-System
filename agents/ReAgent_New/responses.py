"""
统一 success / failed / need_input 响应构建。
"""

from __future__ import annotations

from typing import Optional

from .constants import AGENT_NAME


def success_response(
    task_id: str,
    data: Optional[dict] = None,
    message: str = "",
    agent_name: str = AGENT_NAME,
) -> dict:
    """构建统一成功响应。"""
    return {
        "task_id": task_id,
        "agent_name": agent_name,
        "status": "success",
        "data": data if data is not None else {},
        "message": message or "Agent executed successfully.",
        "error": None,
        "next_action": None,
        "metadata": {},
    }


def error_response(
    task_id: str,
    error_type: str,
    error_message: str,
    suggestion: str = "",
    agent_name: str = AGENT_NAME,
) -> dict:
    """构建统一失败响应（遵循 PROJECT_SPEC 错误格式）。"""
    return {
        "task_id": task_id,
        "agent_name": agent_name,
        "status": "failed",
        "data": {},
        "message": error_message,
        "error": {
            "error_type": error_type,
            "error_message": error_message,
            "suggestion": suggestion,
        },
        "next_action": None,
        "metadata": {},
    }


def need_input_response(
    task_id: str,
    message: str,
    agent_name: str = AGENT_NAME,
) -> dict:
    """构建「需要用户补充信息」响应。"""
    return {
        "task_id": task_id,
        "agent_name": agent_name,
        "status": "need_input",
        "data": {},
        "message": message,
        "error": None,
        "next_action": "ask_user",
        "metadata": {},
    }


def partial_response(
    task_id: str,
    data: Optional[dict] = None,
    message: str = "",
    agent_name: str = AGENT_NAME,
) -> dict:
    """构建 partial 响应（流程跑通但无可用推荐等）。"""
    resp = success_response(task_id, data=data, message=message, agent_name=agent_name)
    resp["status"] = "partial"
    return resp
