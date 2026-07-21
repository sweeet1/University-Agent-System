from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from importlib import import_module
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class MainAgent:
    """Main orchestrator for task understanding, agent scheduling, and integration."""

    agent_name = "MainAgent"

    required_fields = {
        "task_id",
        "user_input",
        "task_type",
        "user_profile",
        "context",
        "input_data",
        "history",
        "required_output",
        "metadata",
    }

    allowed_agents = {"info_collect", "info_extract", "recommendation", "material"}

    sub_agent_specs = {
        "info_collect": ("agents.info_collect_agent", "InfoCollectAgent"),
        "info_extract": ("agents.info_extract_agent", "InfoExtractAgent"),
        "recommendation": ("agents.recommendation_agent", "RecommendationAgent"),
        "material": ("agents.material_agent", "MaterialAgent"),
    }

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.sub_agents = self._load_sub_agents()

    def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Only external interface of MainAgent."""
        task_id = self._get_task_id(input_data)

        try:
            validation_error = self.validate_input(input_data)
            if validation_error:
                return self._build_output(
                    task_id=task_id,
                    status="failed",
                    data={},
                    message="Input validation failed.",
                    error=validation_error,
                )

            return self.process(input_data)
        except Exception as exc:
            return self._build_output(
                task_id=task_id,
                status="failed",
                data={},
                message="MainAgent execution failed.",
                error={"type": exc.__class__.__name__, "message": str(exc)},
            )

    def validate_input(self, input_data: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(input_data, dict):
            return {"message": "input_data must be a dict."}

        missing_fields = sorted(self.required_fields - set(input_data.keys()))
        if missing_fields:
            return {"message": "Missing required fields.", "fields": missing_fields}

        dict_fields = ["user_profile", "context", "input_data", "metadata"]
        invalid_dict_fields = [
            field for field in dict_fields if not isinstance(input_data.get(field), dict)
        ]
        if invalid_dict_fields:
            return {"message": "These fields must be dict.", "fields": invalid_dict_fields}

        if not isinstance(input_data.get("history"), list):
            return {"message": "history must be a list."}

        return None

    def process(self, input_data: dict[str, Any]) -> dict[str, Any]:
        task_id = self._get_task_id(input_data)
        planning = self.plan_task(input_data)
        selected_agents = planning.get("selected_agents", [])

        agent_results = []
        shared_context = dict(input_data.get("context", {}))
        shared_context["main_agent_plan"] = planning

        for agent_key in selected_agents:
            agent_input = self._build_agent_input(
                original_input=input_data,
                agent_key=agent_key,
                previous_results=agent_results,
                shared_context=shared_context,
            )
            result = self._call_sub_agent(agent_key, agent_input)
            agent_results.append(result)
            shared_context[f"{agent_key}_result"] = result.get("data", {})

        final_data = self.integrate_results(input_data, agent_results, planning)
        status = self._resolve_final_status(agent_results, planning)

        return self._build_output(
            task_id=task_id,
            status=status,
            data=final_data,
            message="MainAgent completed orchestration.",
            error=None if status in {"success", "partial", "need_input"} else final_data.get("errors"),
            next_action=final_data.get("next_action"),
            metadata={
                "selected_agents": selected_agents,
                "planning_source": planning.get("planning_source"),
                "agent_statuses": {
                    result.get("agent_name", "unknown"): result.get("status", "failed")
                    for result in agent_results
                },
            },
        )

    def handle_followup(
        self,
        user_input: str,
        previous_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Handle a conversational follow-up against a previous recommendation result.

        Returning ``None`` means the message is not a supported follow-up and should
        continue through the normal task-planning flow.
        """
        if not self._is_competition_detail_request(user_input):
            return None

        recommendations = self._recommendations_from_result(previous_result)
        if not recommendations:
            return self._build_output(
                task_id=self._get_task_id(previous_result),
                status="need_input",
                data={"final_answer": "当前对话中还没有可展开的推荐结果，请先完成一次竞赛推荐。"},
                message="No previous recommendation is available.",
                next_action="Run a recommendation task first.",
                metadata={"followup_type": "competition_detail"},
            )

        selected = self._select_recommendation_for_detail(recommendations, user_input)
        fallback = self._build_competition_detail_fallback(selected)
        generated = self._call_detail_llm(user_input, selected)
        answer = generated.get("content") or fallback
        source_url = str(selected.get("source_url", "")).strip()
        if source_url:
            answer += f"\n\n[打开竞赛原始网页]({source_url})"
        else:
            answer += "\n\n> 当前采集结果没有提供可验证的原始网页链接。"
        answer += "\n\n> 请以主办方或竞赛官网的最新通知为准。"

        return self._build_output(
            task_id=self._get_task_id(previous_result),
            status="success",
            data={"final_answer": answer, "selected_competition": selected},
            message="MainAgent completed conversational follow-up.",
            metadata={
                "followup_type": "competition_detail",
                "generation_source": "llm" if generated.get("content") else "fallback",
                "generation_error": generated.get("error"),
            },
        )

    def _is_competition_detail_request(self, message: str) -> bool:
        text = str(message or "").strip()
        return any(keyword in text for keyword in [
            "详细了解", "详细介绍", "具体介绍", "竞赛详情", "项目详情",
            "展开说说", "详细说说", "第一个", "第二个", "第三个",
        ])

    def _recommendations_from_result(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        for agent_result in result.get("data", {}).get("agent_results", []):
            recommendations = agent_result.get("data", {}).get("recommendations")
            if isinstance(recommendations, list) and recommendations:
                return [item for item in recommendations if isinstance(item, dict)]
        return []

    def _select_recommendation_for_detail(
        self,
        recommendations: list[dict[str, Any]],
        message: str,
    ) -> dict[str, Any]:
        ordinal_map = {
            "第一个": 0, "第一项": 0, "第1个": 0,
            "第二个": 1, "第二项": 1, "第2个": 1,
            "第三个": 2, "第三项": 2, "第3个": 2,
        }
        for marker, index in ordinal_map.items():
            if marker in message and index < len(recommendations):
                return recommendations[index]

        query = str(message or "").strip()
        for phrase in [
            "我想", "详细了解", "详细介绍", "具体介绍", "竞赛详情", "项目详情",
            "展开说说", "详细说说", "一下", "这个", "竞赛", "项目",
        ]:
            query = query.replace(phrase, "")
        query = query.strip(" ，。！？：:、“”'\"")
        if query:
            tokens = re.findall(r"[A-Za-z0-9+]+|[\u4e00-\u9fff]{2,}", query)
            for recommendation in recommendations:
                title = str(recommendation.get("title", ""))
                if query in title or any(token in title for token in tokens):
                    return recommendation
        return recommendations[0]

    def _build_competition_detail_fallback(self, selected: dict[str, Any]) -> str:
        title = str(selected.get("title") or "未命名项目")
        lines = [f"### {title}"]
        fields = [
            ("", selected.get("summary")),
            ("主办方", selected.get("organizer")),
            ("截止日期", selected.get("deadline")),
            ("适合你的原因", selected.get("reason")),
            ("注意事项", selected.get("risk")),
        ]
        for label, value in fields:
            value = str(value or "").strip()
            if not value or value.lower() == "unknown":
                continue
            lines.append(value if not label else f"- **{label}：** {value}")
        return "\n\n".join(lines)

    def _call_detail_llm(
        self,
        user_input: str,
        selected: dict[str, Any],
    ) -> dict[str, Any]:
        llm_config = self.config.get("llm", {}) if isinstance(self.config, dict) else {}
        api_key_env = llm_config.get("api_key_env", "DEEPSEEK_API_KEY")
        api_key = llm_config.get("api_key", "") or os.getenv(str(api_key_env), "")
        if not api_key:
            return {"content": "", "error": f"Missing API key in {api_key_env}."}

        base_url = llm_config.get("base_url") or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model = llm_config.get("model") or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        source_data = {
            key: selected.get(key, "")
            for key in ["title", "summary", "deadline", "organizer", "type", "reason", "risk", "source_url"]
        }
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是大学生竞赛顾问。只能根据提供的数据回答，不得虚构。"
                        "请用中文简要说明竞赛概况、适合人群、时间提醒、与用户的匹配原因，"
                        "并指出仍需到官网核实的信息。回答控制在600字以内。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"用户问题：{user_input}\n竞赛数据：{json.dumps(source_data, ensure_ascii=False)}",
                },
            ],
            "temperature": 0.2,
            "max_tokens": 900,
        }
        request = urllib.request.Request(
            url=base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=int(llm_config.get("timeout", 30))) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            content = str(response_data["choices"][0]["message"]["content"] or "").strip()
            return {"content": content, "error": None}
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError) as exc:
            return {"content": "", "error": {"type": exc.__class__.__name__, "message": str(exc)}}

    def plan_task(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Use an optional LLM planner, then fall back to deterministic rules."""
        fallback_agents = self.select_agents(input_data)
        fallback_plan = self._build_rule_plan(input_data, fallback_agents)

        # Explicit task types come from the UI/API contract. Their dependency
        # chain must be determined by the data that is actually present, not
        # replaced by a free-form LLM plan that may request unavailable inputs.
        task_type = str(input_data.get("task_type", "")).lower()
        explicit_task_types = {
            "collect", "info_collect", "data_collect",
            "extract", "info_extract",
            "recommend", "recommendation",
            "material", "generate_material",
            "full_process", "application_assistant", "mvp_demo",
        }
        if task_type in explicit_task_types:
            return fallback_plan

        if not self._is_llm_enabled():
            return fallback_plan

        llm_plan = self._call_llm_planner(input_data)
        if not llm_plan.get("ok"):
            fallback_plan["planning_error"] = llm_plan.get("error")
            return fallback_plan

        normalized_plan = self._normalize_planning_result(llm_plan.get("data", {}))
        if not normalized_plan.get("selected_agents") and not normalized_plan.get("need_user_input"):
            fallback_plan["planning_error"] = {"message": "LLM returned no usable selected_agents."}
            return fallback_plan

        normalized_plan["planning_source"] = "llm"
        return normalized_plan

    def select_agents(self, input_data: dict[str, Any]) -> list[str]:
        """Deterministic fallback scheduler."""
        task_type = str(input_data.get("task_type", "")).lower()
        user_input = str(input_data.get("user_input", "")).lower()
        payload = input_data.get("input_data", {})

        if task_type in {"collect", "info_collect", "data_collect"}:
            return ["info_collect"]
        if task_type in {"extract", "info_extract"}:
            return ["info_extract"]
        if task_type in {"recommend", "recommendation"}:
            if payload.get("structured_items") or payload.get("projects"):
                return ["recommendation"]
            if self._has_raw_text_input(payload):
                return ["info_extract", "recommendation"]
            return ["info_collect", "info_extract", "recommendation"]
        if task_type in {"material", "generate_material"}:
            if payload.get("project_info") or payload.get("structured_items") or payload.get("projects"):
                return ["material"]
            if self._has_raw_text_input(payload):
                return ["info_extract", "material"]
            return ["material"]
        if task_type in {"full_process", "application_assistant", "mvp_demo"}:
            return self._select_full_process_agents(payload)

        selected = []
        if any(keyword in user_input for keyword in ["notice", "extract", "field", "deadline"]):
            selected.append("info_extract")
        if any(keyword in user_input for keyword in ["recommend", "match", "project", "competition"]):
            selected.extend(["info_collect", "recommendation"])
        if any(keyword in user_input for keyword in ["material", "application", "statement", "plan"]):
            selected.append("material")

        # Chinese keywords are encoded as unicode escapes to avoid source encoding issues.
        chinese_rules = [
            (["\u901a\u77e5", "\u62bd\u53d6", "\u5b57\u6bb5"], "info_extract"),
            (["\u63a8\u8350", "\u5339\u914d", "\u9879\u76ee", "\u7ade\u8d5b"], "recommendation"),
            (["\u6750\u6599", "\u7533\u8bf7", "\u6587\u4e66", "\u8ba1\u5212"], "material"),
        ]
        for keywords, agent_key in chinese_rules:
            if any(keyword in user_input for keyword in keywords):
                if agent_key == "recommendation":
                    selected.extend(["info_collect", "recommendation"])
                else:
                    selected.append(agent_key)

        return self._deduplicate(selected) or self._select_full_process_agents(payload)

    def integrate_results(
        self,
        input_data: dict[str, Any],
        agent_results: list[dict[str, Any]],
        planning: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        planning = planning or {}
        successful_data = {
            result.get("agent_name", f"agent_{index}"): result.get("data", {})
            for index, result in enumerate(agent_results)
            if result.get("status") in {"success", "partial"}
        }
        errors = [
            {
                "agent_name": result.get("agent_name", "unknown"),
                "status": result.get("status", "failed"),
                "error": result.get("error"),
                "message": result.get("message", ""),
            }
            for result in agent_results
            if result.get("status") in {"failed", "skipped"}
        ]

        return {
            "task_summary": {
                "task_type": input_data.get("task_type"),
                "user_input": input_data.get("user_input"),
            },
            "planning": planning,
            "agent_results": agent_results,
            "integrated_data": successful_data,
            "errors": errors,
            "final_answer": self._build_final_answer(agent_results, planning),
            "next_action": planning.get("suggested_next_action") or self._suggest_next_action(errors),
        }

    def _call_llm_planner(self, input_data: dict[str, Any]) -> dict[str, Any]:
        llm_config = self.config.get("llm", {}) if isinstance(self.config, dict) else {}
        api_key_env = llm_config.get("api_key_env", os.getenv("SAIZHITONG_LLM_API_KEY_ENV", "DEEPSEEK_API_KEY"))
        api_key = llm_config.get("api_key", "")
        if not api_key and isinstance(api_key_env, str) and api_key_env.startswith("sk-"):
            api_key = api_key_env
        if not api_key:
            api_key = os.getenv(str(api_key_env), "")
        if not api_key:
            return {"ok": False, "error": {"message": f"Missing API key in {api_key_env}."}}

        base_url = llm_config.get("base_url") or os.getenv("DEEPSEEK_BASE_URL") or os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
        model = llm_config.get("model") or os.getenv("DEEPSEEK_MODEL") or os.getenv("OPENAI_MODEL", "deepseek-chat")
        timeout = int(llm_config.get("timeout", 30))
        url = base_url.rstrip("/") + "/chat/completions"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": self._build_planner_system_prompt()},
                {"role": "user", "content": self._build_planner_user_prompt(input_data)},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        request = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            content = response_data["choices"][0]["message"]["content"]
            return {"ok": True, "data": self._parse_json_object(content)}
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError) as exc:
            return {"ok": False, "error": {"type": exc.__class__.__name__, "message": str(exc)}}

    def _is_llm_enabled(self) -> bool:
        llm_config = self.config.get("llm", {}) if isinstance(self.config, dict) else {}
        configured = bool(llm_config.get("enabled", False))
        env_enabled = os.getenv("SAIZHITONG_LLM_ENABLED", "").lower() in {"1", "true", "yes"}
        deepseek_key_exists = bool(os.getenv("DEEPSEEK_API_KEY", ""))
        gemini_key_exists = bool(os.getenv("GEMINI_API_KEY", ""))
        return configured or env_enabled or deepseek_key_exists or gemini_key_exists

    def _build_planner_system_prompt(self) -> str:
        return """
You are the Main Agent of a multi-agent system named SaiZhiTong.
The system helps university students find suitable research projects, competitions, and application opportunities, then assists with recommendation and application materials.

Your responsibility is not to complete the whole task yourself.
Your responsibility is to understand the user request, decide which sub agents should be called, and define what each sub agent should do.

Available sub agents:
1. info_collect: collects project or competition information from local data, web data, uploaded files, or APIs.
2. info_extract: extracts structured fields from unstructured text, such as title, deadline, requirements, materials, links, organizer, category.
3. recommendation: matches projects with the user profile and provides ranking, scoring, reasons, or Top-N results.
4. material: generates application checklist, application reason, project introduction, personal statement draft, research plan, timeline, or preparation suggestions.

Return valid JSON only. Do not output markdown. Do not explain outside JSON.

Required JSON schema:
{
  "task_type": "",
  "selected_agents": [],
  "reason": "",
  "agent_tasks": {
    "info_collect": "",
    "info_extract": "",
    "recommendation": "",
    "material": ""
  },
  "missing_information": [],
  "need_user_input": false,
  "suggested_next_action": ""
}

Task type must be one of: info_collect, info_extract, recommendation, material, full_process, qa, unknown.
Only use these agent names: info_collect, info_extract, recommendation, material.
If the user wants project recommendation from raw sources, select info_collect, info_extract, and recommendation.
If the user wants recommendation and application materials from raw sources, select info_collect, info_extract, recommendation, and material.
If the user provides notice text and asks to extract fields, select info_extract.
If the user provides notice text and wants recommendation, select info_extract and recommendation.
If the user wants complete application assistance, select info_collect, recommendation, material, and include info_extract only when notice text exists.
If the user only wants materials based on known project information, select material.
If no agent is needed, selected_agents must be empty.
""".strip()

    def _build_planner_user_prompt(self, input_data: dict[str, Any]) -> str:
        planner_input = {
            "task_id": input_data.get("task_id"),
            "user_input": input_data.get("user_input"),
            "task_type": input_data.get("task_type"),
            "user_profile": input_data.get("user_profile"),
            "context": input_data.get("context"),
            "input_data": input_data.get("input_data"),
            "history": input_data.get("history"),
            "required_output": input_data.get("required_output"),
            "metadata": input_data.get("metadata"),
        }
        return "Analyze this standard input and return the planning JSON:\n" + json.dumps(
            planner_input,
            ensure_ascii=False,
            indent=2,
        )

    def _parse_json_object(self, value: str) -> dict[str, Any]:
        value = value.strip()
        if value.startswith("```"):
            value = value.strip("`")
            if value.lower().startswith("json"):
                value = value[4:].strip()
        start = value.find("{")
        end = value.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise json.JSONDecodeError("No JSON object found", value, 0)
        return json.loads(value[start : end + 1])

    def _normalize_planning_result(self, plan: dict[str, Any]) -> dict[str, Any]:
        selected_agents = self._deduplicate(
            [agent for agent in plan.get("selected_agents", []) if agent in self.allowed_agents]
        )
        agent_tasks = plan.get("agent_tasks", {})
        if not isinstance(agent_tasks, dict):
            agent_tasks = {}

        return {
            "task_type": str(plan.get("task_type", "unknown")),
            "selected_agents": selected_agents,
            "reason": str(plan.get("reason", "")),
            "agent_tasks": {
                "info_collect": str(agent_tasks.get("info_collect", "")),
                "info_extract": str(agent_tasks.get("info_extract", "")),
                "recommendation": str(agent_tasks.get("recommendation", "")),
                "material": str(agent_tasks.get("material", "")),
            },
            "missing_information": plan.get("missing_information", []) if isinstance(plan.get("missing_information", []), list) else [],
            "need_user_input": bool(plan.get("need_user_input", False)),
            "suggested_next_action": str(plan.get("suggested_next_action", "")),
        }

    def _build_rule_plan(self, input_data: dict[str, Any], selected_agents: list[str]) -> dict[str, Any]:
        return {
            "task_type": input_data.get("task_type") or "unknown",
            "selected_agents": selected_agents,
            "reason": "Rule-based fallback planning was used.",
            "agent_tasks": {
                "info_collect": "Collect project or competition information." if "info_collect" in selected_agents else "",
                "info_extract": "Extract structured fields from notice or raw text." if "info_extract" in selected_agents else "",
                "recommendation": "Match projects with user profile and rank results." if "recommendation" in selected_agents else "",
                "material": "Generate application checklist and draft materials." if "material" in selected_agents else "",
            },
            "missing_information": [],
            "need_user_input": False,
            "suggested_next_action": "Run selected agents in order and integrate their outputs.",
            "planning_source": "rule",
        }

    def _load_sub_agents(self) -> dict[str, Any]:
        loaded_agents = {}
        for agent_key, (module_name, class_name) in self.sub_agent_specs.items():
            try:
                module = import_module(module_name)
                agent_class = getattr(module, class_name)
                loaded_agents[agent_key] = agent_class(self.config)
            except Exception as exc:
                loaded_agents[agent_key] = {
                    "load_error": {
                        "type": exc.__class__.__name__,
                        "message": str(exc),
                        "module": module_name,
                        "class": class_name,
                    }
                }
        return loaded_agents

    def _call_sub_agent(self, agent_key: str, agent_input: dict[str, Any]) -> dict[str, Any]:
        agent = self.sub_agents.get(agent_key)
        task_id = self._get_task_id(agent_input)

        if isinstance(agent, dict) and "load_error" in agent:
            return self._build_output(
                task_id=task_id,
                agent_name=self.sub_agent_specs[agent_key][1],
                status="skipped",
                data={},
                message=f"{agent_key} is not ready and was skipped.",
                error=agent["load_error"],
            )

        try:
            result = agent.run(agent_input)
            return self._normalize_agent_output(agent_key, task_id, result)
        except Exception as exc:
            return self._build_output(
                task_id=task_id,
                agent_name=self.sub_agent_specs[agent_key][1],
                status="failed",
                data={},
                message=f"{agent_key} execution failed.",
                error={"type": exc.__class__.__name__, "message": str(exc)},
            )

    def _build_agent_input(
        self,
        original_input: dict[str, Any],
        agent_key: str,
        previous_results: list[dict[str, Any]],
        shared_context: dict[str, Any],
    ) -> dict[str, Any]:
        agent_input = dict(original_input)
        agent_input["context"] = shared_context
        agent_input["metadata"] = {
            **original_input.get("metadata", {}),
            "called_by": self.agent_name,
            "target_agent": agent_key,
            "previous_agent_count": len(previous_results),
        }
        agent_input["history"] = [
            *original_input.get("history", []),
            {"role": self.agent_name, "event": f"dispatch_to_{agent_key}"},
        ]
        if agent_key == "info_collect":
            agent_input["input_data"] = self._adapt_info_collect_input(original_input)
        elif agent_key == "info_extract":
            agent_input["input_data"] = self._adapt_info_extract_input(
                original_input, shared_context
            )
        elif agent_key == "recommendation":
            agent_input["input_data"] = self._adapt_recommendation_input(
                original_input, shared_context
            )
        elif agent_key == "material":
            agent_input["input_data"] = self._adapt_material_input(
                original_input, shared_context
            )
        return agent_input

    def _adapt_info_collect_input(self, original_input: dict[str, Any]) -> dict[str, Any]:
        """Map the web form fields to InfoCollectAgent without changing its API."""
        payload = dict(original_input.get("input_data", {}))
        if payload.get("sources"):
            return payload

        data_source = str(payload.get("data_source", "")).lower()
        source_url = str(payload.get("source_url", "")).lower()
        sources = []

        if data_source in {"web", "mixed"} and (
            not source_url or "saikr.com" in source_url
        ):
            sources.append("saikr")
        if data_source in {"upload", "mixed"} and payload.get("file_paths"):
            sources.append("local_file")

        if sources:
            payload["sources"] = sources
        if "saikr" in sources and not payload.get("keywords"):
            interests = original_input.get("user_profile", {}).get("interests", [])
            payload["keywords"] = interests or [str(original_input.get("user_input", ""))]
        return payload

    def _adapt_info_extract_input(
        self,
        original_input: dict[str, Any],
        shared_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Provide raw items from collection results or pasted notice text."""
        payload = dict(original_input.get("input_data", {}))
        if payload.get("raw_items"):
            return payload

        collect_result = shared_context.get("info_collect_result", {})
        if isinstance(collect_result, dict) and collect_result.get("raw_items"):
            payload["raw_items"] = collect_result["raw_items"]
            return payload

        raw_text = (
            payload.get("notification_text")
            or payload.get("raw_text")
            or payload.get("raw_project_text")
        )
        if raw_text:
            payload["raw_items"] = [{
                "title": "",
                "url": payload.get("source_url", ""),
                "source": payload.get("data_source", "user_input"),
                "raw_text": str(raw_text),
                "publish_date": "",
                "collected_at": "",
            }]
            return payload

        projects = payload.get("projects")
        if isinstance(projects, list):
            raw_items = []
            for project in projects:
                if isinstance(project, dict):
                    item = dict(project)
                    item.setdefault("raw_text", json.dumps(project, ensure_ascii=False))
                    raw_items.append(item)
            if raw_items:
                payload["raw_items"] = raw_items
        return payload

    def _adapt_recommendation_input(
        self,
        original_input: dict[str, Any],
        shared_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Provide structured items produced by InfoExtractAgent."""
        payload = dict(original_input.get("input_data", {}))
        if payload.get("structured_items"):
            return payload

        extract_result = shared_context.get("info_extract_result", {})
        if isinstance(extract_result, dict) and extract_result.get("structured_items"):
            payload["structured_items"] = extract_result["structured_items"]
            return payload

        projects = payload.get("projects")
        if isinstance(projects, list) and projects:
            payload["structured_items"] = projects
        return payload

    def _adapt_material_input(
        self,
        original_input: dict[str, Any],
        shared_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build MaterialAgent input from explicit or recommended project data."""
        payload = dict(original_input.get("input_data", {}))
        payload.setdefault("user_profile", original_input.get("user_profile", {}))

        project_info = payload.get("project_info")
        if isinstance(project_info, dict) and project_info:
            project_info = dict(project_info)
            project_info.setdefault(
                "project_name",
                project_info.get("title") or project_info.get("name", ""),
            )
            payload["project_info"] = project_info
            return payload

        structured_items = payload.get("structured_items")
        if not isinstance(structured_items, list) or not structured_items:
            extract_result = shared_context.get("info_extract_result", {})
            structured_items = (
                extract_result.get("structured_items", [])
                if isinstance(extract_result, dict)
                else []
            )

        selected_title = ""
        recommendation_result = shared_context.get("recommendation_result", {})
        if isinstance(recommendation_result, dict):
            recommendations = recommendation_result.get("recommendations", [])
            if recommendations:
                selected_title = str(recommendations[0].get("title", ""))

        selected = None
        for item in structured_items or []:
            if isinstance(item, dict) and (
                not selected_title or str(item.get("title", "")) == selected_title
            ):
                selected = dict(item)
                break

        if selected is None:
            projects = payload.get("projects", [])
            if isinstance(projects, list) and projects and isinstance(projects[0], dict):
                selected = dict(projects[0])

        if selected is not None:
            title = selected.get("project_name") or selected.get("title") or selected_title
            selected["project_name"] = str(title or "")
            payload["project_info"] = selected
            payload.setdefault("competition_info", {
                "competition_name": str(selected.get("title", "")),
                "competition_type": str(selected.get("type", "")),
                "deadline": str(selected.get("deadline", "")),
                "organizer": str(selected.get("organizer", "")),
            })
        return payload

    def _normalize_agent_output(self, agent_key: str, task_id: str, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            return self._build_output(
                task_id=task_id,
                agent_name=self.sub_agent_specs[agent_key][1],
                status="failed",
                data={},
                message="Sub agent returned invalid output type.",
                error={"message": "Agent output must be a dict."},
            )

        output = self._build_output(
            task_id=result.get("task_id", task_id),
            agent_name=result.get("agent_name", self.sub_agent_specs[agent_key][1]),
            status=result.get("status", "success"),
            data=result.get("data", {}),
            message=result.get("message", ""),
            error=result.get("error"),
            next_action=result.get("next_action"),
            metadata=result.get("metadata", {}),
        )

        if output["status"] not in {"success", "failed", "partial", "need_input", "skipped"}:
            output["status"] = "partial"
            output["metadata"]["normalization_warning"] = "Unknown status was converted to partial."

        return output

    def _select_full_process_agents(self, payload: dict[str, Any]) -> list[str]:
        if payload.get("structured_items") or payload.get("projects"):
            selected = ["recommendation", "material"]
        elif self._has_raw_text_input(payload):
            selected = ["info_extract", "recommendation", "material"]
        else:
            selected = ["info_collect", "info_extract", "recommendation", "material"]
        return selected

    @staticmethod
    def _has_raw_text_input(payload: dict[str, Any]) -> bool:
        return bool(
            payload.get("notification_text")
            or payload.get("raw_text")
            or payload.get("raw_project_text")
            or payload.get("raw_items")
        )

    def _build_final_answer(self, agent_results: list[dict[str, Any]], planning: dict[str, Any] | None = None) -> str:
        planning = planning or {}
        if planning.get("need_user_input"):
            missing = ", ".join(str(item) for item in planning.get("missing_information", []))
            return f"More user input is needed: {missing}" if missing else "More user input is needed."

        if not agent_results:
            return "No agent was selected."

        lines = []
        for result in agent_results:
            agent_name = result.get("agent_name", "unknown")
            status = result.get("status", "unknown")
            message = result.get("message", "")
            lines.append(f"- {agent_name}: {status}. {message}".strip())
        return "\n".join(lines)

    def _resolve_final_status(self, agent_results: list[dict[str, Any]], planning: dict[str, Any] | None = None) -> str:
        planning = planning or {}
        if planning.get("need_user_input"):
            return "need_input"
        if not agent_results:
            return "success" if not planning.get("selected_agents") else "failed"

        statuses = {result.get("status") for result in agent_results}
        if statuses <= {"success"}:
            return "success"
        if "success" in statuses or "partial" in statuses:
            return "partial"
        if "need_input" in statuses:
            return "need_input"
        return "failed"

    def _suggest_next_action(self, errors: list[dict[str, Any]]) -> str | None:
        if not errors:
            return None
        return "Check skipped or failed sub agents, then rerun the same standard input."

    def _deduplicate(self, items: list[str]) -> list[str]:
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    def _get_task_id(self, input_data: Any) -> str:
        if isinstance(input_data, dict) and input_data.get("task_id"):
            return str(input_data["task_id"])
        return "unknown_task"

    def _build_output(
        self,
        task_id: str,
        status: str,
        data: dict[str, Any],
        message: str,
        error: Any = None,
        next_action: Any = None,
        metadata: dict[str, Any] | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        return {
            "task_id": task_id,
            "agent_name": agent_name or self.agent_name,
            "status": status,
            "data": data,
            "message": message,
            "error": error,
            "next_action": next_action,
            "metadata": metadata or {},
        }


if __name__ == "__main__":
    demo_input = {
        "task_id": "demo_task_001",
        "user_input": "Please recommend suitable research competitions and generate an application checklist.",
        "task_type": "full_process",
        "user_profile": {
            "major": "computer science",
            "grade": "junior",
            "interests": ["AI", "data analysis"],
        },
        "context": {},
        "input_data": {},
        "history": [],
        "required_output": "markdown",
        "metadata": {"source": "main_agent_demo"},
    }

    agent = MainAgent(config={})
    print(json.dumps(agent.run(demo_input), ensure_ascii=False, indent=2))




