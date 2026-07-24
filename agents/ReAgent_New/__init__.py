"""
ReAgent_New — RecommendationAgent 多模块实现包。

Step 0：输入 / 输出契约（与 agents/recommendation_agent.py 对齐，便于日后替换入口）。
业务打分逻辑未在本步实现；后续步骤不得擅自删减下列必选字段。

依据：
    - docs/PROJECT_SPEC_CN.md 第 12.3 节
    - agents/recommendation_agent.py 中 RecommendationAgent.run 文档字符串
    - tests/fixtures/recommendation_input_sample.json
"""

from .constants import AGENT_NAME

# ---------------------------------------------------------------------------
# 统一响应外壳必选键
# ---------------------------------------------------------------------------
RESPONSE_KEYS = frozenset({
    "task_id",      # 本轮任务编号，透传自输入，便于日志与结果落盘关联
    "agent_name",   # 产出该结果的 Agent 标识，固定为 recommendation_agent
    "status",       # 执行状态：success / failed / partial / need_input / skipped
    "data",         # 业务结果载荷（推荐列表、计数等）；失败时多为空 dict
    "message",      # 给人看的简短说明（成功摘要或失败提示）
    "error",        # 失败时的错误详情 dict；成功时为 None
    "next_action",  # 建议的下一步动作（如 ask_user）；无则 None
    "metadata",     # 附加元信息（调试、耗时等），默认可为空 dict
})

ALLOWED_STATUS = frozenset({
    "success",     # 正常产出至少一条推荐
    "failed",      # 校验失败或处理异常，不可用
    "partial",     # 跑通流程但无可用推荐（如全被硬门槛过滤）
    "need_input",  # 缺关键输入（画像 / 候选列表），需用户或上游补充
    "skipped",     # 被调度层跳过（契约预留，本 Agent 少用）
})

# ---------------------------------------------------------------------------
# 输入契约
# ---------------------------------------------------------------------------
# 顶层常用字段（MainAgent 下发）
INPUT_TOP_KEYS = (
    "task_id",          # 任务编号
    "user_input",       # 用户原始自然语言（如「帮我推荐竞赛」）
    "task_type",        # 任务类型，推荐场景一般为 recommendation
    "user_profile",     # 用户画像（专业、年级、兴趣、技能等）
    "context",          # 会话/上游上下文（可含其他 Agent 中间结果）
    "input_data",       # 本 Agent 业务数据：structured_items、rules 等
    "history",          # 多轮对话历史（本 Agent 当前可选用）
    "required_output",  # 期望输出形态（如 markdown），展示层可用
    "metadata",         # 请求级附加信息
)

# user_profile 画像字段（与样例 / 原版一致；校验时不必全部非空）
USER_PROFILE_KEYS = (
    "nickname",                 # 昵称 / 称呼，展示用
    "school",                   # 所在学校（后续可做校内赛加分）
    "major",                    # 专业，用于专业匹配与硬门槛
    "enrollment_year",          # 入学年份，用于推断年级
    "education_level",          # 学历层次（本科/硕士等），学历门槛与打分
    "gpa",                      # 绩点，原版未参与打分，契约预留
    "skills",                   # 技能标签列表，能力匹配主输入
    "interests",                # 兴趣标签列表，兴趣匹配主输入
    "awards",                   # 获奖记录（名称/等级/年份等），可并入能力语料
    "competition_experience",   # 竞赛经历文本列表，能力/相关性辅助
    "research_experience",      # 科研经历文本列表，能力/相关性辅助
    "available_time",           # 可参赛时间窗（如 2026年7月-9月），影响截止分
    "team_status",              # 组队状态：单人申报 / 寻找队友 / 已有团队
)

# input_data 业务段
INPUT_DATA_KEYS = (
    "structured_items",      # InfoExtractAgent 产出的结构化竞赛列表（主候选集）
    "user_profile",          # 画像也可嵌在此处；与顶层 user_profile 二选一或互补
    "recommendation_rules",  # 可选：覆盖默认权重、Top-N、等级封顶等规则
)

# structured_items[] 单条项目字段
STRUCTURED_ITEM_KEYS = (
    "title",              # 竞赛 / 项目名称
    "type",               # 项目类型（如学科竞赛）
    "deadline",           # 报名截止日期字符串
    "registration_time",  # 报名时间说明（原文或区间描述）
    "requirements",       # 参赛要求 dict（专业/年级/技能/组队/标签等）
    "reward",             # 奖项与奖励说明
    "organizer",          # 主办方
    "source_url",         # 来源链接（赛氪等）
    "summary",            # 项目摘要，供展示与后续材料生成
)

