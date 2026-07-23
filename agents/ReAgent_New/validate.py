"""
输入校验：失败返回标准 need_input / failed 响应 dict；通过返回 None。
"""

from __future__ import annotations

from typing import Optional

from .responses import error_response, need_input_response


def validate_input(input_data) -> Optional[dict]:
    """校验输入是否满足推荐最低要求。

    Returns:
        None 表示通过；否则返回标准错误 / need_input 响应 dict。
    """
    if not isinstance(input_data, dict):
        return error_response(
            "",
            "ValidationError",
            "input_data 必须是 dict 类型",
        )

    task_id = input_data.get("task_id", "")

    if "input_data" in input_data and input_data["input_data"] is not None:
        business = input_data["input_data"]
        if not isinstance(business, dict):
            return error_response(
                task_id,
                "ValidationError",
                "input_data 字段必须是 dict 类型",
            )
    else:
        business = input_data

    structured_items = business.get("structured_items", None)
    if structured_items is None:
        return need_input_response(
            task_id,
            "缺少结构化项目数据（structured_items），"
            "请先调用信息采集和信息抽取 Agent。",
        )
    if not isinstance(structured_items, list):
        return error_response(
            task_id,
            "ValidationError",
            "structured_items 必须是 list 类型",
        )
    if len(structured_items) == 0:
        return need_input_response(
            task_id,
            "structured_items 为空，请先补充可推荐的项目数据。",
        )

    user_profile = input_data.get("user_profile") or business.get("user_profile")
    if not isinstance(user_profile, dict) or not user_profile:
        return need_input_response(
            task_id,
            "缺少用户画像数据（user_profile），"
            "请用户完善个人信息（专业、年级、兴趣方向等）。",
        )

    return None
