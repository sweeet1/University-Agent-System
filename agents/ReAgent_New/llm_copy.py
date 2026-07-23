"""
用项目已有 DeepSeek / OpenAI 兼容 API 润色推荐文案。

仅处理 Top-N 的 reason / risk；失败或未配置时回退规则文案。
不参与打分与排序。不依赖 main_agent。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


DEFAULT_LLM_COPY = {
    "enabled": True,  # config.yaml 可关；无 API Key 时自动跳过
    "polish_risk": True,
    "temperature": 0.3,
    "max_tokens": 280,
    "timeout": 20,
}


def load_llm_copy_settings(rec_cfg: Optional[dict] = None) -> dict:
    """合并 recommendation.llm_copywriting 配置。"""
    settings = dict(DEFAULT_LLM_COPY)
    rec_cfg = rec_cfg if isinstance(rec_cfg, dict) else {}
    custom = rec_cfg.get("llm_copywriting", {})
    if isinstance(custom, dict):
        settings.update(custom)
    settings["enabled"] = bool(settings.get("enabled", True))
    settings["polish_risk"] = bool(settings.get("polish_risk", True))
    return settings


def _ensure_dotenv() -> None:
    """若尚未注入环境变量，尝试加载项目根 .env（与 app.py 一致）。"""
    if os.getenv("DEEPSEEK_API_KEY"):
        return
    try:
        from dotenv import load_dotenv

        from .utils import project_root

        load_dotenv(project_root() / ".env")
    except Exception:
        return


def _resolve_llm_credentials(config: Optional[dict]) -> Dict[str, Any]:
    """从全局 config.llm / 环境变量解析 API 凭证。"""
    _ensure_dotenv()
    cfg = config if isinstance(config, dict) else {}
    llm = cfg.get("llm", {}) if isinstance(cfg.get("llm"), dict) else {}

    api_key_env = llm.get("api_key_env", "DEEPSEEK_API_KEY")
    api_key = llm.get("api_key", "") or os.getenv(str(api_key_env), "")
    base_url = (
        llm.get("base_url")
        or os.getenv("DEEPSEEK_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.deepseek.com"
    )
    model = (
        llm.get("model")
        or os.getenv("DEEPSEEK_MODEL")
        or os.getenv("OPENAI_MODEL")
        or "deepseek-chat"
    )
    timeout = int(llm.get("timeout", DEFAULT_LLM_COPY["timeout"]))
    enabled_flag = bool(llm.get("enabled", False)) or bool(api_key)
    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "timeout": timeout,
        "enabled": enabled_flag and bool(api_key),
    }


def _profile_brief(user: dict) -> dict:
    """压缩画像，避免 prompt 过长。"""
    awards = []
    for a in (user.get("awards") or [])[:3]:
        if isinstance(a, dict):
            awards.append(
                {
                    "competition_name": a.get("competition_name", ""),
                    "level": a.get("level", ""),
                    "award_name": a.get("award_name", ""),
                }
            )
        else:
            awards.append(str(a))
    return {
        "major": user.get("major", ""),
        "school": user.get("school", ""),
        "education_level": user.get("education_level", ""),
        "skills": (user.get("skills") or [])[:8],
        "interests": (user.get("interests") or [])[:8],
        "team_status": user.get("team_status", ""),
        "awards": awards,
        "competition_experience": (user.get("competition_experience") or [])[:3],
    }


def _call_chat_completions(
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout: int,
    system: str,
    user_content: str,
    temperature: float,
    max_tokens: int,
) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        url=base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = str(data["choices"][0]["message"]["content"] or "").strip()
        return {"ok": True, "content": content, "error": None}
    except (
        urllib.error.URLError,
        TimeoutError,
        KeyError,
        IndexError,
        json.JSONDecodeError,
        OSError,
    ) as exc:
        return {
            "ok": False,
            "content": "",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }


def _parse_polish_json(text: str) -> Optional[dict]:
    """从模型输出中解析 {reason, risk}。"""
    if not text:
        return None
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped)
    if fence:
        stripped = fence.group(1).strip()
    try:
        data = json.loads(stripped)
        if isinstance(data, dict) and data.get("reason"):
            return data
    except json.JSONDecodeError:
        pass

    # 截取第一个 {...}
    brace = re.search(r"\{[\s\S]*\}", stripped)
    if brace:
        try:
            data = json.loads(brace.group(0))
            if isinstance(data, dict) and data.get("reason"):
                return data
        except json.JSONDecodeError:
            pass

    if len(stripped) >= 8 and "{" not in stripped:
        return {"reason": stripped}
    return None


def polish_one_recommendation(
    rec: dict,
    user: dict,
    *,
    config: Optional[dict] = None,
    llm_copy_settings: Optional[dict] = None,
) -> dict:
    """润色单条推荐的 reason/risk；失败则原样返回并标记 source=rule。"""
    settings = llm_copy_settings or load_llm_copy_settings()
    creds = _resolve_llm_credentials(config)

    if not settings.get("enabled", True) or not creds.get("enabled"):
        rec = dict(rec)
        rec.setdefault("copy_source", "rule")
        return rec

    fallback_reason = rec.get("reason", "")
    fallback_risk = rec.get("risk", "")

    payload = {
        "user_profile": _profile_brief(user),
        "competition": {
            "title": rec.get("title", ""),
            "summary": (rec.get("summary") or "")[:240],
            "deadline": rec.get("deadline", ""),
            "organizer": rec.get("organizer", ""),
            "prestige_tier": rec.get("prestige_tier", ""),
            "category_key": rec.get("category_key", ""),
            "match_score": rec.get("match_score"),
            "recommend_level": rec.get("recommend_level"),
            "is_backup": rec.get("is_backup", False),
        },
        "matched_signals": (rec.get("matched_signals") or [])[:8],
        "unmatched_signals": (rec.get("unmatched_signals") or [])[:6],
        "rule_reason": fallback_reason,
        "rule_risk": fallback_risk,
    }

    system = (
        "你是大学生竞赛顾问。根据给定 JSON 事实撰写推荐说明。"
        "只能使用提供的信息，禁止编造奖项、技能或截止日期。"
        "输出严格 JSON 对象，字段："
        '{"reason":"2到3句中文推荐理由","risk":"1句风险或注意点"}。'
        "reason 要自然流畅，像顾问口头说明，不要出现 <-> 或「兴趣匹配度(xx分)」这种模板。"
        "不要输出 Markdown 代码块以外的多余文字。"
    )
    user_content = (
        "请润色以下推荐文案：\n"
        + json.dumps(payload, ensure_ascii=False)
    )

    result = _call_chat_completions(
        api_key=creds["api_key"],
        base_url=creds["base_url"],
        model=creds["model"],
        timeout=int(settings.get("timeout", creds["timeout"])),
        system=system,
        user_content=user_content,
        temperature=float(settings.get("temperature", 0.3)),
        max_tokens=int(settings.get("max_tokens", 280)),
    )

    out = dict(rec)
    if not result.get("ok"):
        out["copy_source"] = "rule"
        out["copy_error"] = result.get("error")
        return out

    parsed = _parse_polish_json(result.get("content", ""))
    if not parsed or not str(parsed.get("reason", "")).strip():
        out["copy_source"] = "rule"
        out["copy_error"] = {"message": "LLM returned unusable reason"}
        return out

    out["reason"] = str(parsed.get("reason", "")).strip()
    if settings.get("polish_risk", True) and str(parsed.get("risk", "")).strip():
        out["risk"] = str(parsed.get("risk", "")).strip()
    out["copy_source"] = "llm"
    return out


def polish_recommendations(
    recommendations: List[dict],
    user: dict,
    *,
    config: Optional[dict] = None,
    llm_copy_settings: Optional[dict] = None,
) -> List[dict]:
    """批量润色 Top-N 推荐文案。"""
    settings = llm_copy_settings or load_llm_copy_settings()
    creds = _resolve_llm_credentials(config)
    if not settings.get("enabled", True) or not creds.get("enabled"):
        return [
            {**r, "copy_source": r.get("copy_source", "rule")}
            for r in recommendations
        ]

    polished = []
    for rec in recommendations:
        polished.append(
            polish_one_recommendation(
                rec,
                user,
                config=config,
                llm_copy_settings=settings,
            )
        )
    return polished
