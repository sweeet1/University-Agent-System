"""
InfoExtractAgent — 信息抽取 Agent
===================================
负责将非结构化通知文本（竞赛/科研项目）转换为结构化 JSON 数据。

规范遵循：PROJECT_SPEC_CN.md §12.2
文件位置：agents/info_extract_agent.py
类名：InfoExtractAgent
接口：run(input_data: dict) -> dict
"""

import json
import re
import time
import os
import importlib.util
import yaml
from typing import Optional, Any


class InfoExtractAgent:
    """从高校竞赛/科研通知文本中抽取结构化信息。"""

    # ── 类常量 ────────────────────────────────────────────
    AGENT_NAME = "info_extract_agent"

    VALID_TYPES = {"学科竞赛", "科研项目", "创新创业", "社会实践", "其他"}

    VALID_GRADES = {"大一", "大二", "大三", "大四", "大五"}

    VALID_EDUCATION = {"本科", "硕士", "博士"}

    VALID_TEAM_REQUIREMENT = {"单人", "组队", "不限", ""}

    REQUIRED_FIELDS = [
        "title", "type", "deadline", "registration_time",
        "requirements", "reward", "organizer", "source_url", "summary"
    ]

    REQUIRED_REQUIREMENT_FIELDS = [
        "target_majors", "target_grades", "target_education",
        "required_skills", "team_requirement", "tags", "category"
    ]

    FIELD_DEFAULTS = {
        "title": "unknown",
        "type": "其他",
        "deadline": "unknown",
        "registration_time": "unknown",
        "requirements": {
            "target_majors": [],
            "target_grades": [],
            "target_education": [],
            "required_skills": [],
            "team_requirement": "不限",
            "tags": [],
            "category": "unknown",
        },
        "reward": "unknown",
        "organizer": "unknown",
        "source_url": "",
        "summary": "unknown",
    }

    DEADLINE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def __init__(self, config: Optional[dict] = None):
        """
        初始化 Agent。

        Args:
            config: 配置字典。若为 None，从 config/config.yaml 读取。
                    必须包含 model 和 api 相关字段。
        """
        self.config = self._load_config(config)
        self.prompt_config = self._load_prompt_config()
        self.system_prompt = self.prompt_config.get("system", "")
        self.user_template = self.prompt_config.get("user_template", "")
        self.output_schema = self.prompt_config.get("output_schema", {})

        self._openai_available = False
        # 使用 find_spec 检查 openai 是否已安装（可选依赖，未安装时自动 Mock）
        if importlib.util.find_spec("openai") is not None:
            import openai  # type: ignore[no-redef]
            self.openai = openai
            self._openai_available = True

    # ── 配置加载 ─────────────────────────────────────────

    def _load_config(self, config: Optional[dict]) -> dict:
        """加载项目配置。"""
        if config is not None:
            return config

        config_paths = [
            os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml"),
            os.path.join(os.getcwd(), "config", "config.yaml"),
        ]
        for p in config_paths:
            p = os.path.normpath(p)
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        return {}

    def _load_prompt_config(self) -> dict:
        """加载抽取 Prompt 模板配置。"""
        prompt_file = (
            self.config.get("agent", {})
            .get("info_extract", {})
            .get("prompt_file", "")
        )
        if prompt_file:
            prompt_path = os.path.normpath(
                os.path.join(os.path.dirname(__file__), "..", prompt_file)
            )
        else:
            prompt_path = os.path.normpath(
                os.path.join(
                    os.path.dirname(__file__), "..",
                    "config", "extraction_prompt.yaml"
                )
            )

        if os.path.isfile(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    # ── 对外唯一入口 ─────────────────────────────────────

    def run(self, input_data: dict) -> dict:
        """
        Agent 唯一对外入口。

        输入（统一规范 §5）：
        {
            "task_id": "xxx",
            "user_input": "...",
            "task_type": "info_extract",
            "user_profile": {},
            "context": {},
            "input_data": {
                "raw_items": [
                    {
                        "title": "...",
                        "url": "...",
                        "source": "...",
                        "raw_text": "...",
                        "publish_date": "...",
                        "collected_at": "..."
                    }
                ],
                "extract_fields": [...]
            },
            "history": [],
            "required_output": "json",
            "metadata": {}
        }

        输出（统一规范 §6）：
        {
            "task_id": "xxx",
            "agent_name": "info_extract_agent",
            "status": "success|partial|failed",
            "data": { "structured_items": [...] },
            "message": "...",
            "error": null | {...},
            "next_action": null | "...",
            "metadata": {...}
        }
        """
        task_id = input_data.get("task_id", "")
        metadata = {"start_time": time.strftime("%Y-%m-%d %H:%M:%S")}

        # 1. 输入校验
        valid, err_msg = self.validate_input(input_data)
        if not valid:
            return self._build_response(
                task_id=task_id,
                status="failed",
                data={},
                message=f"输入校验失败: {err_msg}",
                error={
                    "error_type": "ValidationError",
                    "error_message": err_msg,
                    "suggestion": "请检查 input_data 中的 raw_items 格式是否正确。",
                },
                metadata=metadata,
            )

        # 2. 核心处理
        try:
            result_data = self.process(input_data)
        except Exception as e:
            return self._build_response(
                task_id=task_id,
                status="failed",
                data={},
                message=f"处理异常: {str(e)}",
                error={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "suggestion": "请检查 LLM API 配置或输入数据。",
                },
                metadata=metadata,
            )

        # 3. 判断整体状态
        structured_items = result_data.get("structured_items", [])
        success_count = sum(
            1 for it in structured_items
            if it.get("_extract_status") == "success"
        )
        failed_count = sum(
            1 for it in structured_items
            if it.get("_extract_status") == "failed"
        )

        if failed_count == 0:
            status = "success"
            message = f"全部 {success_count} 条文本抽取成功。"
        elif success_count > 0:
            status = "partial"
            message = f"部分成功：{success_count} 条成功，{failed_count} 条失败。"
        else:
            status = "failed"
            message = f"全部 {failed_count} 条文本抽取失败。"

        return self._build_response(
            task_id=task_id,
            status=status,
            data=result_data,
            message=message,
            metadata=metadata,
        )

    # ── 输入校验 ─────────────────────────────────────────

    def validate_input(self, input_data: dict):
        """
        校验输入格式。

        Returns:
            (bool, str): (是否合法, 错误信息)
        """
        if "input_data" not in input_data:
            return False, "缺少 input_data 字段。"

        inner = input_data["input_data"]
        if not isinstance(inner, dict):
            return False, "input_data 必须是 dict 类型。"

        if "raw_items" not in inner:
            return False, "input_data 中缺少 raw_items 字段。"

        raw_items = inner["raw_items"]
        if not isinstance(raw_items, list):
            return False, "raw_items 必须是 list 类型。"

        if len(raw_items) == 0:
            return False, "raw_items 不能为空。"

        for i, item in enumerate(raw_items):
            if not isinstance(item, dict):
                return False, f"raw_items[{i}] 必须是 dict 类型。"
            if "raw_text" not in item or not item["raw_text"]:
                return False, f"raw_items[{i}] 缺少 raw_text 或为空。"

        return True, ""

    # ── 核心业务逻辑 ─────────────────────────────────────

    def process(self, input_data: dict) -> dict:
        """
        对每条通知文本调用 LLM 抽取结构化信息。

        Args:
            input_data: 统一输入格式

        Returns:
            {"structured_items": [...]}
        """
        inner = input_data.get("input_data", {})
        raw_items = inner.get("raw_items", [])

        structured_items = []
        total = len(raw_items)

        for i, raw_item in enumerate(raw_items):
            raw_text = raw_item.get("raw_text", "")
            source_url = raw_item.get("url", raw_item.get("source_url", ""))

            try:
                print(f"[抽取] ({i+1}/{total}) {raw_item.get('title','')[:50]} ...")
                extracted = self._call_llm_extract(raw_text, source_url)
                validated = self._validate_and_fix(extracted)
                if not validated.get("source_url") or validated["source_url"] == "unknown":
                    validated["source_url"] = source_url
                validated["_extract_status"] = "success"
                validated["_source_title"] = raw_item.get("title", "")
                validated["_source"] = raw_item.get("source", "")
                validated["_collected_at"] = raw_item.get("collected_at", "")
                structured_items.append(validated)
            except KeyboardInterrupt:
                print(f"\n[中断] 用户取消，已保存前 {i} 条结果。")
                # 把剩余未处理的标记为 skipped
                for remaining in raw_items[i:]:
                    structured_items.append({
                        "title": remaining.get("title", "unknown"),
                        "type": "其他",
                        "deadline": "unknown",
                        "registration_time": "unknown",
                        "requirements": dict(self.FIELD_DEFAULTS["requirements"]),
                        "reward": "unknown",
                        "organizer": "unknown",
                        "source_url": remaining.get("url", ""),
                        "summary": "unknown",
                        "_extract_status": "skipped",
                        "_extract_error": "用户中断",
                        "_source_title": remaining.get("title", ""),
                        "_source": remaining.get("source", ""),
                        "_collected_at": remaining.get("collected_at", ""),
                    })
                break
            except Exception as e:
                # 单条失败不中断整体流程
                print(f"  [失败] {e}")
                structured_items.append({
                    "title": raw_item.get("title", "unknown"),
                    "type": "其他",
                    "deadline": "unknown",
                    "registration_time": "unknown",
                    "requirements": dict(self.FIELD_DEFAULTS["requirements"]),
                    "reward": "unknown",
                    "organizer": "unknown",
                    "source_url": source_url,
                    "summary": "unknown",
                    "_extract_status": "failed",
                    "_extract_error": str(e),
                    "_source_title": raw_item.get("title", ""),
                    "_source": raw_item.get("source", ""),
                    "_collected_at": raw_item.get("collected_at", ""),
                })

        return {"structured_items": structured_items}

    # ── LLM 调用 ─────────────────────────────────────────

    def _call_llm_extract(self, raw_text: str, source_url: str) -> dict:
        """
        调用 LLM API 进行信息抽取。

        Args:
            raw_text: 通知原文
            source_url: 来源链接

        Returns:
            LLM 返回的 dict

        Raises:
            RuntimeError: API 调用失败
        """
        user_prompt = self.user_template.format(
            raw_text=raw_text,
            source_url=source_url,
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response_text = self._call_api(messages)
        return self._parse_llm_json(response_text)

    def _call_api(self, messages: list) -> str:
        """
        调用 OpenAI 兼容 API，未配置时回退到 Mock 模式。
        """
        llm_config = self.config.get("llm", {})
        model_config = self.config.get("model", {}) or llm_config
        api_config = self.config.get("api", {})

        api_key_env = llm_config.get("api_key_env", "DEEPSEEK_API_KEY")
        api_key = api_config.get("key", "") or os.getenv(api_key_env, "")
        base_url = api_config.get("base_url", "") or llm_config.get("base_url", "")
        model_name = model_config.get("name", "") or model_config.get("model", "")
        temperature = model_config.get("temperature", 0.3)
        max_tokens = model_config.get("max_tokens", 2048)

        # 如果没有 openai 库或 API 未配置，回退到 Mock
        if not self._openai_available:
            return self._mock_extract(messages)
        if not api_key or not base_url:
            return self._mock_extract(messages)

        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = self.openai.OpenAI(**client_kwargs)

        timeout = self.config.get("agent", {}).get("timeout", 60)
        max_retry = self.config.get("agent", {}).get("max_retry", 3)
        last_error = None

        for attempt in range(max_retry):
            try:
                print(f"  [API] 第 {attempt+1}/{max_retry} 次调用 {model_name} ...")
                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
                print(f"  [API] 调用成功")
                return response.choices[0].message.content
            except KeyboardInterrupt:
                print(f"  [API] 用户中断，正在退出...")
                raise
            except Exception as e:
                last_error = e
                print(f"  [API] 调用失败: {type(e).__name__}: {e}")
                if attempt < max_retry - 1:
                    wait = 1 * (attempt + 1)
                    print(f"  [API] {wait}s 后重试...")
                    time.sleep(wait)
                continue

        raise RuntimeError(
            f"LLM API 调用失败（已重试 {max_retry} 次）: {last_error}"
        )

    def _mock_extract(self, messages: list) -> str:
        """
        Mock 模式：API 未配置时返回默认 JSON 占位。
        正式开发时请在 config.yaml 填入真实 API 配置。
        """
        return json.dumps(self.FIELD_DEFAULTS, ensure_ascii=False)

    # ── JSON 解析与修复 ──────────────────────────────────

    def _parse_llm_json(self, text: str) -> dict:
        """
        解析 LLM 返回文本为 dict，带多层降级策略。

        策略：
            1. 直接 json.loads
            2. 提取 ```json ... ``` 代码块
            3. 提取 ``` ... ``` 代码块
            4. 定位第一个 { 到最后一个 }
            5. 单引号替换为双引号后重试
        """
        if not text or not text.strip():
            raise ValueError("LLM 返回为空。")

        text = text.strip()

        # 策略 1：直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 策略 2：```json ... ```
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 策略 3：``` ... ```
        match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 策略 4：{ ... }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # 策略 5：单引号 → 双引号
        try:
            candidate = text.replace("'", '"')
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(candidate[start:end + 1])
        except json.JSONDecodeError:
            pass

        raise ValueError(
            f"无法解析 LLM 返回为合法 JSON。"
            f"原始返回前 200 字符: {text[:200]}"
        )

    # ── 字段校验与修复 ───────────────────────────────────

    def _validate_and_fix(self, extracted: dict) -> dict:
        """
        校验并修复抽取结果：
            1. 补全缺失字段
            2. 校验 type 枚举
            3. 校验 deadline 格式
            4. requirements 嵌套对象校验（7子字段 + 枚举约束）
        """
        result = {}

        for field in self.REQUIRED_FIELDS:
            value = extracted.get(field, self.FIELD_DEFAULTS[field])

            # ── type 枚举校验 ──
            if field == "type":
                if value not in self.VALID_TYPES:
                    value = "其他"

            # ── deadline 格式校验 ──
            if field == "deadline":
                if value != "unknown" and not self.DEADLINE_PATTERN.match(
                    str(value)
                ):
                    date_match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
                    if date_match:
                        value = date_match.group(0)
                    else:
                        value = "unknown"

            # ── requirements 嵌套对象校验 ──
            if field == "requirements":
                value = self._validate_requirements(value)

            # ── 其他字符串字段 ──
            if field not in ("requirements",):
                if not isinstance(value, str):
                    value = (
                        str(value)
                        if value is not None
                        else self.FIELD_DEFAULTS[field]
                    )

            result[field] = value

        return result

    def _validate_requirements(self, reqs: Any) -> dict:
        """
        校验并修复 requirements 嵌套对象。

        确保 7 个子字段全部存在、类型正确、枚举值合法。
        如果传入的是旧版数组格式（向后兼容），转换为新版对象。
        """
        # ── 向后兼容：旧版数组格式 → 新版嵌套对象 ──
        if isinstance(reqs, list):
            return dict(self.FIELD_DEFAULTS["requirements"])

        # ── 不是 dict → 返回默认值 ──
        if not isinstance(reqs, dict):
            return dict(self.FIELD_DEFAULTS["requirements"])

        default = self.FIELD_DEFAULTS["requirements"]
        result = {}

        # target_majors：数组
        value = reqs.get("target_majors", default["target_majors"])
        result["target_majors"] = value if isinstance(value, list) else []

        # target_grades：数组 + 枚举校验
        value = reqs.get("target_grades", default["target_grades"])
        if isinstance(value, list):
            result["target_grades"] = [
                g for g in value if g in self.VALID_GRADES
            ]
        else:
            result["target_grades"] = []

        # target_education：数组 + 枚举校验
        value = reqs.get("target_education", default["target_education"])
        if isinstance(value, list):
            result["target_education"] = [
                e for e in value if e in self.VALID_EDUCATION
            ]
        else:
            result["target_education"] = []

        # required_skills：数组
        value = reqs.get("required_skills", default["required_skills"])
        result["required_skills"] = value if isinstance(value, list) else []

        # team_requirement：字符串 + 枚举校验
        value = reqs.get("team_requirement", default["team_requirement"])
        result["team_requirement"] = (
            value if value in self.VALID_TEAM_REQUIREMENT
            else default["team_requirement"]
        )

        # tags：数组
        value = reqs.get("tags", default["tags"])
        result["tags"] = value if isinstance(value, list) else []

        # category：字符串
        value = reqs.get("category", default["category"])
        result["category"] = str(value) if value is not None else "unknown"

        return result

    # ── 响应构造 ─────────────────────────────────────────

    def _build_response(
        self,
        task_id: str,
        status: str,
        data: dict,
        message: str = "",
        error: Optional[dict] = None,
        next_action: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """构造统一输出格式。"""
        response = {
            "task_id": task_id,
            "agent_name": self.AGENT_NAME,
            "status": status,
            "data": data,
            "message": message,
            "error": error,
            "next_action": next_action,
            "metadata": metadata or {},
        }
        response["metadata"]["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        response["metadata"]["agent_version"] = "1.0"
        return response


# ── 独立测试入口 ─────────────────────────────────────────────
if __name__ == "__main__":
    """
    使用 data/raw/sample_notifications.json 进行独立测试。

    用法：
        python agents/info_extract_agent.py
    """
    import sys

    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    agent = InfoExtractAgent()

    samples_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "raw", "projects.json",
    )

    if not os.path.isfile(samples_path):
        print(f"[ERROR] 样例文件不存在: {samples_path}")
        sys.exit(1)

    with open(samples_path, "r", encoding="utf-8") as f:
        samples = json.load(f)

    # 自动适配两种数据格式：
    #   sample_notifications.json → 含 expected_output 嵌套
    #   projects.json             → 扁平结构，字段名为 url/source 等
    first_item = samples[0] if samples else {}
    is_projects_format = "url" in first_item and "expected_output" not in first_item

    raw_items = []
    for s in samples:
        if is_projects_format:
            # projects.json 格式
            raw_items.append({
                "title": s.get("title", ""),
                "url": s.get("url", ""),
                "source": s.get("source", ""),
                "raw_text": s.get("raw_text", ""),
                "publish_date": s.get("publish_date", ""),
                "collected_at": s.get("collected_at", time.strftime("%Y-%m-%d %H:%M:%S")),
            })
        else:
            # sample_notifications.json 格式
            raw_items.append({
                "title": s.get("expected_output", {}).get("title", ""),
                "url": s.get("source_url", ""),
                "source": s.get("source", ""),
                "raw_text": s.get("raw_text", ""),
                "publish_date": s.get("publish_date", ""),
                "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })

    # 构造统一输入
    test_input = {
        "task_id": "test_extract_001",
        "user_input": "批量抽取竞赛通知信息",
        "task_type": "info_extract",
        "user_profile": {},
        "context": {},
        "input_data": {
            "raw_items": raw_items,
            "extract_fields": [
                "title", "type", "deadline", "registration_time",
                "requirements", "reward", "organizer", "source_url", "summary",
            ],
        },
        "history": [],
        "required_output": "json",
        "metadata": {"test": True},
    }

    result = agent.run(test_input)

    print(f"\n{'='*60}")
    print(f"Agent: {result['agent_name']}")
    print(f"Status: {result['status']}")
    print(f"Message: {result['message']}")
    print(f"{'='*60}")

    items = result.get("data", {}).get("structured_items", [])
    for i, item in enumerate(items):
        flag = item.pop("_extract_status", "?")
        item.pop("_extract_error", None)
        item.pop("_source_title", None)
        item.pop("_source", None)
        item.pop("_collected_at", None)
        print(f"\n--- Item {i+1} [{flag}] ---")
        print(json.dumps(item, ensure_ascii=False, indent=2))
