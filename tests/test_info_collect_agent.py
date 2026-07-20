from pathlib import Path

from agents.info_collect_agent import InfoCollectAgent
from agents.main_agent import MainAgent


REQUIRED_OUTPUT_FIELDS = {
    "task_id", "agent_name", "status", "data", "message",
    "error", "next_action", "metadata",
}


def build_input(**business_overrides):
    business = {"sources": [], "keywords": [], **business_overrides}
    return {
        "task_id": "collect_test_001",
        "user_input": "查找人工智能竞赛",
        "task_type": "info_collect",
        "user_profile": {"interests": ["人工智能"]},
        "context": {},
        "input_data": business,
        "history": [],
        "required_output": "json",
        "metadata": {},
    }


def test_output_schema_on_need_input():
    result = InfoCollectAgent(config={}).run(build_input())
    assert REQUIRED_OUTPUT_FIELDS <= result.keys()
    assert result["status"] == "need_input"
    assert result["agent_name"] == "info_collect_agent"


def test_invalid_source_is_caught():
    result = InfoCollectAgent(config={}).run(
        build_input(sources=["not_a_real_source"], keywords=["test"])
    )
    assert result["status"] == "failed"
    assert isinstance(result["error"], dict)


def test_local_txt_file_is_parsed(tmp_path: Path):
    notice = tmp_path / "test_notice.txt"
    notice.write_text("温州大学人工智能竞赛报名通知", encoding="utf-8")
    config = {"storage": {"raw_data_path": str(tmp_path / "raw")}}
    result = InfoCollectAgent(config=config).run(
        build_input(sources=["local_file"], file_paths=[str(notice)])
    )

    assert result["status"] == "success"
    assert len(result["data"]["raw_items"]) == 1
    item = result["data"]["raw_items"][0]
    assert item["source"] == "local_file"
    assert item["file_type"] == ".txt"
    assert "温州大学" in item["raw_text"]


def test_main_agent_adapts_saikr_web_input():
    main_agent = MainAgent(config={})
    original = build_input(
        sources=[], data_source="web", source_url="https://www.saikr.com/"
    )
    adapted = main_agent._adapt_info_collect_input(original)

    assert adapted["sources"] == ["saikr"]
    assert adapted["keywords"] == ["人工智能"]


def test_main_agent_does_not_mislabel_unknown_websites():
    main_agent = MainAgent(config={})
    original = build_input(
        sources=[], data_source="web", source_url="https://example.com/competition"
    )
    adapted = main_agent._adapt_info_collect_input(original)

    assert "sources" not in adapted or not adapted["sources"]


def test_main_agent_runs_local_collection_end_to_end(tmp_path: Path):
    notice = tmp_path / "main_agent_notice.txt"
    notice.write_text("温州大学程序设计竞赛通知", encoding="utf-8")
    main_agent = MainAgent(
        config={"storage": {"raw_data_path": str(tmp_path / "main_raw")}}
    )
    original = build_input(
        sources=["local_file"],
        file_paths=[str(notice)],
    )

    result = main_agent.run(original)

    assert result["status"] == "success"
    agent_result = result["data"]["agent_results"][0]
    assert agent_result["agent_name"] == "info_collect_agent"
    assert agent_result["status"] == "success"
    assert "温州大学" in agent_result["data"]["raw_items"][0]["raw_text"]
