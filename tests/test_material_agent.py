from pathlib import Path

from agents.main_agent import MainAgent
from agents.material_agent import MaterialAgent


def material_config(tmp_path: Path):
    return {
        "llm": {
            "api_key_env": "MATERIAL_TEST_MISSING_KEY",
            "base_url": "https://example.com/v1",
            "model": "test-model",
            "timeout": 17,
        },
        "agent": {
            "max_retry": 2,
            "material_agent": {
                "prompt_config_path": "./config/material_prompts.yaml",
                "default_style": "formal",
                "default_language": "zh-CN",
            }
        },
        "storage": {
            "output_path": str(tmp_path / "output"),
            "temp_path": str(tmp_path / "temp"),
        },
    }


def standard_input(payload):
    return {
        "task_id": "material_test_001",
        "user_input": "生成项目进度计划",
        "task_type": "material",
        "user_profile": {"major": "计算机科学与技术", "grade": "大二"},
        "context": {},
        "input_data": payload,
        "history": [],
        "required_output": "markdown",
        "metadata": {},
    }


def test_validation_failure_uses_standard_output(tmp_path, monkeypatch):
    monkeypatch.delenv("MATERIAL_TEST_MISSING_KEY", raising=False)
    result = MaterialAgent(material_config(tmp_path)).run(standard_input({}))

    assert result["status"] == "failed"
    assert result["agent_name"] == "material_agent"
    assert result["error"]["error_type"] == "ValidationError"


def test_mock_material_generation_and_files(tmp_path, monkeypatch):
    monkeypatch.delenv("MATERIAL_TEST_MISSING_KEY", raising=False)
    agent = MaterialAgent(material_config(tmp_path))
    assert agent.model_name == "test-model"
    assert agent.api_timeout == 17
    assert agent.max_retry == 2
    result = agent.run(standard_input({
        "project_info": {
            "project_name": "校园智能竞赛助手",
            "background": "帮助大学生准备竞赛申请",
        },
        "user_profile": {"major": "计算机科学与技术"},
        "material_type": "generic_schedule",
    }))

    assert result["status"] == "success"
    assert result["data"]["material_type"] == "generic_schedule"
    assert result["data"]["content"]["sections"]
    saved_files = result["data"]["_saved_files"]
    assert len(saved_files) == 1
    output_path = Path(saved_files[0])
    assert output_path.is_file()
    assert output_path.suffix == ".docx"
    assert "校园智能竞赛助手" in output_path.name

    from docx import Document

    document = Document(output_path)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "校园智能竞赛助手" in text
    assert "准备清单" in text


def test_main_agent_adapts_recommended_project(tmp_path):
    main_agent = MainAgent(config=material_config(tmp_path))
    item = {
        "title": "全国大学生人工智能竞赛",
        "type": "学科竞赛",
        "deadline": "2026-09-30",
        "organizer": "示例组委会",
    }
    adapted = main_agent._adapt_material_input(
        standard_input({}),
        {
            "info_extract_result": {"structured_items": [item]},
            "recommendation_result": {
                "recommendations": [{"title": item["title"]}]
            },
        },
    )

    assert adapted["project_info"]["project_name"] == item["title"]
    assert adapted["competition_info"]["deadline"] == "2026-09-30"


def test_personal_resume_template_generates_word_file(tmp_path, monkeypatch):
    monkeypatch.delenv("MATERIAL_TEST_MISSING_KEY", raising=False)
    result = MaterialAgent(material_config(tmp_path)).run(standard_input({
        "project_info": {"project_name": "算法程序设计赛"},
        "competition_info": {
            "competition_name": "算法程序设计赛",
            "deadline": "2026-09-30",
        },
        "user_profile": {
            "major": "计算机科学与技术",
            "grade": "大三",
            "skills": ["Python", "算法"],
        },
        "material_type": "generic_personal_resume",
    }))

    assert result["status"] == "success"
    assert result["data"]["material_name"] == "竞赛报名个人简历"
    path = Path(result["data"]["_saved_files"][0])
    assert path.name == "算法程序设计赛_竞赛报名个人简历.docx"


def test_main_agent_runs_material_end_to_end(tmp_path, monkeypatch):
    monkeypatch.delenv("MATERIAL_TEST_MISSING_KEY", raising=False)
    main_agent = MainAgent(config=material_config(tmp_path))
    request = standard_input({
        "project_info": {"project_name": "校园智能竞赛助手"},
        "material_type": "generic_schedule",
    })

    result = main_agent.run(request)

    assert result["status"] == "success"
    agent_result = result["data"]["agent_results"][0]
    assert agent_result["agent_name"] == "material_agent"
    assert agent_result["status"] == "success"
