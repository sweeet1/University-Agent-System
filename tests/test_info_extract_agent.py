from types import SimpleNamespace

from agents.info_extract_agent import InfoExtractAgent
from agents.main_agent import MainAgent


REQUIRED_OUTPUT_FIELDS = {
    "task_id", "agent_name", "status", "data", "message",
    "error", "next_action", "metadata",
}


def standard_input(payload):
    return {
        "task_id": "extract_test_001",
        "user_input": "抽取竞赛通知",
        "task_type": "info_extract",
        "user_profile": {},
        "context": {},
        "input_data": payload,
        "history": [],
        "required_output": "json",
        "metadata": {},
    }


def test_validation_failure_uses_standard_output():
    result = InfoExtractAgent(config={}).run(standard_input({}))

    assert REQUIRED_OUTPUT_FIELDS <= result.keys()
    assert result["status"] == "failed"
    assert result["agent_name"] == "info_extract_agent"
    assert result["error"]["error_type"] == "ValidationError"


def test_mock_extraction_returns_structured_item():
    agent = InfoExtractAgent(config={})
    result = agent.run(standard_input({"raw_items": [{
        "title": "数学建模竞赛通知",
        "url": "https://example.com/notice",
        "source": "test",
        "raw_text": "报名截止日期为2026年9月1日。",
    }]}))

    assert result["status"] == "success"
    assert len(result["data"]["structured_items"]) == 1
    item = result["data"]["structured_items"][0]
    assert item["_extract_status"] == "success"
    assert item["source_url"] == "https://example.com/notice"


def test_main_agent_adapts_pasted_notification():
    main_agent = MainAgent(config={})
    original = standard_input({
        "data_source": "upload",
        "source_url": "https://example.com/source",
        "notification_text": "温州大学程序设计竞赛报名通知",
    })
    adapted = main_agent._adapt_info_extract_input(original, {})

    assert len(adapted["raw_items"]) == 1
    assert adapted["raw_items"][0]["raw_text"].startswith("温州大学")
    assert adapted["raw_items"][0]["url"] == "https://example.com/source"


def test_main_agent_uses_collection_result():
    main_agent = MainAgent(config={})
    collected = [{"title": "采集结果", "raw_text": "竞赛通知正文"}]
    adapted = main_agent._adapt_info_extract_input(
        standard_input({}), {"info_collect_result": {"raw_items": collected}}
    )

    assert adapted["raw_items"] == collected


def test_main_agent_runs_pasted_notice_end_to_end():
    main_agent = MainAgent(config={})
    request = standard_input({
        "data_source": "upload",
        "notification_text": "关于举办2026年大学生程序设计竞赛的通知。",
    })

    result = main_agent.run(request)

    assert result["status"] == "success"
    agent_result = result["data"]["agent_results"][0]
    assert agent_result["agent_name"] == "info_extract_agent"
    assert agent_result["status"] == "success"
    assert len(agent_result["data"]["structured_items"]) == 1


def test_main_llm_configuration_is_used(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content='{"title": "configured"}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    fake_openai = SimpleNamespace(OpenAI=lambda **kwargs: fake_client)
    monkeypatch.setenv("TEST_LLM_KEY", "test-only-key")

    agent = InfoExtractAgent(config={
        "llm": {
            "api_key_env": "TEST_LLM_KEY",
            "base_url": "https://example.com/v1",
            "model": "configured-model",
        },
        "agent": {"max_retry": 1},
    })
    agent._openai_available = True
    agent.openai = fake_openai

    response = agent._call_api([])

    assert response == '{"title": "configured"}'
    assert captured["model"] == "configured-model"
