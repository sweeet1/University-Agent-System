"""
推荐匹配 Agent 入口（兼容 MainAgent 原有导入路径）。

实现已迁移至 agents.ReAgent_New；本模块仅作薄封装转发，
便于 `main_agent.sub_agent_specs` 继续使用
`("agents.recommendation_agent", "RecommendationAgent")` 而无需改调度代码。

旧版完整实现见：agents/recommendation_agent_legacy.py
"""

from agents.ReAgent_New import RecommendationAgent
from agents.ReAgent_New.utils import (
    build_sample_input,
    enrollment_to_grade,
    load_config,
    load_json_file,
    project_root,
    resolve_path,
)

# 兼容旧测试 / 脚本中的私有名
_enrollment_to_grade = enrollment_to_grade
_load_config = load_config
_load_json_file = load_json_file
_project_root = project_root
_resolve_path = resolve_path


def build_input_from_integration_files(*_args, **kwargs):
    """兼容旧函数名，转发到 build_sample_input。"""
    return build_sample_input(
        config=kwargs.get("config"),
        sample_path=kwargs.get("sample_path") or kwargs.get("leader_path"),
    )


__all__ = [
    "RecommendationAgent",
    "build_sample_input",
    "build_input_from_integration_files",
    "enrollment_to_grade",
    "load_config",
    "_enrollment_to_grade",
    "_load_config",
]


if __name__ == "__main__":
    import json

    config = load_config()
    agent = RecommendationAgent(config)
    test_input = build_sample_input(
        config,
        sample_path="./tests/fixtures/recommendation_input_sample.json",
    )
    result = agent.run(test_input)

    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    output_dir = resolve_path(storage.get("output_path", "./data/output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    task_id = result.get("task_id") or "sample"
    output_file = output_dir / f"recommendation_result_{task_id}.json"
    output_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[saved] {output_file}")
