# 赛智通（SaiZhiTong）

赛智通是面向大学生科研与竞赛场景的多智能体对话助手。用户可以像使用 ChatGPT 一样描述自己的专业、年级、兴趣和参赛目标；系统会在信息不足时继续追问，随后完成竞赛信息采集、通知抽取、项目推荐、赛事详情解释和报名材料生成。

> 当前版本用于课程、竞赛和研究演示。竞赛信息、推荐结果与生成材料仅供辅助决策，正式报名或提交前请以赛事官网为准并人工复核。

## 当前功能

- GPT 风格对话界面：使用 Streamlit 提供连续对话、历史消息、快捷任务和会话状态展示。
- 上下文信息收集：逐项收集专业、年级、竞赛方向、竞赛级别和技能，无需重复填写表单。
- 竞赛信息采集：读取赛氪公开竞赛数据，也支持解析本地通知文件。
- 通知结构化抽取：提取名称、截止日期、主办方、参赛要求和原始网页等字段。
- 个性化推荐：综合用户画像、兴趣、截止日期和硬性条件进行筛选与排序。
- 赛事详情追问：用户可通过“详细介绍第二个”等自然语言继续了解刚才的推荐结果。
- 智能任务路由：根据当前对话状态区分信息补充、项目推荐、赛事详情和材料生成，避免重复推荐。
- Word 材料生成：生成可编辑的 `.docx` 初稿，支持竞赛报名个人简历及项目材料；文件名包含对应竞赛名称。
- 降级运行：LLM 暂时不可用时，系统仍会尽量保留采集到的可信字段并使用规则完成基础流程。

## Agent 分工

```text
用户对话
   │
   ▼
MainAgent（理解意图、维护上下文、调度与整合结果）
   │
   ├── InfoCollectAgent       采集公开竞赛数据或解析本地文件
   ├── InfoExtractAgent       抽取结构化竞赛字段
   ├── RecommendationAgent    补全推荐所需画像并完成匹配排序
   └── MaterialAgent          生成可下载的 Word 报名材料
```

典型流程：

```text
竞赛推荐：信息补全 → 信息采集 → 信息抽取 → 项目推荐
粘贴通知：通知抽取 → 详情展示或项目推荐
了解项目：读取本轮推荐上下文 → 返回简介、官网和待核实事项
生成材料：确认目标竞赛与材料类型 → MaterialAgent → Word 下载
```

无关问题不会被误判为竞赛任务。系统会说明当前能力范围，并引导用户回到竞赛推荐、通知分析或材料生成。

## 项目结构

```text
.
├── agents/
│   ├── main_agent.py              # 主调度与对话意图处理
│   ├── info_collect_agent.py      # 信息采集 Agent
│   ├── info_extract_agent.py      # 信息抽取 Agent
│   ├── recommendation_agent.py    # 项目推荐 Agent
│   ├── material_agent.py          # Word 材料生成 Agent
│   └── info_collect/              # 采集器、解析器和存储组件
├── config/
│   ├── config.yaml                # 非敏感运行配置
│   ├── extraction_prompt.yaml     # 信息抽取提示词
│   └── material_prompts.yaml      # 材料模板
├── data/                          # 运行数据与生成文件
├── docs/                          # 项目规范文档
├── tests/                         # 自动化测试
├── streamlit_app.py               # 主要 Web 对话入口
├── app.py                         # 旧版 Gradio 调试入口
├── main.py                        # 命令行演示入口
├── render.yaml                    # Render 备用部署配置
└── requirements.txt               # Python 依赖
```

## 环境要求

- Python 3.11（推荐版本）
- pip
- DeepSeek API Key（建议配置；未配置时部分能力进入降级模式）

安装依赖：

```powershell
pip install -r requirements.txt
```

Windows 下创建本地环境变量文件：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中填写：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-chat
```

不要把真实 API Key 写入源码、README 或 Git 提交。`.env` 已被 Git 忽略。

## 本地运行

推荐使用 Streamlit 对话界面：

```powershell
streamlit run streamlit_app.py
```

浏览器通常会自动打开 `http://localhost:8501`。如未自动打开，请手动访问该地址。

旧版 Gradio 调试界面仍可运行：

```powershell
python app.py
```

默认地址为 `http://127.0.0.1:7860`。

## 对话示例

```text
用户：我是计算机专业大三学生，想参加人工智能方向的国家级竞赛。
助手：你目前掌握哪些技能？例如 Python、算法、机器学习或团队协作。
用户：我会 Python 和机器学习，也有团队协作经验。
助手：根据已记录的信息，为你采集并推荐合适的竞赛……
用户：详细介绍第二个。
助手：返回该竞赛的简要概括、匹配原因、截止日期、官网链接和待核实事项。
用户：给第二个竞赛生成报名个人简历。
助手：确认目标和材料类型后生成 Word 文件，可在侧栏下载。
```

生成的文件示例：

```text
2026华智高校大学生人工智能大赛_竞赛报名个人简历.docx
```

## 自动化测试

运行完整测试：

```powershell
python -m pytest -q -p no:cacheprovider
```

测试覆盖四个子 Agent、MainAgent 调度、对话状态、意图纠正、推荐详情、材料选择、Word 文件生成以及 LLM 降级流程。

## 部署到 Streamlit Community Cloud

1. 将功能分支通过 Pull Request 合并到 GitHub `main`。
2. 登录 [Streamlit Community Cloud](https://share.streamlit.io/)。
3. 选择本项目仓库、`main` 分支和入口文件 `streamlit_app.py`。
4. 在 App 的 **Settings → Secrets** 中配置：

   ```toml
   DEEPSEEK_API_KEY = "你的真实密钥"
   DEEPSEEK_MODEL = "deepseek-chat"
   ```

5. 保存后点击 Deploy 或 Reboot app。

后续合并到 `main` 的提交通常会触发自动重新部署。如果线上仍显示旧版，可在 Streamlit 管理页面执行 Reboot app。

## 数据与生成文件

- `data/raw`：采集到的原始竞赛数据和日志。
- `data/processed`：结构化处理结果。
- `data/output`：MaterialAgent 生成的 `.docx` 文件。
- `data/temp`：运行期临时文件。

当前版本没有接入持久化竞赛数据库，竞赛数据主要在请求时从公开来源采集。Streamlit Community Cloud 等免费实例使用临时文件系统，重启或重新部署后，运行期数据和生成文件可能丢失；用户应在生成后及时下载 Word 文件。

## 已知限制

- 公开网页的网络状态或页面结构变化可能影响采集结果。
- 赛事名称、日期、主办方和报名要求应以链接中的官方页面为准。
- 未配置或无法访问 DeepSeek API 时，复杂意图理解、摘要和通知抽取能力会下降。
- 推荐质量依赖用户画像完整度；信息不足时系统会继续追问。
- Word 材料是可编辑初稿，不保证直接满足所有学校或赛事的正式模板。
- 免费云平台可能休眠，首次访问和首次 Agent 调用可能较慢。

## 安全与隐私

- 不要在公开部署中输入身份证号、银行卡号、密码等敏感信息。
- 不要将 API Key、`.env` 或本地隐私数据提交到 GitHub。
- 生成材料包含个人信息时，请下载后及时检查，并避免在共享设备上长期保留。
- 正式报名和提交前必须人工复核全部内容。

## 设计文档

- [项目规范（中文）](docs/PROJECT_SPEC_CN.md)
- [Project Specification](docs/PROJECT_SPEC.md)
