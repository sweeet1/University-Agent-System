# 赛智通（SaiZhiTong）

赛智通是面向大学生科研与竞赛场景的多智能体辅助系统。系统通过多轮对话收集用户背景，完成竞赛信息采集、通知结构化抽取、项目匹配推荐，并生成可下载的申报材料初稿。

> 当前版本用于课程、竞赛和研究演示。推荐结果与生成材料仅供辅助决策，正式报名或提交前请人工核验。

## 功能概览

- 对话式信息收集：逐步询问专业、年级、竞赛方向、竞赛级别和技能，并在会话中保留上下文。
- 竞赛信息采集：当前接入赛氪公开竞赛数据，也支持本地文件解析。
- 通知信息抽取：从通知正文或采集结果中抽取标题、截止日期、主办方、报名要求等字段。
- 智能推荐：结合专业、年级、兴趣、技能和截止日期进行多维评分与硬约束过滤。
- 申报材料生成：支持挑战杯、创新创业和通用材料模板，并输出 Markdown 与 JSON 文件。
- 双界面入口：提供 Streamlit 对话页面和 Gradio 高级表单页面。
- 降级保障：LLM 不可用时保留采集到的可信字段，不再将有效项目显示为 `unknown`。

## 系统流程

```text
用户对话
   │
   ▼
MainAgent（任务理解、依赖调度、结果整合）
   │
   ├── InfoCollectAgent       采集公开竞赛或解析本地文件
   ├── InfoExtractAgent       抽取结构化项目字段
   ├── RecommendationAgent    用户画像匹配与项目排序
   └── MaterialAgent          生成申报材料与下载文件
```

系统会根据已有数据选择正确的起点。例如：

```text
公开数据推荐：信息采集 → 信息抽取 → 项目推荐
粘贴通知推荐：信息抽取 → 项目推荐
粘贴通知生成材料：信息抽取 → 材料生成
完整流程：信息抽取/采集 → 项目推荐 → 材料生成
```

## 项目结构

```text
.
├── agents/
│   ├── main_agent.py              # 主调度 Agent
│   ├── info_collect_agent.py      # 信息采集 Agent
│   ├── info_extract_agent.py      # 信息抽取 Agent
│   ├── recommendation_agent.py    # 项目推荐 Agent
│   ├── material_agent.py          # 申报材料 Agent
│   └── info_collect/              # 采集器、解析器和存储组件
├── config/
│   ├── config.yaml                # 非敏感运行配置
│   ├── extraction_prompt.yaml     # 信息抽取提示词
│   └── material_prompts.yaml      # 材料模板
├── data/                          # 运行数据与生成文件
├── docs/                          # 项目设计文档
├── tests/                         # 自动化测试
├── app.py                         # Gradio 页面入口
├── streamlit_app.py               # Streamlit Cloud 部署入口
├── main.py                        # 命令行演示入口
├── render.yaml                    # Render 部署配置
└── requirements.txt               # Python 依赖
```

## 环境要求

- Python 3.11（云端部署推荐版本）
- pip
- DeepSeek API Key（推荐配置；未配置时部分功能进入降级模式）

安装依赖：

```bash
pip install -r requirements.txt
```

复制环境变量模板：

```bash
copy .env.example .env
```

macOS 或 Linux：

```bash
cp .env.example .env
```

在 `.env` 中填写：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-chat
```

真实密钥不得写入源码、README 或 Git 提交。`.env` 已被 Git 忽略。

## 本地运行

### Streamlit 对话界面

```bash
streamlit run streamlit_app.py
```

默认访问地址：`http://localhost:8501`

### Gradio 界面

```bash
python app.py
```

默认访问地址：`http://127.0.0.1:7860`

允许局域网访问：

```bash
python app.py --host 0.0.0.0 --port 7860
```

## 对话示例

```text
用户：我是计算机专业大三学生，想参加国家级人工智能竞赛。
助手：你目前掌握哪些技能？例如 Python、C++、算法、机器学习或团队协作。
用户：我会 Python、机器学习，也有团队协作经验。
助手：开始采集并推荐符合条件的竞赛……
用户：给刚才推荐的第一个项目生成报名材料。
助手：材料已生成，可在页面右侧下载 Markdown 和 JSON 文件。
```

## 自动化测试

运行完整测试：

```bash
python -m pytest -q
```

当前测试覆盖：

- 四个子 Agent 的输入校验与核心流程
- MainAgent 输入适配和调度链
- Gradio 表单与演示案例
- Streamlit 多轮对话状态
- 材料生成与文件保存
- LLM 降级时的采集字段保留

## 部署到 Streamlit Community Cloud

1. 将最新代码合并到 GitHub `main` 分支。
2. 访问 [Streamlit Community Cloud](https://share.streamlit.io/) 并使用 GitHub 登录。
3. 创建 App，选择仓库和 `main` 分支。
4. Main file path 填写 `streamlit_app.py`。
5. Advanced settings 中选择 Python 3.11。
6. 在 Secrets 中填写：

   ```toml
   DEEPSEEK_API_KEY = "你的真实密钥"
   ```

7. 点击 Deploy。

Streamlit 会分配一个 `https://<应用名>.streamlit.app` 地址。GitHub 仓库为 Private 时，部署出的 App 默认也受访问权限限制；如需任何人无需登录即可访问，应使用公开仓库。

## 部署到 Render

项目保留 `render.yaml`，也可以部署为 Render Web Service：

```text
Runtime: Python 3
Build Command: pip install -r requirements.txt
Start Command: python app.py
Health Check Path: /
```

需要配置：

```text
PYTHON_VERSION=3.11.11
HOST=0.0.0.0
DEEPSEEK_API_KEY=<secret>
```

端口由 Render 的 `PORT` 环境变量自动注入。

## 数据与文件说明

- `data/raw`：采集到的原始竞赛数据和日志。
- `data/processed`：结构化处理结果。
- `data/output`：MaterialAgent 生成的 Markdown 与 JSON 文件。
- `data/temp`：运行期临时文件。

Streamlit Community Cloud 和 Render 免费实例均使用临时文件系统，应用重启或重新部署后，运行期采集数据和生成文件可能丢失。当前版本会实时采集公开数据，尚未接入持久化竞赛数据库；如需稳定项目库，应接入外部数据库或对象存储，并配置定时采集任务。

## 已知限制

- 当前网页采集主要支持赛氪数据源，网络或站点结构变化可能影响结果。
- 未配置或无法访问 DeepSeek API 时，系统使用规则和采集字段降级运行，复杂通知理解能力会下降。
- 推荐依赖用户画像完整度；专业、年级、技能等信息不足时，系统会继续追问。
- 生成材料属于初稿，不保证直接满足所有学校或赛事的正式格式。
- 免费云平台可能休眠，首次访问和首次 Agent 调用耗时较长。

## 安全与隐私

- 不要输入身份证号、银行卡号、密码等敏感信息。
- 不要将 API Key 提交到 GitHub。
- 部署公开应用前，确认仓库中不存在个人信息、密钥和本地运行数据。
- 正式提交申报材料前必须人工复核。

## 设计文档

- [项目规范（中文）](docs/PROJECT_SPEC_CN.md)
- [Project Specification](docs/PROJECT_SPEC.md)
