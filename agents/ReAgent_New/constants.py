"""
默认权重、等级阈值、维度名等常量（config / rules 可覆盖）。
"""

# 对外 Agent 名（与原版一致）
AGENT_NAME = "recommendation_agent"

# 推荐维度默认权重（config.yaml recommendation.weights 优先）
DEFAULT_WEIGHTS = {
    "interest_score": 0.30,
    "ability_score": 0.25,
    "deadline_score": 0.18,
    "team_score": 0.12,
    "grade_score": 0.10,
    "major_score": 0.05,
}

# 权重维度顺序（综合分计算与归一化共用）
WEIGHT_KEYS = tuple(DEFAULT_WEIGHTS.keys())

# 硬性门槛：专业匹配低于此分视为不符合（target_majors 非空时）
HARD_MAJOR_MIN_SCORE = 50

# 推荐等级划分默认阈值：(分数下界, 代码, 中文标签)
LEVEL_THRESHOLDS = [
    (80, "S", "强烈推荐"),
    (65, "A", "推荐"),
    (50, "B", "可考虑"),
    (0, "C", "不推荐"),
]

LEVEL_LABELS = {
    "S": "强烈推荐",
    "A": "推荐",
    "B": "可考虑",
    "C": "不推荐",
}

# 等级排序（用于封顶规则）
LEVEL_ORDER = {"S": 4, "A": 3, "B": 2, "C": 1}

# 维度中文名（用于 reason / risk / action 文案）
DIM_NAME_MAP = {
    "major_score": "专业匹配度",
    "grade_score": "年级/学历匹配度",
    "interest_score": "兴趣匹配度",
    "ability_score": "能力匹配度",
    "deadline_score": "截止时间可行性",
    "team_score": "团队匹配度",
}

# 推荐文案使用的维度（专业/年级多数不限，不作文案主依据）
COPY_DIM_KEYS = (
    "interest_score",
    "ability_score",
    "deadline_score",
    "team_score",
)

# 默认等级封顶规则
DEFAULT_LEVEL_CAPS = {
    "grade_score_below": 40,
    "ability_score_below": 30,
    "max_level": "B",
}