# requirements 子字段
REQUIREMENT_KEYS = (
    "target_majors",      # 面向专业列表；空表示不限
    "target_grades",      # 面向年级列表（如大一、大二）；空表示不限
    "target_education",   # 面向学历列表；空表示不限
    "required_skills",    # 建议/要求的技能列表，能力打分依据
    "team_requirement",   # 组队要求（单人/组队/不限等）
    "tags",               # 主题标签（数学建模、AI 等），兴趣匹配依据
    "category",           # 赛事大类 / 分类
)

# recommendation_rules 可选覆盖
RECOMMENDATION_RULE_KEYS = (
    "weights",  # 覆盖六维权重（interest_score 等）
    "top_n",    # 返回推荐条数，默认 3
    "caps",     # 等级封顶规则（如年级/能力过低时最高只能 B）
)

# ---------------------------------------------------------------------------
# 输出契约 — data 段
# ---------------------------------------------------------------------------
DATA_KEYS = (
    "recommendations",       # Top-N 推荐结果列表
    "recommendation_pool",   # 一次打分缓存的更大候选池，供扩容复用
    "total_count",           # 输入候选项目总数
    "matched_count",         # 通过硬门槛并参与排序的项目数
    "hard_filtered_count",   # 被硬性门槛剔除的数量（原版已返回，契约保留）
    "filtered_out",          # Step7：被过滤项目及原因 [{title, reason}, ...]
)

# recommendations[] 每条至少含下列字段（原版另附 source_url 等展示字段，可只增不删）
RECOMMENDATION_REQUIRED_KEYS = frozenset({
    "title",             # 推荐项目名称
    "match_score",       # 加权综合分 0–100
    "recommend_level",   # 推荐等级 S / A / B / C
    "reason",            # 推荐理由文案
    "risk",              # 风险或注意点文案
    "suggested_action",  # 建议用户下一步做什么
    "detail",            # 各维度分数字典，供调试与前端展开
})

RECOMMENDATION_OPTIONAL_KEYS = (
    "source_url",  # 项目链接，方便跳转详情
    "summary",     # 项目摘要，列表页展示
    "deadline",    # 截止日期，列表页展示
    "organizer",   # 主办方，列表页展示
    "type",        # 项目类型，列表页展示
    "category_key",       # 归一分类（多样性）
    "prestige_tier",      # 赛事层级
    "matched_signals",    # 命中信号（解释/前端）
    "unmatched_signals",  # 未命中信号
    "is_backup",          # 是否备选（质量门槛）
    "rank",               # 结果序号
    "id",                 # 稳定定位 id
)

# detail 六维分数字段
DETAIL_SCORE_KEYS = (
    "major_score",     # 专业匹配分
    "grade_score",     # 年级 / 学历匹配分
    "interest_score",  # 兴趣标签匹配分
    "ability_score",   # 能力 / 技能 / 经历匹配分
    "deadline_score",  # 截止时间可行性分
    "team_score",      # 组队状态与项目要求匹配分
)

RECOMMEND_LEVELS = frozenset({
    "S",  # 强烈推荐
    "A",  # 推荐
    "B",  # 可考虑
    "C",  # 不推荐 / 备选观望
})


# ---------------------------------------------------------------------------
# 契约示例（文档用，非运行数据）
# ---------------------------------------------------------------------------
#
# 输入要点::
#
# {
#   "task_id": str,
#   "user_input": str,
#   "task_type": "recommendation",
#   "user_profile": { ... USER_PROFILE_KEYS ... },
#   "input_data": {
#     "structured_items": [ { ... STRUCTURED_ITEM_KEYS ... } ],
#     "recommendation_rules": { "weights": {}, "top_n": 3, "caps": {} }
#   }
# }
#
# 输出要点::
#
# {
#   "task_id": "",
#   "agent_name": "recommendation_agent",
#   "status": "success | failed | partial | need_input | skipped",
#   "data": {
#     "recommendations": [
#       {
#         "title": str,
#         "match_score": float,
#         "recommend_level": "S|A|B|C",
#         "reason": str,
#         "risk": str,
#         "suggested_action": str,
#         "detail": { ... DETAIL_SCORE_KEYS ... }
#       }
#     ],
#     "total_count": 0,
#     "matched_count": 0,
#     "hard_filtered_count": 0
#   },
#   "message": "",
#   "error": null,
#   "next_action": null,
#   "metadata": {}
# }
#
# ---------------------------------------------------------------------------
# 包导出（Step 1 起可导入 RecommendationAgent；业务逻辑后续步骤补齐）
# ---------------------------------------------------------------------------
from .agent import RecommendationAgent  # noqa: E402

__all__ = [
    "AGENT_NAME",
    "RecommendationAgent",
    "RESPONSE_KEYS",
    "ALLOWED_STATUS",
    "RECOMMENDATION_REQUIRED_KEYS",
    "DETAIL_SCORE_KEYS",
]
